# Can the scheduled orders start with the material available?

On January 4, 2027, a simulated aerospace electronics manufacturer has 30 production orders on its eight-week schedule. Ten orders have all required components covered by stock. Eight depend on incoming deliveries arriving by the day the material is needed. The remaining 12 have shortages even after the model counts expected deliveries. The material readiness rate is **33.33%** (10 of 30).

## Where a planner would look first

Power Distribution Assemblies (FAM-02) account for **9,273 of the 9,659 missing units** across the schedule. Four of the family's eight orders are blocked. Start with those four orders to investigate the largest volume of missing material. For example, high-priority order `MO-0006` lacks 3,091 units across 100 components. In the model, buying all missing units at standard lead times moves its start 14 days past plan. Expediting 25 of its shortage lines restores its February 8 start. [Family totals](../data/reporting/family_summary.csv) · [Order-level recovery](../data/reporting/production_recovery.csv)

## What faster purchasing buys

Each row below starts with the same shortages. An order-delay day is one order starting one day after plan. Two orders each starting four days late contribute eight days to the total.

| Purchasing strategy | Orders starting on time | Total order-delay days | Extra spend above standard |
| --- | ---: | ---: | ---: |
| Standard replenishment | 24 of 30 | 93 | $0.00 |
| Qualified alternate where available | 24 of 30 | 93 | $31,403.70 |
| Expedite all shortage lines | 28 of 30 | 8 | $368,510.12 |
| Expedite selected shortage lines | 28 of 30 | 8 | $154,010.01 |

Targeted expediting is the purchasing option to investigate first. Paying the premium on **101 of 424 shortage lines** yields the same modeled start dates as expediting all 424, at **$214,500.11 less**. Two Avionics Control Module orders still start four days late each. Before committing spend, a buyer would need supplier confirmation of price, quantity, and arrival date. [Scenario comparison](../data/reporting/recovery_comparison.csv) · [Planning assumptions](assumptions.md)

## Reading the dashboards

1. Open [Manufacturing readiness](../dashboards/exports/01_manufacturing_readiness.png) for the order status overview.
2. Open [Component shortages and supplier risk](../dashboards/exports/02_component_shortages_supplier_risk.png) to investigate the parts and suppliers behind the blocked orders.
3. Open [Production impact and recovery](../dashboards/exports/03_production_impact_recovery.png) to compare the purchasing premium with the change in start dates.

The [project scope](project_scope.md) introduces the manufacturing setting. The [methodology](methodology.md) shows how a single order moves through the analysis.
