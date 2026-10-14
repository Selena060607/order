# Delivery Promise Review

## Step 1 — Dataset and decision-maker

I use Olist's [Brazilian E-Commerce Public Dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce), specifically olist_orders_dataset.csv. It contains 99,441 anonymized real orders in one 17.7 MB CSV; each row is one order. Purchases run from September 4, 2016, to October 17, 2018. The dashboard is for a fulfillment manager responsible for delivery-promise performance.

## Step 2 — Why a dashboard?

In a production setting, the fulfillment manager checks the dashboard each morning after the order events refresh. If the missed-promise rate for orders due in the latest seven calendar days is at least 2 percentage points above the preceding seven days, the manager inspects the affected orders, compares handoff and transit times, and asks the relevant team to investigate. The 2-point trigger is a proposed decision rule, not a threshold estimated from Olist's data.

Without this view, the manager would have to compare purchase, promise, carrier-handoff, and delivery dates in a spreadsheet each day. That costs analysis time and increases the chance of noticing a worsening pattern late; the dataset cannot put a dollar value on either cost. A dashboard lets the manager select a promised delivery date, see the daily pattern, inspect the stages, and check individual records in one place. A weekly email would arrive too late for a daily review; an alert would suit an urgent individual order, which this historical snapshot cannot monitor.

## Step 3 — Decide what matters

Quick EDA shows 99,441 rows, 8 columns, and one unique order_id per row. Date fields require parsing from text. Most orders have final status delivered (96,478), but 2,965 customer-delivery dates are missing. Among delivered orders with a recorded delivery date, 6,534 arrived after the promised calendar date. The final promised-date months have far fewer orders, so the last dates should not define the default view.

The page starts with the **missed-promise rate** and counts of **delivered-late** and **no-delivery-record** orders for the seven calendar days ending on the selected **promised delivery date**. The rate uses all eligible due orders as its denominator, while the counts show how many records warrant investigation. Daily stacked bars show which dates and outcomes drove misses over the past 21 days; a line shows the smoother seven-day rate. A second chart compares median time before carrier handoff and in transit for on-time versus late deliveries in the selected seven-day window. The promised delivery date is the only filter. At the bottom, an order-detail table lets the manager inspect the missed-promise records from that same window.

I left out a pie chart of final order statuses because status alone does not show whether a delivery promise was met. I also left out a single average delivery-time KPI because it hides the distinction between handoff and transit time.

The CSV has no extraction timestamp, so the last observed event is only a proxy for the observation cutoff. The dashboard includes promises due by that cutoff and excludes canceled and unavailable orders and delivered rows without a delivery date. Dates with fewer than 50 due orders or fewer than 500 orders in the seven-day window are omitted from the selector; the default comes from the last substantial historical month because the snapshot's final dates are sparse. “No delivery recorded” means exactly that in this snapshot; it does not establish that an order remained open. Stage comparisons describe where time accumulated, not why a delay occurred.

## Step 4 — Decide the refresh frequency

For a production version, I would refresh order events **daily before the manager's morning review**. The manager checks the seven-day missed-promise rate and its order details every day. A rise of at least **2 percentage points** against the preceding seven days, when both windows contain at least 500 due orders, triggers a review of handoff and transit time. If the data were a day old, recently delivered orders might still appear to have no delivery record, distorting the component rates and delaying the response. The Kaggle CSV is a frozen snapshot; it does not itself refresh.
