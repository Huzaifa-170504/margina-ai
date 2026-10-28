# Synthetic distributor dataset specification

Status: approved synthetic fixture policy, version 1.0.0. All people, customers, orders, and monetary values in these files are fictional.

## Business and metric decisions

| Decision | Approved rule |
| --- | --- |
| Tenant | One synthetic organization identified by `demo-distributor`. |
| Currency | PKR only. Currency conversion is outside this fixture and the MVP. |
| Reporting timezone | `Asia/Karachi`. All timestamps are stored as UTC ISO 8601 values ending in `Z`; `original_timezone` records the reporting/source timezone. |
| Sales basis | `unit_price` and `gross_sales` are before discounts and sales tax. `gross_sales = quantity × unit_price`. |
| Net revenue | Gross sales minus discounts and refunded revenue. Sales tax is collected separately and excluded. Discounts must not be subtracted a second time. |
| COGS | Only cost rows with category `cogs` are recognized as base COGS. |
| Variable fulfillment costs | `shipping`, `handling`, and `payment_fee`. These reduce contribution and are not included in COGS. |
| Returns | `refunded_revenue` reduces net revenue. `inventory_recovery_amount` reduces recognized COGS because the synthetic inventory is returned in saleable condition. Variable fulfillment costs are not reversed. |
| Contribution | Net revenue minus recognized COGS minus included variable fulfillment costs. |
| Process case | One `order_id` is one process case. Split deliveries are outside this fixture. |
| Workflow start | The first `Order received` event. |
| Workflow completion | The first subsequent `Dispatched` event. Unfinished cases would be reported separately. |
| Approval loop | An `Approval rejected` event followed later by another `Approval requested` event in the same order. |
| SLA breach | More than 48 elapsed clock hours from `Order received` to `Dispatched`. Exactly 48 hours is not a breach. Business calendars are not applied in policy v1.0.0. |
| Equal timestamps | Order by `occurred_at`, then `event_id`; flag the case if this tie-breaking affects a timing interpretation. |
| Discount alert | Demo cohort rule: discount divided by gross sales greater than 10%. This is an investigative threshold, not proof of improper discounting. |

## File contracts

All files are UTF-8 CSV with a header row, comma delimiter, a period decimal separator, and no thousands separators. Empty optional values are represented by an empty field.

### `orders.csv`

Expected rows: **12**. Unique business key: **`tenant_id + source_system + order_id`**.

| Column | Meaning |
| --- | --- |
| `tenant_id` | Organization scope. |
| `source_system` | Source-qualified namespace for identifiers. |
| `order_id` | Source order identifier. |
| `customer_id` | Synthetic customer identifier. |
| `branch_id` | Authorized/reporting branch. |
| `currency` | ISO currency code; always PKR here. |
| `occurred_at` | Order creation time in UTC. |
| `original_timezone` | Timezone associated with the source record. |
| `gross_sales` | Pre-discount, pre-tax sales control amount. |
| `discount` | Discount control amount. |
| `tax` | Collected sales tax, excluded from revenue. |
| `source_reference` | Synthetic provenance identifier. |

Example rows:

| `order_id` | `branch_id` | `gross_sales` | `discount` | `occurred_at` |
| --- | --- | ---: | ---: | --- |
| `ORD-1001` | `Branch A` | 150000.00 | 5000.00 | `2026-07-05T04:00:00Z` |
| `ORD-1011` | `Branch B` | 175000.00 | 25000.00 | `2026-09-17T04:00:00Z` |

### `order_lines.csv`

Expected rows: **12**. Unique business key: **`tenant_id + source_system + order_id + line_id`**.

| Column | Meaning |
| --- | --- |
| `tenant_id`, `source_system`, `order_id` | Scoped parent-order key. |
| `line_id` | Line identifier within an order. |
| `product_id` | Synthetic SKU identifier. |
| `quantity` | Non-negative decimal quantity. |
| `unit_price` | Pre-discount, pre-tax unit price. |
| `discount` | Line discount; sums to the order discount. |
| `tax` | Line sales tax; sums to the order tax. |
| `currency` | ISO currency code. |
| `occurred_at`, `original_timezone` | UTC business timestamp and source timezone. |
| `source_reference` | Synthetic row provenance. |

Example rows:

| `order_id` | `line_id` | `product_id` | `quantity` | `unit_price` | `discount` |
| --- | --- | --- | ---: | ---: | ---: |
| `ORD-1001` | `L1` | `SKU-ALPHA` | 10.000000 | 15000.0000 | 5000.0000 |
| `ORD-1006` | `L1` | `SKU-DELTA` | 10.000000 | 16000.0000 | 20000.0000 |

### `costs.csv`

