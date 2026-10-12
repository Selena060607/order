from datetime import timedelta
from pathlib import Path

import pandas as pd
import streamlit as st


TEAM_NAME = "Team 10" 
DATA_FILE = "olist_orders_dataset.csv"

DATE_COLUMNS = [
    "order_purchase_timestamp",
    "order_delivered_carrier_date",
    "order_delivered_customer_date",
    "order_estimated_delivery_date",
]


@st.cache_data
def load_orders():
    data = pd.read_csv(DATA_FILE)

    for column in DATE_COLUMNS:
        data[column] = pd.to_datetime(data[column], errors="coerce")

    return data


def open_orders_on(data, day):
    """Orders purchased by day and not yet recorded as delivered by day."""
    cutoff = pd.Timestamp(day)

    purchased = data["purchase_day"] <= cutoff
    not_delivered = (
        data["delivery_day"].isna()
        | (data["delivery_day"] > cutoff)
    )

    return data.loc[purchased & not_delivered].copy()


st.set_page_config(page_title="Order Fulfillment", layout="wide")
st.title(f"{TEAM_NAME} | Order Fulfillment")
st.caption(
    "For the fulfillment manager: review overdue orders each morning "
    "and decide which orders or fulfillment stage to escalate."
)

if not DATA_FILE.exists():
    st.error("Place olist_orders_dataset.csv in the same folder as app.py.")
    st.stop()

orders = load_orders()

# Cancellation dates are unavailable. Also exclude records whose essential
# dates do not allow their historical delivery state to be reconstructed.
excluded = (
    orders["order_status"].isin(["canceled", "unavailable"])
    | orders["order_purchase_timestamp"].isna()
    | orders["order_estimated_delivery_date"].isna()
    | (
        orders["order_status"].eq("delivered")
        & orders["order_delivered_customer_date"].isna()
    )
)

usable = orders.loc[~excluded].copy()

if usable.empty:
    st.error("No orders with usable dates were found.")
    st.stop()

usable["purchase_day"] = (
    usable["order_purchase_timestamp"].dt.normalize()
)
usable["carrier_day"] = (
    usable["order_delivered_carrier_date"].dt.normalize()
)
usable["delivery_day"] = (
    usable["order_delivered_customer_date"].dt.normalize()
)
usable["promised_day"] = (
    usable["order_estimated_delivery_date"].dt.normalize()
)

first_day = usable["purchase_day"].min().date()
last_day = usable["purchase_day"].max().date()

# Default to the latest purchase day with meaningful order volume.
daily_counts = usable["purchase_day"].value_counts()
active_days = daily_counts[daily_counts >= 20]
default_day = (
    active_days.index.max().date()
    if not active_days.empty
    else last_day
)

review_day = st.date_input(
    "Historical review date",
    value=default_day,
    min_value=first_day,
    max_value=last_day,
)

cutoff = pd.Timestamp(review_day)
open_orders = open_orders_on(usable, review_day)

overdue = open_orders.loc[
    open_orders["promised_day"] < cutoff
].copy()

no_handoff = open_orders.loc[
    open_orders["carrier_day"].isna()
    | (open_orders["carrier_day"] > cutoff)
]

previous_day = review_day - timedelta(days=1)
previous_open = open_orders_on(usable, previous_day)
previous_overdue_count = (
    previous_open["promised_day"] < pd.Timestamp(previous_day)
).sum()

# Top: the three numbers needed for the morning decision.
col1, col2, col3 = st.columns(3)

col1.metric("Orders not yet delivered", f"{len(open_orders):,}")
col2.metric(
    "Past promised delivery date",
    f"{len(overdue):,}",
    delta=f"{len(overdue) - previous_overdue_count:+,} vs prior day",
    delta_color="inverse",
)
col3.metric("No carrier handoff recorded", f"{len(no_handoff):,}")

# Middle: whether the issue is growing.
trend_days = pd.date_range(
    end=cutoff,
    periods=14,
    freq="D",
)

overdue_trend = pd.Series(
    {
        day: (
            open_orders_on(usable, day)["promised_day"] < day
        ).sum()
        for day in trend_days
    },
    name="Overdue orders",
)

st.subheader("Overdue orders over the past 14 days")
st.line_chart(overdue_trend)

# Middle: where today's overdue orders are in the process.
if not overdue.empty:
    overdue["stage"] = "No carrier handoff recorded"
    with_carrier = (
        overdue["carrier_day"].notna()
        & (overdue["carrier_day"] <= cutoff)
    )
    overdue.loc[with_carrier, "stage"] = "Handed to carrier"

    stage_counts = overdue["stage"].value_counts()

    st.subheader("Where overdue orders stand")
    st.bar_chart(stage_counts)

    # Bottom: specific orders the manager can look up and escalate.
    overdue["days_past_promise"] = (
        cutoff - overdue["promised_day"]
    ).dt.days

    details = overdue[
        [
            "order_id",
            "stage",
            "order_purchase_timestamp",
            "order_estimated_delivery_date",
            "order_delivered_carrier_date",
            "days_past_promise",
        ]
    ].sort_values("days_past_promise", ascending=False)

    st.subheader("Orders to review first")
    st.dataframe(
        details.head(30),
        hide_index=True,
        use_container_width=True,
    )
else:
    st.info("No overdue orders on the selected review date.")

data_start = orders["order_purchase_timestamp"].min().date()
data_end = orders["order_purchase_timestamp"].max().date()

st.caption(
    f"Data: orders purchased {data_start} to {data_end}; "
    "Kaggle historical snapshot. In production: refresh nightly "
    "and review each morning."
)
st.caption(
    "Historical reconstruction excludes canceled and unavailable orders "
    "because their cancellation dates are not provided. A missing carrier "
    "handoff date may also reflect missing data. These counts are therefore "
    "a demonstration of the workflow, not a complete live order backlog."
)