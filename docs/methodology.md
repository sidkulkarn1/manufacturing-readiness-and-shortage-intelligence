# From a production order to a recovery decision

**Project:** [Manufacturing Readiness & Shortage Intelligence](../README.md)

The analysis follows one question through the data: can every component reach a production order in time for its planned start? The first calculation measures coverage from existing supply. The second estimates what would happen if a buyer ordered the missing units.

1. **Load the planning snapshot.** Python generates synthetic CSV records. DuckDB loads them and creates typed manufacturing tables for products, parts, scheduled orders, stock, and receipts. Integrity checks verify identifiers, references, revisions, dates, and allocations. [Schema](../sql/01_create_schema.sql) · [Validation report](validation_report.md)
2. **Translate products into component demand.** A bill of materials (BOM) lists the parts needed to make one parent assembly. For an order of ten assemblies requiring three units of a part each, gross demand is 30 units. The query follows each level of the BOM, checks revision and effective dates against the material requirement date, and adds demand when the same part appears along multiple paths. [Material requirements](../sql/03_material_requirements.sql)
3. **Allocate supply in date order.** Credit an order's reservations first. Allocate free stock and eligible receipts to remaining requirements by material need date, then by priority, then by order ID. Track quantities actually consumed so a previously unmet requirement cannot use a later order's supply. An order is blocked if any component is short or the model finds no component requirements. Otherwise, dependence on an incoming receipt makes it at risk. Coverage entirely from stock makes it material ready. [Allocation and status rules](../sql/04_material_readiness.sql)
4. **Prioritize missing material.** Record one exception per short order, component, and revision. Multiply missing units by standard unit cost to measure exposure. Group exceptions by component to rank them. The score gives up to 30 points for affected orders, 20 for high-priority exposure, 25 for urgency, 15 for lead time, and 10 for shortage size. Scores of 70 or more are critical, 40–69 high, and below 40 moderate. [Shortage scoring](../sql/05_shortage_analysis.sql)
5. **Estimate a new start date.** For each purchasing strategy, calculate when the missing components could arrive. The latest required arrival sets the earliest feasible material-based start, bounded below by the planned start. Sum each order's days past plan to compare scenarios. For targeted expediting, first calculate the start achievable by expediting everything. Pay the premium only for lines whose standard arrival would miss that order-specific date. [Standard and alternate procurement](../sql/07_recovery_analysis.sql) · [Targeted selection](../sql/07b_targeted_expediting.sql)
6. **Screen internal alternatives.** A transfer needs matching part, revision, and site plus a later, lower-priority donor with reserved stock. A slot swap needs a later ready order at the same site and a slot the blocked order can use before its due date. Neither screen found a qualifying pair in this case. [Screening rules](../sql/07c_reallocation_resequencing.sql)

## Follow one order

Filter the [order recovery table](../data/reporting/production_recovery.csv) to `MO-0013`. Its planned start is February 1. Three component shortages leave 42 units uncovered. Standard replenishment implies a 20-day start delay. Expediting two lines costs an additional $1,583.12 and brings the modeled start forward to February 5, leaving four days of delay. Filter the [shortage detail](../data/reporting/shortage_detail.csv) by the same order ID to inspect the three component lines. The order keeps its baseline blocked status alongside the modeled recovery date because those fields answer different planning questions.

## Rebuild from the project root

The documented development environment is Python 3.14.10 and DuckDB 2.0.0. Install the recorded dependency in a local environment:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Generation and export scripts write to fixed project paths. Preserve any manually edited synthetic inputs or outputs before regeneration. Execute the stages sequentially from the repository root:

```sh
set -e
for stage in data_generator generate_bom generate_production_orders \
             generate_supply_data generate_disruptions build_database \
             validate_database run_sql03 run_sql04 run_sql05 run_sql06 \
             run_sql07 run_sql07b run_sql07c run_sql08
do
    python "scripts/${stage}.py"
done
```

The generated database is `data/processed/manufacturing_readiness.duckdb`; the ten dashboard datasets are written to `data/reporting/`. The reporting runner checks its exports. Open the Tableau workbook separately and relink CSV connections if the local folder has changed. Screenshots are static exports and must be refreshed separately after analytical changes.

The archived stress baseline is retained for provenance; it is not the current planning snapshot. Its directory name is a functional historical identifier.
