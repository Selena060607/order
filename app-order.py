import pandas as pd
import streamlit as st

st.set_page_config(page_title="Order Fulfillment Watch", layout="wide")

# 直接读取 CSV
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
last_delivery = df["order_delivered_customer_date"].max()

# 无法确定取消或缺货发生的日期，因此不把这些订单放入历史积压量。
# 标记为 delivered 却缺少实际送达日期的订单也无法还原其历史状态。
orders = df.dropna(
    subset=["order_purchase_timestamp", "order_estimated_delivery_date"]
).copy()

orders = orders[
    ~orders["order_status"].isin(["canceled", "unavailable"])
].copy()

orders = orders[
    ~(
        (orders["order_status"] == "delivered")
        & orders["order_delivered_customer_date"].isna()
    )
].copy()


def open_orders_on(day):
    """返回截至指定日期早晨，已购买但尚未记录送达的订单。"""
    purchased = orders[orders["order_purchase_timestamp"] < day]

    return purchased[
        purchased["order_delivered_customer_date"].isna()
        | (purchased["order_delivered_customer_date"] >= day)
    ].copy()


def overdue_orders_on(day):
    """返回截至指定日期早晨，已超过预计送达日的未送达订单。"""
    open_orders = open_orders_on(day)

    return open_orders[
        open_orders["order_estimated_delivery_date"] < day
    ].copy()


st.title("Order Fulfillment Watch")
st.caption(
    "For a fulfillment manager: review overdue orders each morning "
    "and decide which orders need follow-up."
)

min_date = (purchase_start.normalize() + pd.Timedelta(days=1)).date()
max_event = max(purchase_end, last_delivery)
max_date = (max_event.normalize() + pd.Timedelta(days=1)).date()

# 2018 年 9—10 月的新订单记录很少，默认展示较完整的 8 月之后的状态。
default_date = pd.Timestamp("2018-09-01").date()
default_date = min(max(default_date, min_date), max_date)

selected_date = st.date_input(
    "Review date (start of day)",
    value=default_date,
    min_value=min_date,
    max_value=max_date,
)

day = pd.Timestamp(selected_date)
open_orders = open_orders_on(day)
overdue_orders = overdue_orders_on(day)

# 在所选日期之前有承运商交接记录的逾期订单
handoff_recorded = (
    overdue_orders["order_delivered_carrier_date"].notna()
    & (overdue_orders["order_delivered_carrier_date"] < day)
)
no_handoff_count = int((~handoff_recorded).sum())

col1, col2, col3 = st.columns(3)

with col1:
    st.metric("Inferred open orders", f"{len(open_orders):,}")

with col2:
    st.metric("Overdue orders", f"{len(overdue_orders):,}")

with col3:
    st.metric("Overdue: no handoff recorded", f"{no_handoff_count:,}")

st.caption(
    "Counts are reconstructed from historical timestamps as of the "
    "start of the selected date."
)

# 图 1：最近 14 天逾期订单数量
trend_rows = []

for trend_day in pd.date_range(end=day, periods=14, freq="D"):
    if trend_day < pd.Timestamp(min_date):
        continue

    trend_rows.append(
        {
            "Date": trend_day,
            "Overdue orders": len(overdue_orders_on(trend_day)),
        }
    )

trend = pd.DataFrame(trend_rows)

st.subheader("Overdue orders over the past 14 days")
st.line_chart(trend.set_index("Date"))

# 如果逾期订单连续两天增加，给出明确的处理提示
if len(trend) >= 3:
    recent = trend["Overdue orders"].iloc[-3:]

    if recent.iloc[0] < recent.iloc[1] < recent.iloc[2]:
        st.warning(
            "Overdue orders increased for two consecutive days. "
            "Review the order list below and prioritize follow-up."
        )

# 图 2：逾期订单是否有承运商交接记录
stage_counts = pd.DataFrame(
    {
        "Orders": [
            no_handoff_count,
            int(handoff_recorded.sum()),
        ]
    },
    index=[
        "No handoff recorded",
        "Handoff recorded",
    ],
)

st.subheader("Where are the overdue orders?")
st.bar_chart(stage_counts)

# 可供经理查看的具体订单
st.subheader("Orders to review")

if overdue_orders.empty:
    st.info("No overdue orders for the selected date.")
else:
    details = overdue_orders.copy()

    details["days_overdue"] = (
        day - details["order_estimated_delivery_date"].dt.normalize()
    ).dt.days

    details["carrier_handoff"] = "No record"
    details.loc[handoff_recorded, "carrier_handoff"] = "Recorded"

    details = details.sort_values(
        ["days_overdue", "order_estimated_delivery_date"],
        ascending=[False, True],
    )

    st.dataframe(
        details[
            [
                "order_id",
                "order_purchase_timestamp",
                "order_estimated_delivery_date",
                "order_delivered_carrier_date",
                "days_overdue",
                "carrier_handoff",
            ]
        ]
        .head(30)
        .rename(
            columns={
                "order_id": "Order ID",
                "order_purchase_timestamp": "Purchased",
                "order_estimated_delivery_date": "Estimated delivery",
                "order_delivered_carrier_date": "Carrier handoff date",
                "days_overdue": "Days overdue",
                "carrier_handoff": "Handoff record",
            }
        )
    )

st.caption(
    f"Historical purchase period: {purchase_start:%Y-%m-%d} to "
    f"{purchase_end:%Y-%m-%d}. Proposed production refresh: nightly; "
    "manager review: each morning."
)

st.caption(
    "Data limitation: this is a historical demonstration, not a live "
    "order queue. Canceled and unavailable orders are excluded because "
    "their cancellation dates are absent. A missing carrier handoff "
    "date may also mean the record is incomplete."
)

if selected_date >= pd.Timestamp("2018-09-01").date():
    st.caption(
        "The dataset contains very few new purchases in September and "
        "October 2018, so interpret dates in this period cautiously."
    )
