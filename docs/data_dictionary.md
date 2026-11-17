# Data dictionary

Start with the reporting table that matches your question. For a late start, find the order in `production_recovery.csv`, then use its `production_order_id` to find missing components in `shortage_detail.csv`. To investigate one of those components across the schedule, use its part ID and revision in `shortage_priority.csv`.

## Measures and identifiers

| Field or term | Meaning |
| --- | --- |
| `production_order_id` | Identifier for one scheduled build, such as MO-0013. It links readiness, shortage detail, and recovery. |
| `component_part_id`, `component_revision` | The specific purchased item and engineering version required. Match both when joining component records. |
| `shortage_qty`, `total_shortage_units` | Uncovered physical units on one requirement or summed across requirements. One line may represent many units. |
| `shortage_exception_lines`, `unique_short_components` | Count of short order-component lines versus count of distinct short components. A component needed by four orders can create four exceptions. |
| `modeled_missing_material_value_usd` | Missing quantity multiplied by standard unit cost, summed at the table’s level of detail. |
| `readiness_rate_pct` | Material-ready orders divided by all orders in the selected group, multiplied by 100. Orders dependent on expected receipts are at risk. |
| `modeled_order_delay_days` | Sum of days each order starts past plan under a purchasing scenario. An on-time order contributes zero. |
| `additional_spend_vs_standard_usd` | Scenario procurement cost less standard procurement cost for the same shortage units. |
| `risk_score`, `shortage_severity` | Component-level prioritization measures. The score and severity on a detail line describe the component across its affected orders. |

## Reporting exports

| File | Rows | What one row represents |
| --- | ---: | --- |
| [executive_kpis.csv](../data/reporting/executive_kpis.csv) | 1 | One row for the whole schedule. Use it for headline counts, spending, and order-delay days. |
| [readiness_orders.csv](../data/reporting/readiness_orders.csv) | 30 | One scheduled production order. Use readiness_status to distinguish stock coverage, dependence on inbound supply, and shortages. |
| [weekly_readiness.csv](../data/reporting/weekly_readiness.csv) | 8 | One planned week. readiness_rate_pct uses all orders scheduled in that week as its denominator. |
| [family_summary.csv](../data/reporting/family_summary.csv) | 4 | One product family. blocked_order_pct is the share of that family’s orders classified as blocked. |
| [shortage_detail.csv](../data/reporting/shortage_detail.csv) | 424 | One short component revision on one order. Use this file to sum shortage_qty and missing-material value. |
| [shortage_priority.csv](../data/reporting/shortage_priority.csv) | 109 | One short component revision across orders. Rank 1 is the first component to investigate under the scoring rules. |
| [supplier_risk.csv](../data/reporting/supplier_risk.csv) | 8 | One primary supplier. affected_production_orders counts distinct orders within that supplier. An order can appear under several suppliers. |
| [production_recovery.csv](../data/reporting/production_recovery.csv) | 30 | One order with its baseline status and targeted purchasing result. Compare standard_delay_days with targeted_delay_days. |
| [recovery_comparison.csv](../data/reporting/recovery_comparison.csv) | 4 | One purchasing strategy applied to the entire schedule. Each row represents a separate outcome for the same orders. |
| [action_screening.csv](../data/reporting/action_screening.csv) | 2 | One type of internal recovery action. candidate_pairs counts eligible donor–recipient or schedule-swap pairs. |

## Manufacturing inputs

| File | Rows | What one row represents |
| --- | ---: | --- |
| [product_families.csv](../data/raw/product_families.csv) | 4 | One product family. Connect family_id to product_family_id on orders and parts. |
| [suppliers.csv](../data/raw/suppliers.csv) | 8 | One supplier. Join supplier_id to the primary or alternate supplier identifier to find a name and region. |
| [part_master.csv](../data/raw/part_master.csv) | 428 | One part record. Part type distinguishes purchased components, manufactured subassemblies, and finished products. Purchased components carry the standard price and lead time. |
| [bom_structure.csv](../data/raw/bom_structure.csv) | 496 | One parent-to-child bill of materials line. quantity_per_parent converts assembly demand into child demand. Effective dates determine when the relationship applies. |
| [production_orders.csv](../data/raw/production_orders.csv) | 30 | One scheduled build. order_quantity counts finished goods. material_required_date is the component need date, planned_start_date is the scheduled start, and planned_due_date is the completion target. |
| [inventory.csv](../data/raw/inventory.csv) | 800 | One stock observation by part, revision, location, and snapshot date. on_hand_qty includes the quantity on quality hold. |
| [inventory_allocations.csv](../data/raw/inventory_allocations.csv) | 1,000 | One reservation of a component for a production order at a location. allocated_qty is the portion earmarked for that order. |
| [purchase_orders.csv](../data/raw/purchase_orders.csv) | 300 | One purchase order for a component revision. expected_receipt_date determines when an open order enters available supply. |
| [engineering_changes.csv](../data/raw/engineering_changes.csv) | 12 | One proposed engineering change. The approval, revision, and cutover fields govern hypothetical adoption. |
| [approved_alternates.csv](../data/raw/approved_alternates.csv) | 40 | One alternate source for a part revision. Quoted cost, lead time, and maximum quantity constrain the alternate purchase. |
| [disruption_scenarios.csv](../data/raw/disruption_scenarios.csv) | 5 | One hypothetical event. The target identifies the affected entity and the parameter fields describe the change. |

The three JSON manifests in [the raw data folder](../data/raw/) record generation settings for the master data, supply baseline, and disruption inputs. The [reporting SQL](../sql/08_dashboard_reporting.sql) defines the views used to export the reporting CSVs.
