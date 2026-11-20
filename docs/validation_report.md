# Validation report

**Project:** [Manufacturing Readiness & Shortage Intelligence](../README.md)

The published planning snapshot passed three checks: the manufacturing records satisfy the database integrity rules, every reporting export matches its DuckDB view, and the headline results can be reconstructed from the detailed orders and shortages.

## Manufacturing data integrity

The validation ran against the existing database in read-only mode. It found all 11 expected core tables and passed all 23 integrity checks. Eleven checks cover primary keys, one for each table. The others examine family and supplier references, component revisions and assembly hierarchy, order dates, inventory quantities, reservation references and overallocations, purchase orders, engineering changes, alternate sources, and disruption targets. [Validation code](../scripts/validate_database.py)

## Agreement between DuckDB and the published files

Each of the ten reporting CSVs was read using the column types of its corresponding reporting view. Rows were compared in both directions, including duplicate counts. All ten matched. The comparison covers the actual field values as well as the number of rows. The [data dictionary](data_dictionary.md) lists the row count and meaning of each export.

## Independent checks on the headline results

| Check | Calculation from the detailed exports | Result |
| --- | --- | --- |
| Readiness | Count orders by status | 10 material ready + 8 at risk + 12 blocked = 30 orders |
| Shortage coverage | Count order-component exceptions, then count distinct component and revision pairs | 424 lines across 109 distinct pairs |
| Missing material | Sum shortage units and standard-cost exposure over the 424 detail lines | 9,659 units valued at $1,473,979.95 |
| Schedule impact | Sum standard and targeted delay days over the 30 order records | 93 days under standard purchasing and 8 under targeted expediting |
| Purchasing premium | Sum expedited lines and additional spending across individual orders | 101 expedited lines and $154,010.01 above standard |

The [order readiness](../data/reporting/readiness_orders.csv), [shortage detail](../data/reporting/shortage_detail.csv), and [order recovery](../data/reporting/production_recovery.csv) exports provide the rows behind these calculations. The [executive KPI export](../data/reporting/executive_kpis.csv) contains the corresponding headline values.

## What the checks establish

These checks establish internal consistency for the saved synthetic snapshot. They do not test whether suppliers can achieve the quoted delivery dates or the factory has capacity for the recovered starts. Those conditions require operational evidence. If the underlying data changes, rerun the integrity checks and compare the new detail and summary exports before using these figures. [Planning assumptions](assumptions.md)
