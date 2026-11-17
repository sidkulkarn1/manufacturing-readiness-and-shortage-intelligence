# Project scope

A production order tells a factory which finished product to build, how many units to make, and when work should start. For an aerospace electronics assembly, one missing component can hold up the entire order. This project asks whether a planner at a simulated manufacturer could identify those orders early enough to evaluate a purchasing response.

## The planning case

The schedule covers January 4 through February 28, 2027. It contains 30 orders across four product families: avionics control modules, power distribution assemblies, sensor and communication modules, and electromechanical assemblies. Their bills of materials describe how 400 purchased components and 24 subassemblies feed four finished products. Eight simulated suppliers provide the primary sources for purchased parts. [Product families](../data/raw/product_families.csv) · [Dataset manifest](../data/raw/dataset_manifest.json)

| Reader | Question | Where to look |
| --- | --- | --- |
| Production planner | Which orders have stock, depend on deliveries, or lack parts? | [Readiness by order](../data/reporting/readiness_orders.csv) |
| Buyer | Which shortages affect several orders, and which supplier owns each part? | [Ranked shortages](../data/reporting/shortage_priority.csv) and [supplier exposure](../data/reporting/supplier_risk.csv) |
| Operations lead | How much would faster purchasing cost, and which starts could it recover? | [Scenario comparison](../data/reporting/recovery_comparison.csv) and [individual orders](../data/reporting/production_recovery.csv) |

## Boundaries of the case

The baseline uses a single inventory snapshot, existing reservations, planned demand, and open purchase orders. Recovery scenarios change how missing material is purchased. A separate screen looks for eligible inventory transfers and schedule swaps. Engineering changes and disruption definitions are available as hypothetical inputs. The reported purchasing comparison uses the baseline shortages.

The analysis covers material availability and modeled start dates. A production release would also require labor, equipment, quality clearance, and confirmed supplier commitments. Financial measures cover the value and purchasing cost of missing units. The project has no customer revenue or margin model.

For a first read, start with the [executive summary](executive_summary.md). The [data dictionary](data_dictionary.md) explains how to follow an order or component across files.
