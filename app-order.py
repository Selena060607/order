import altair as alt
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
monthly["late_rate_pct"] = 100 * monthly["delivered_late"] / monthly["order_count"]
monthly["no_record_rate_pct"] = (
    100 * monthly["no_delivery_record"] / monthly["order_count"]
)

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
recent_months = month_options[max(0, selected_index - 5) : selected_index + 1]
recent_history = monthly.loc[recent_months]


def mini_trend(column):
    """Monthly history for a small chart inside a headline metric."""
    if len(recent_history) < 2:
        return None
    return recent_history[column].tolist()

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
        chart_data=mini_trend("miss_rate_pct"),
        chart_type="line",
        border=True,
        height=220,
    )
with col2:
    st.metric(
        "Delivered late",
        f"{current['late_rate_pct']:.1f}%",
        chart_data=mini_trend("late_rate_pct"),
        chart_type="line",
        border=True,
        height=220,
    )
with col3:
    st.metric(
        "No delivery recorded",
        f"{current['no_record_rate_pct']:.1f}%",
        chart_data=mini_trend("no_record_rate_pct"),
        chart_type="line",
        border=True,
        height=220,
    )

st.caption(
    f"{int(current['order_count']):,} due orders in {selected_month}: "
    f"{int(current['delivered_late']):,} delivered late and "
    f"{int(current['no_delivery_record']):,} without a delivery record. "
    f"Small trends show {recent_months[0]}–{selected_month}."
)

if previous_rate is not None and current_rate - previous_rate >= 2:
    st.warning(
        f"Missed promises rose {current_rate - previous_rate:.1f} percentage "
        f"points vs {previous_month}. Review the delivery stages below."
    )

# Chart 1: zoom in on the last four months to show the recent change.
chart_months = recent_months[-4:]
trend = monthly.loc[chart_months].reset_index()
trend_parts = trend.melt(
    id_vars="purchase_month",
    value_vars=["late_rate_pct", "no_record_rate_pct"],
    var_name="outcome",
    value_name="rate_pct",
)
trend_parts["outcome"] = trend_parts["outcome"].map(
    {
        "late_rate_pct": "Delivered late",
        "no_record_rate_pct": "No delivery record",
    }
)

month_axis = alt.X(
    "purchase_month:O",
    title=None,
    sort=chart_months,
    axis=alt.Axis(labelAngle=0),
)
trend_bars = alt.Chart(trend_parts).mark_bar(size=48).encode(
    x=month_axis,
    y=alt.Y(
        "rate_pct:Q",
        stack="zero",
        title="Share of due orders (%)",
        scale=alt.Scale(domain=[0, float(trend["miss_rate_pct"].max()) * 1.2]),
    ),
    color=alt.Color(
        "outcome:N",
        scale=alt.Scale(
            domain=["Delivered late", "No delivery record"],
            range=["#E9A24B", "#8292A4"],
        ),
        legend=alt.Legend(title=None, orient="top"),
    ),
    opacity=alt.condition(
        alt.datum.purchase_month == selected_month,
        alt.value(1),
        alt.value(0.72),
    ),
    tooltip=[
        alt.Tooltip("purchase_month:O", title="Purchase month"),
        alt.Tooltip("outcome:N", title="Outcome"),
        alt.Tooltip("rate_pct:Q", title="Share (%)", format=".1f"),
    ],
)
trend_labels = alt.Chart(trend).mark_text(
    dy=-8, color="#243447", fontSize=12, fontWeight="bold"
).encode(
    x=month_axis,
    y=alt.Y("miss_rate_pct:Q"),
    text=alt.Text("miss_rate_pct:Q", format=".1f"),
)
trend_chart = (trend_bars + trend_labels).properties(height=290).configure_axis(
    gridColor="#E8EDF3", labelColor="#516071", titleColor="#516071"
).configure_view(stroke=None)

st.subheader("What drives missed promises?")
st.altair_chart(trend_chart, width="stretch")

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
        "handoff_days": "Pre-handoff",
        "transit_days": "Transit",
    },
)

stage_plot = stage_medians.reset_index(names="Outcome").melt(
    id_vars="Outcome", var_name="Stage", value_name="Median days"
)
stage_plot = stage_plot.dropna(subset=["Median days"])
stage_order = ["Pre-handoff", "Transit"]
outcome_order = ["On time", "Late"]
stage_axis = alt.Y("Stage:N", sort=stage_order, title=None)
stage_offset = alt.YOffset("Outcome:N", sort=outcome_order)
stage_color = alt.Color(
    "Outcome:N",
    scale=alt.Scale(domain=outcome_order, range=["#316DA8", "#E9A24B"]),
    legend=alt.Legend(title=None, orient="top"),
)
stage_bars = alt.Chart(stage_plot).mark_bar(size=24).encode(
    y=stage_axis,
    yOffset=stage_offset,
    x=alt.X(
        "Median days:Q",
        title="Median days",
        scale=alt.Scale(domain=[0, float(stage_plot["Median days"].max()) * 1.25]),
        axis=alt.Axis(tickCount=8, format=".0f"),
    ),
    color=stage_color,
    tooltip=[
        alt.Tooltip("Stage:N"),
        alt.Tooltip("Outcome:N"),
        alt.Tooltip("Median days:Q", format=".1f"),
    ],
)
stage_labels = alt.Chart(stage_plot).mark_text(
    align="left", dx=5, color="#243447", fontSize=12
).encode(
    y=stage_axis,
    yOffset=stage_offset,
    x=alt.X("Median days:Q"),
    text=alt.Text("Median days:Q", format=".1f"),
)
stage_chart = (stage_bars + stage_labels).properties(height=230).configure_axis(
    gridColor="#E8EDF3", labelColor="#516071", titleColor="#516071"
).configure_view(stroke=None)

st.subheader("Where does delivery time accumulate?")
st.altair_chart(stage_chart, width="stretch")

# Keep the record-level evidence available after the summary charts. This is
# the selected historical purchase cohort, not a live fulfillment queue.
order_details = selected_orders[selected_orders["promise_missed"]].copy()
order_details["Outcome"] = order_details["no_delivery_record"].map(
    {True: "No delivery recorded", False: "Delivered late"}
)
order_details["Days late"] = (
    order_details["order_delivered_customer_date"].dt.normalize()
    - order_details["order_estimated_delivery_date"].dt.normalize()
).dt.days.astype("Int64")
order_details = order_details.sort_values(
    ["no_delivery_record", "Days late"], ascending=[False, False]
)
order_details = order_details[
    [
        "order_id",
        "Outcome",
        "order_status",
        "order_purchase_timestamp",
        "order_estimated_delivery_date",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "Days late",
    ]
].rename(
    columns={
        "order_id": "Order ID",
        "order_status": "Status",
        "order_purchase_timestamp": "Purchased",
        "order_estimated_delivery_date": "Promised",
        "order_delivered_carrier_date": "Carrier handoff",
        "order_delivered_customer_date": "Delivered",
    }
)

st.subheader(f"Order details · {len(order_details):,} missed promises")
st.dataframe(order_details, hide_index=True, width="stretch", height=360)

st.caption(
    f"Data: purchases {purchase_start:%Y-%m-%d} to {purchase_end:%Y-%m-%d} "
    "(Kaggle snapshot). Production plan: refresh weekly; review monthly."
)
