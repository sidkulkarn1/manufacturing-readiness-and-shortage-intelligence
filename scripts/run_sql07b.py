
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parents[1]

DB_PATH = (
    ROOT / "data" / "processed"
    / "manufacturing_readiness.duckdb"
)

SQL_PATH = ROOT / "sql" / "07b_targeted_expediting.sql"


def check_zero(con, label, query):
    issues = con.execute(query).fetchone()[0]

    if issues != 0:
        raise AssertionError(
            f"{label}: {issues} issue(s)"
        )

    print(f"[PASS] {label}")


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError("DuckDB database missing.")

    sql = SQL_PATH.read_text(encoding="utf-8")

    if "targeted_expediting_decisions" not in sql:
        raise ValueError("SQL07B file is incomplete.")

    con = duckdb.connect(str(DB_PATH))

    try:
        print("Running SQL07B targeted expediting...")
        con.execute(sql)

        print("\nValidating recovery decisions:\n")

        check_zero(
            con,
            "All shortage lines evaluated",
            """
            SELECT ABS(
                (SELECT COUNT(*)
                 FROM planning.targeted_expediting_decisions)
                -
                (SELECT COUNT(*)
                 FROM planning.shortage_exceptions)
            )
            """
        )

        check_zero(
            con,
            "No duplicate procurement decisions",
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    production_order_id,
                    component_part_id,
                    component_revision,
                    COUNT(*) AS n
                FROM planning.targeted_expediting_decisions
                GROUP BY 1, 2, 3
                HAVING COUNT(*) > 1
            )
            """
        )

        check_zero(
            con,
            "Sourced quantities reconcile",
            """
            SELECT COUNT(*)
            FROM planning.targeted_expediting_decisions d
            LEFT JOIN planning.shortage_exceptions e
                ON d.production_order_id =
                   e.production_order_id
               AND d.component_part_id =
                   e.component_part_id
               AND d.component_revision =
                   e.component_revision
            WHERE e.production_order_id IS NULL
               OR d.sourced_qty <> e.shortage_qty
            """
        )

        check_zero(
            con,
            "Expediting decisions follow target dates",
            """
            SELECT COUNT(*)
            FROM planning.targeted_expediting_decisions
            WHERE
                (selected_action = 'EXPEDITE'
                 AND standard_arrival_date
                     <= full_expediting_start_date)
                OR
                (selected_action = 'STANDARD'
                 AND standard_arrival_date
                     > full_expediting_start_date)
            """
        )

        check_zero(
            con,
            "Selected materials arrive by target",
            """
            SELECT COUNT(*)
            FROM planning.targeted_expediting_decisions
            WHERE selected_arrival_date
                  > full_expediting_start_date
            """
        )

        check_zero(
            con,
            "All production orders evaluated",
            """
            SELECT
                ABS(COUNT(*) - 30)
                + (
                    COUNT(*)
                    - COUNT(DISTINCT production_order_id)
                )
            FROM planning.targeted_expediting_orders
            """
        )

        check_zero(
            con,
            "Order delays match full expediting",
            """
            SELECT COUNT(*)
            FROM planning.targeted_expediting_orders t
            JOIN planning.recovery_order_scenarios e
                ON t.production_order_id =
                   e.production_order_id
               AND e.scenario_id = 'EXPEDITE_ALL'
            WHERE t.recovery_delay_days
                  <> e.scenario_delay_days
            """
        )

        check_zero(
            con,
            "No negative delays or spending",
            """
            SELECT COUNT(*)
            FROM planning.targeted_expediting_orders
            WHERE recovery_delay_days < 0
               OR additional_spend_usd < 0
               OR procurement_cost_usd < 0
            """
        )

        check_zero(
            con,
            "Targeted cost does not exceed full expediting",
            """
            SELECT COUNT(*)
            FROM planning.targeted_expediting_kpis
            WHERE savings_vs_expedite_all_usd < 0
               OR additional_spend_usd >
                  expedite_all_additional_spend_usd
            """
        )

        check_zero(
            con,
            "Procurement costs reconcile",
            """
            SELECT COUNT(*)
            FROM planning.targeted_expediting_kpis t
            JOIN planning.recovery_scenario_kpis s
                ON s.scenario_id = 'STANDARD_PO'
            WHERE ABS(
                t.procurement_cost_usd
                - s.modeled_procurement_cost_usd
                - t.additional_spend_usd
            ) > 0.01
            """
        )

        results = con.execute("""
            SELECT
                production_orders,
                on_time_orders,
                delayed_orders,
                standard_delay_days,
                targeted_delay_days,
                delay_days_reduced,
                total_shortage_lines,
                expedited_lines,
                procurement_cost_usd,
                additional_spend_usd,
                savings_vs_expedite_all_usd
            FROM planning.targeted_expediting_kpis
        """).fetchone()

        (
            total,
            on_time,
            delayed,
            standard_days,
            targeted_days,
            reduced_days,
            total_lines,
            expedited_lines,
            procurement_cost,
            additional_spend,
            savings,
        ) = results

        assert total == 30
        assert on_time + delayed == total
        assert standard_days - targeted_days == reduced_days
        assert 0 <= expedited_lines <= total_lines

        print("\nTARGETED EXPEDITING RESULTS")
        print("-" * 50)

        print(f"Production orders: {total}")
        print(f"On-time orders: {on_time}")
        print(f"Delayed orders: {delayed}")
        print(f"Standard delay days: {standard_days}")
        print(f"Targeted delay days: {targeted_days}")
        print(f"Delay days reduced: {reduced_days}")
        print(f"Total shortage lines: {total_lines}")
        print(f"Expedited lines: {expedited_lines}")

        print(f"\nTargeted procurement cost: ${procurement_cost:,.2f}")
        print(f"Additional spending: ${additional_spend:,.2f}")
        print(f"Savings versus expediting all: ${savings:,.2f}")

        print("\nSQL07B validation: PASSED")
        print("Validation checks passed: 10")

    finally:
        con.close()


if __name__ == "__main__":
    main()
