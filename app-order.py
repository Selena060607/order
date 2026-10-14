import pandas as pd
import streamlit as st


TEAM_NAME = "Team 10"  # Replace this with your actual team name.

st.set_page_config(page_title="Delivery Promise Review", layout="wide")

# One row is one Olist order. The CSV sits in the app's working directory.
df = pd.read_csv("olist_orders_dataset.csv")

date_columns = [
    "order_purchase_timestamp",
    "order_delivered_carrier_date",
    "order_delivered_customer_date",
    "order_estimated_delivery_date",
]
for column in date_columns:
    df[column] = pd.to_datetime(df[column], errors="coerce")

purchase_start = df["order_purchase_timestamp"].min()
purchase_end = df["order_purchase_timestamp"].max()

# The CSV has no extraction timestamp. This is only a proxy for the last
# observable day; it is not a claim that the data was complete on that day.
last_observed_event = max(
    df["order_purchase_timestamp"].max(),
    df["order_delivered_carrier_date"].max(),
    df["order_delivered_customer_date"].max(),
)
observation_cutoff = last_observed_event.normalize() + pd.Timedelta(days=1)

# Canceled/unavailable orders have no event date for that outcome. Exclude them
# from the delivery-promise denominator rather than label them as late.
excluded_status = df["order_status"].isin(["canceled", "unavailable"])
missing_delivered_date = (
    (df["order_status"] == "delivered")
    & df["order_delivered_customer_date"].isna()
)

orders = df[
    df["order_purchase_timestamp"].notna()
    & df["order_estimated_delivery_date"].notna()
    & (df["order_estimated_delivery_date"] < observation_cutoff)
    & ~excluded_status
    & ~missing_delivered_date
].copy()

# Compare calendar dates because the promised delivery field has date-level
# meaning (00:00:00), while actual delivery includes time of day.
orders["delivered_late"] = (
    orders["order_delivered_customer_date"].notna()
    & (
        orders["order_delivered_customer_date"].dt.normalize()
        > orders["order_estimated_delivery_date"].dt.normalize()
    )
)
orders["no_delivery_record"] = orders["order_delivered_customer_date"].isna()
orders["promise_missed"] = (
    orders["delivered_late"] | orders["no_delivery_record"]
)
orders["purchase_month"] = orders["order_purchase_timestamp"].dt.to_period("M").astype(str)

monthly = orders.groupby("purchase_month", sort=True).agg(
    order_count=("order_id", "size"),
    missed=("promise_missed", "sum"),
    delivered_late=("delivered_late", "sum"),
    no_delivery_record=("no_delivery_record", "sum"),
)
monthly["miss_rate_pct"] = 100 * monthly["missed"] / monthly["order_count"]

# Sparse opening and closing months would make a monthly comparison misleading.
month_options = monthly.index[monthly["order_count"] >= 500].tolist()
if not month_options:
    st.error("No purchase month has enough due orders for this review.")
    st.stop()

st.title(f"{TEAM_NAME} | Delivery Promise Review")
st.caption(
    "For the fulfillment manager: identify a rise in missed delivery promises "
    "and decide whether to investigate handoff or delivery time."
)

selected_month = st.selectbox(
    "Purchase month to review",
    month_options,
    index=len(month_options) - 1,
)
selected_index = month_options.index(selected_month)
selected_orders = orders[orders["purchase_month"] == selected_month]
current = monthly.loc[selected_month]
current_rate = float(current["miss_rate_pct"])

previous_rate = None
if selected_index > 0:
    previous_month = month_options[selected_index - 1]
    previous_rate = float(monthly.loc[previous_month, "miss_rate_pct"])

delta = None
if previous_rate is not None:
    delta = f"{current_rate - previous_rate:+.1f} pp vs {previous_month}"

col1, col2, col3 = st.columns(3)
with col1:
    st.metric(
        "Missed promise rate",
        f"{current_rate:.1f}%",
        delta=delta,
        delta_color="inverse",
    )
with col2:
    st.metric("Delivered late", f"{int(current['delivered_late']):,}")
with col3:
    st.metric("No delivery recorded", f"{int(current['no_delivery_record']):,}")

st.caption(
    f"Among {int(current['order_count']):,} selected orders whose promised date "
    "had passed by the last observed day: a miss is a late recorded delivery "
    "or no delivery record. Canceled and unavailable orders are excluded."
)

if previous_rate is not None and current_rate - previous_rate >= 2:
    st.warning(
        "Proposed review trigger: the miss rate rose at least 2 percentage "
        "points from the previous month. Check the stage comparison below "
        "before assigning follow-up."
    )

# Chart 1: repeated monthly review of the same decision metric.
recent_months = month_options[max(0, selected_index - 5) : selected_index + 1]
trend = monthly.loc[recent_months, ["miss_rate_pct"]].rename(
    columns={"miss_rate_pct": "Miss rate (%)"}
)
st.subheader("Missed promise rate across recent purchase months")
st.line_chart(trend, y_label="Percent of due orders")

# Chart 2: compare elapsed stages within the selected month. These durations
# can suggest where to investigate, but do not establish the cause of lateness.
completed = selected_orders[
    selected_orders["order_delivered_customer_date"].notna()
    & selected_orders["order_delivered_carrier_date"].notna()
].copy()
completed["handoff_days"] = (
    completed["order_delivered_carrier_date"]
    - completed["order_purchase_timestamp"]
).dt.total_seconds() / 86400
completed["transit_days"] = (
    completed["order_delivered_customer_date"]
    - completed["order_delivered_carrier_date"]
).dt.total_seconds() / 86400
completed = completed[
    (completed["handoff_days"] >= 0) & (completed["transit_days"] >= 0)
]

stage_medians = completed.groupby("delivered_late")[[
    "handoff_days", "transit_days"
]].median()
stage_medians = stage_medians.reindex([False, True]).rename(
    index={False: "On time", True: "Late"},
    columns={
        "handoff_days": "Purchase to carrier handoff",
        "transit_days": "Carrier to customer",
    },
)

st.subheader("Median days by delivery stage")
st.bar_chart(stage_medians, y_label="Days", stack=False)
st.caption(
    "Stage comparison uses delivered orders with valid carrier dates. "
    "Different durations are clues for investigation, not proof of cause."
)

st.caption(
    f"Data: purchases {purchase_start:%Y-%m-%d} to {purchase_end:%Y-%m-%d} "
    "(Kaggle frozen snapshot). Proposed production refresh: weekly; "
    "manager review: monthly after the delivery window closes."
)
st.caption(
    f"Data limits: no extraction timestamp; last observed event was "
    f"{last_observed_event:%Y-%m-%d}. Months with fewer than 500 due orders "
    "are omitted from the selector. An absent delivery timestamp may reflect "
    "an unfinished order or an incomplete record."
)
