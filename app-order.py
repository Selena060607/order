import altair as alt
import pandas as pd
import streamlit as st


TEAM_NAME = "Team 10"  # Replace with your team name.

st.set_page_config(page_title="Delivery Promise Review", layout="wide")

df = pd.read_csv("olist_orders_dataset.csv")
for column in [
    "order_purchase_timestamp",
    "order_delivered_carrier_date",
    "order_delivered_customer_date",
    "order_estimated_delivery_date",
]:
    df[column] = pd.to_datetime(df[column], errors="coerce")

purchase_start = df["order_purchase_timestamp"].min()
purchase_end = df["order_purchase_timestamp"].max()

# The historical CSV has no extraction timestamp. The latest event provides
# a proxy cutoff for which promised dates could have been observed.
last_observed_event = max(
    df["order_purchase_timestamp"].max(),
    df["order_delivered_carrier_date"].max(),
    df["order_delivered_customer_date"].max(),
)
observation_cutoff = last_observed_event.normalize() + pd.Timedelta(days=1)

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

# The promise is a calendar date, so delivery later that same day is on time.
orders["due_date"] = orders["order_estimated_delivery_date"].dt.normalize()
orders["delivered_late"] = (
    orders["order_delivered_customer_date"].notna()
    & (
        orders["order_delivered_customer_date"].dt.normalize()
        > orders["due_date"]
    )
)
orders["no_delivery_record"] = orders["order_delivered_customer_date"].isna()
orders["promise_missed"] = (
    orders["delivered_late"] | orders["no_delivery_record"]
)

# Daily due-date cohorts support a daily review. Include days without orders
# when computing calendar-day rolling windows.
daily = orders.groupby("due_date", sort=True).agg(
    order_count=("order_id", "size"),
    missed=("promise_missed", "sum"),
    delivered_late=("delivered_late", "sum"),
    no_delivery_record=("no_delivery_record", "sum"),
)
daily = daily.reindex(
    pd.date_range(daily.index.min(), daily.index.max(), freq="D"),
    fill_value=0,
)
daily.index.name = "due_date"
daily["orders_7d"] = daily["order_count"].rolling(7, min_periods=1).sum()
for name in ["missed", "delivered_late", "no_delivery_record"]:
    daily[f"{name}_7d"] = daily[name].rolling(7, min_periods=1).sum()
    daily[f"{name}_rate_pct"] = (
        100 * daily[name] / daily["order_count"].where(daily["order_count"] > 0)
    )
    daily[f"{name}_7d_pct"] = (
        100 * daily[f"{name}_7d"] / daily["orders_7d"].where(daily["orders_7d"] > 0)
    )

# Omit single-order days from the selector. Open on the last substantial
# historical month so the sparse tail of the snapshot is not the first view.
date_options = daily.index[
    (daily["order_count"] >= 50) & (daily["orders_7d"] >= 500)
].tolist()
if not date_options:
    st.error("No date has enough due orders for this review.")
    st.stop()

month_counts = orders.groupby(orders["due_date"].dt.to_period("M")).size()
substantial_months = month_counts[month_counts >= 5000]
default_month = (
    substantial_months.index[-1]
    if not substantial_months.empty
    else date_options[-1].to_period("M")
)
default_dates = [day for day in date_options if day.to_period("M") == default_month]
default_date = default_dates[-1] if default_dates else date_options[-1]

st.title(f"{TEAM_NAME} | Delivery Promise Review")
st.caption(
    "For the fulfillment manager: check delivery promises due recently "
    "and decide whether to investigate handoff or transit time."
)

selected_date = st.selectbox(
    "Promised delivery date",
    date_options,
    index=date_options.index(default_date),
    format_func=lambda day: day.strftime("%Y-%m-%d"),
)
window_start = selected_date - pd.Timedelta(days=6)
previous_start = selected_date - pd.Timedelta(days=13)
previous_end = selected_date - pd.Timedelta(days=7)
selected_window = orders[orders["due_date"].between(window_start, selected_date)]
previous_window = orders[orders["due_date"].between(previous_start, previous_end)]

current = daily.loc[selected_date]
current_rate = float(current["missed_7d_pct"])
previous_rate = (
    100 * previous_window["promise_missed"].mean()
    if len(previous_window) >= 500
    else None
)
delta = (
    f"{current_rate - previous_rate:+.1f} pp vs prior 7 days"
    if previous_rate is not None
    else None
)
mini_history = daily.loc[window_start:selected_date]


def mini_trend(column):
    return mini_history[column].tolist()


col1, col2, col3 = st.columns(3)
with col1:
    st.metric(
        "Missed promises · 7 days",
        f"{current_rate:.1f}%",
        delta=delta,
        delta_color="inverse",
        chart_data=mini_trend("missed_7d_pct"),
        chart_type="line",
        border=True,
        height=220,
    )