Expected rows: **48**. Unique business key: **`tenant_id + source_system + cost_id`**.

| Column | Meaning |
| --- | --- |
| `tenant_id`, `source_system`, `cost_id` | Scoped cost key. |
| `order_id`, `line_id` | Parent order and optional parent line. |
| `category` | One of `cogs`, `shipping`, `handling`, or `payment_fee`. |
| `amount` | Decimal cost in PKR. |
| `currency` | ISO currency code. |
| `effective_at`, `original_timezone` | UTC effective time and source timezone. |
| `included_in_contribution` | Whether the cost is used by the approved contribution policy. |
| `source_reference` | Synthetic cost provenance. |

Example rows:

| `cost_id` | `order_id` | `line_id` | `category` | `amount` |
| --- | --- | --- | --- | ---: |
| `COGS-1001` | `ORD-1001` | `L1` | `cogs` | 95000.00 |
| `SHIP-1010` | `ORD-1010` |  | `shipping` | 22000.00 |

### `returns.csv`

Expected rows: **3**. Unique business key: **`tenant_id + source_system + return_id`**.

| Column | Meaning |
| --- | --- |
| `tenant_id`, `source_system`, `return_id` | Scoped return key. |
| `order_id`, `line_id` | Returned order and line. |
| `refunded_revenue` | Amount subtracted from net revenue, excluding tax. |
| `inventory_recovery_amount` | Amount subtracted from base COGS under the approved recovery policy. |
| `currency` | ISO currency code. |
| `effective_at`, `original_timezone` | UTC return time and source timezone. |
| `source_reference` | Synthetic return provenance. |

Example rows:

| `return_id` | `order_id` | `line_id` | `refunded_revenue` | `inventory_recovery_amount` |
| --- | --- | --- | ---: | ---: |
| `RET-1003-01` | `ORD-1003` | `L1` | 20000.00 | 12000.00 |
| `RET-1010-01` | `ORD-1010` | `L1` | 10000.00 | 6000.00 |

### `process_events.csv`

Expected rows: **56**. Unique business key: **`tenant_id + source_system + event_id`**.

| Column | Meaning |
| --- | --- |
| `tenant_id`, `source_system`, `event_id` | Scoped event key. |
| `order_id` | Order-level process case. |
| `activity` | Versioned workflow activity name. |
| `lifecycle_marker` | Lifecycle state; `complete` for this fixture. |
| `occurred_at` | Source event time in UTC. |
| `ingested_at` | Time received by MARGINA in UTC. |
| `original_timezone` | Source/reporting timezone. |
| `source_reference` | Synthetic event provenance. |

Example rows:

| `event_id` | `order_id` | `activity` | `occurred_at` | `ingested_at` |
| --- | --- | --- | --- | --- |
| `EV-1001-01` | `ORD-1001` | `Order received` | `2026-07-05T04:00:00Z` | `2026-07-05T04:05:00Z` |
| `EV-1010-04` | `ORD-1010` | `Approval requested` | `2026-09-10T06:00:00Z` | `2026-09-10T06:05:00Z` |

## Expected control totals

| Control | Expected value |
| --- | ---: |
| Orders | 12 |
| Order lines | 12 |
| Cost rows | 48 |
| Return rows | 3 |
| Process events | 56 |
| Gross sales | PKR 2,185,000.00 |
| Discounts | PKR 122,000.00 |
| Sales tax excluded from revenue | PKR 330,080.00 |
| Refunded revenue | PKR 45,000.00 |
| Net revenue | PKR 2,018,000.00 |
| Base COGS | PKR 1,395,000.00 |
| Inventory recovery | PKR 27,000.00 |
| Recognized COGS | PKR 1,368,000.00 |
| Shipping | PKR 149,000.00 |
| Handling | PKR 24,000.00 |
| Payment fees | PKR 18,000.00 |
| Variable fulfillment costs | PKR 191,000.00 |
| Gross profit | PKR 650,000.00 |
| Contribution | PKR 459,000.00 |
| Contribution margin | 22.7453% |

## Seeded investigative signals

- Rising delivery cost: shipping totals are PKR 34,000 in July, PKR 37,000 in August, and PKR 78,000 in September.
- Excessive discounting: `ORD-1006`, `ORD-1008`, and `ORD-1011` exceed the 10% demo threshold.
- Approval loops: `ORD-1002`, `ORD-1006`, `ORD-1010`, and `ORD-1011` contain a rejection followed by a repeated request.
- SLA breaches: `ORD-1002`, `ORD-1006`, `ORD-1009`, `ORD-1010`, `ORD-1011`, and `ORD-1012` exceed 48 elapsed hours.

These are synthetic associations for testing and demonstration. They are not causal findings or verified customer savings.