with col2:
    st.metric(
        "Delivered late · 7 days",
        f"{int(current['delivered_late_7d']):,}",
        chart_data=mini_trend("delivered_late_7d"),
        chart_type="line",
        border=True,
        height=220,
    )
with col3:
    st.metric(
        "No delivery recorded · 7 days",
        f"{int(current['no_delivery_record_7d']):,}",
        chart_data=mini_trend("no_delivery_record_7d"),
        chart_type="line",
        border=True,
        height=220,
    )

st.caption(
    f"{int(current['orders_7d']):,} orders promised {window_start:%b %d}–"
    f"{selected_date:%b %d, %Y}."
)

if previous_rate is not None and current_rate - previous_rate >= 2:
    st.warning(
        f"The 7-day missed-promise rate rose "
        f"{current_rate - previous_rate:.1f} percentage points. "
        "Review the delivery stages below."
    )

# Daily bars show which outcome drives misses; the line separates a sustained
# 7-day change from one noisy due date.
chart_start = selected_date - pd.Timedelta(days=20)
chart_days = daily.loc[chart_start:selected_date].reset_index()
chart_days = chart_days[chart_days["order_count"] > 0]
chart_days["series"] = "7-day miss rate"
trend_parts = chart_days.melt(
    id_vars=["due_date", "order_count"],
    value_vars=["delivered_late_rate_pct", "no_delivery_record_rate_pct"],
    var_name="outcome",
    value_name="rate_pct",
)
trend_parts["outcome"] = trend_parts["outcome"].map(
    {
        "delivered_late_rate_pct": "Delivered late",
        "no_delivery_record_rate_pct": "No delivery record",
    }
)
chart_max = max(
    float(chart_days["missed_rate_pct"].max()),
    float(chart_days["missed_7d_pct"].max()),
    1.0,
)
date_axis = alt.X(
    "due_date:T",
    title="Promised delivery date",
    axis=alt.Axis(format="%b %d", tickCount=7, labelAngle=0),
)
chart_color = alt.Scale(
    domain=["Delivered late", "No delivery record", "7-day miss rate"],
    range=["#E9A24B", "#8292A4", "#245C8E"],
)
rate_axis = alt.Y(
    "rate_pct:Q",
    title="Share of due orders (%)",
    scale=alt.Scale(domain=[0, chart_max * 1.15]),
)
bars = alt.Chart(trend_parts).mark_bar(size=17).encode(
    x=date_axis,
    y=rate_axis,
    color=alt.Color(
        "outcome:N",
        scale=chart_color,
        legend=alt.Legend(title=None, orient="top"),
    ),
    tooltip=[
        alt.Tooltip("due_date:T", title="Promised date", format="%Y-%m-%d"),
        alt.Tooltip("outcome:N", title="Outcome"),
        alt.Tooltip("rate_pct:Q", title="Daily share (%)", format=".1f"),
        alt.Tooltip("order_count:Q", title="Due orders", format=","),
    ],
)
rolling_line = alt.Chart(chart_days).mark_line(strokeWidth=3).encode(
    x=date_axis,
    y=alt.Y(
        "missed_7d_pct:Q",
        title="Share of due orders (%)",
        scale=alt.Scale(domain=[0, chart_max * 1.15]),
    ),
    color=alt.Color(
        "series:N",
        scale=chart_color,
        legend=alt.Legend(title=None, orient="top"),
    ),
    tooltip=[
        alt.Tooltip("due_date:T", title="Promised date", format="%Y-%m-%d"),
        alt.Tooltip("missed_7d_pct:Q", title="7-day miss rate (%)", format=".1f"),
    ],
)
daily_chart = (bars + rolling_line).properties(height=300).configure_axis(
    gridColor="#E8EDF3", labelColor="#516071", titleColor="#516071"
).configure_view(stroke=None)

st.subheader("Which due dates drove missed promises?")
st.altair_chart(daily_chart, width="stretch")

# Compare elapsed stages over the same seven-day cohort as the KPI cards.
completed = selected_window[
    selected_window["order_delivered_customer_date"].notna()
    & selected_window["order_delivered_carrier_date"].notna()
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
    columns={"handoff_days": "Pre-handoff", "transit_days": "Transit"},
)
stage_plot = stage_medians.reset_index(names="Outcome").melt(
    id_vars="Outcome", var_name="Stage", value_name="Median days"
).dropna(subset=["Median days"])

if not stage_plot.empty:
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

order_details = selected_window[selected_window["promise_missed"]].copy()
order_details["Outcome"] = order_details["no_delivery_record"].map(
    {True: "No delivery recorded", False: "Delivered late"}
)
order_details["Days late"] = (
    order_details["order_delivered_customer_date"].dt.normalize()
    - order_details["order_estimated_delivery_date"].dt.normalize()
).dt.days.astype("Int64")
order_details = order_details.sort_values(
    ["no_delivery_record", "due_date", "Days late"],
    ascending=[False, False, False],
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
    "(Kaggle snapshot). Production plan: refresh daily; review daily."
)
