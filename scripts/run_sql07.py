
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parents[1]

DB_PATH = (
    ROOT / "data" / "processed"
    / "manufacturing_readiness.duckdb"
)

SQL_PATH = ROOT / "sql" / "07_recovery_analysis.sql"

SCENARIOS = (
    "STANDARD_PO",
    "EXPEDITE_ALL",
    "QUALIFIED_ALTERNATE",
)


def check_zero(con, label, query):
    issues = con.execute(query).fetchone()[0]

    if issues != 0:
        raise AssertionError(
            f"{label}: {issues} issue(s)"
        )

    print(f"[PASS] {label}")


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(
            "Database missing. Run SQL01–SQL06 first."
        )

    if not SQL_PATH.exists():
        raise FileNotFoundError("SQL07 file missing.")

    sql = SQL_PATH.read_text(encoding="utf-8")

    if (
        "CREATE OR REPLACE TABLE" not in sql
        or "COMMIT;" not in sql
    ):
        raise ValueError(
            "SQL07 is empty or incomplete. Save the SQL file."
        )

    con = duckdb.connect(str(DB_PATH))

    try:
        # Verify SQL06 exists.
        con.execute("""
            SELECT COUNT(*)
            FROM planning.production_impact
        """).fetchone()

        print("Running SQL07 recovery scenario analysis...")

        con.execute(sql)

        print("\nValidating recovery scenarios:\n")

        check_zero(
            con,
            "Recovery demand matches SQL05 shortages",
            """
            SELECT ABS(
                (SELECT COUNT(*)
                 FROM planning.recovery_demand)
                -
                (SELECT COUNT(*)
                 FROM planning.shortage_exceptions)
            )
            """
        )

        check_zero(
            con,
            "All shortage units are sourced exactly once",
            """
            WITH supplied AS (
                SELECT
                    scenario_id,
                    production_order_id,
                    component_part_id,
                    component_revision,
                    SUM(sourced_qty) AS supplied_qty
                FROM planning.recovery_procurement
                GROUP BY 1, 2, 3, 4
            ),
            scenarios AS (
                SELECT scenario_id
                FROM (
                    VALUES
                        ('STANDARD_PO'),
                        ('EXPEDITE_ALL'),
                        ('QUALIFIED_ALTERNATE')
                ) v(scenario_id)
            )
            SELECT COUNT(*)
            FROM planning.shortage_exceptions e
            CROSS JOIN scenarios s
            LEFT JOIN supplied p
                ON e.production_order_id =
                   p.production_order_id
               AND e.component_part_id =
                   p.component_part_id
               AND e.component_revision =
                   p.component_revision
               AND s.scenario_id = p.scenario_id
            WHERE COALESCE(p.supplied_qty, 0)
                  <> e.shortage_qty
            """
        )

        check_zero(
            con,
            "No invalid procurement quantities or prices",
            """
            SELECT COUNT(*)
            FROM planning.recovery_procurement
            WHERE sourced_qty IS NULL
               OR sourced_qty <= 0
               OR scenario_unit_cost_usd IS NULL
               OR scenario_unit_cost_usd <= 0
               OR modeled_procurement_cost_usd < 0
               OR expected_arrival_date IS NULL
            """
        )

        check_zero(
            con,
            "Approved alternate capacity respected",
            """
            WITH usage AS (
                SELECT
                    p.component_part_id,
                    p.component_revision,
                    SUM(p.sourced_qty) AS used_qty,
                    MAX(a.max_available_qty) AS capacity_qty
                FROM planning.recovery_procurement p
                JOIN core.approved_alternates a
                    ON p.component_part_id = a.part_id
                   AND p.component_revision =
                       a.approved_revision
                WHERE p.scenario_id =
                      'QUALIFIED_ALTERNATE'
                  AND p.source_type =
                      'QUALIFIED_ALTERNATE'
                GROUP BY 1, 2
            )
            SELECT COUNT(*)
            FROM usage
            WHERE used_qty > capacity_qty
            """
        )

        check_zero(
            con,
            "Alternate source qualification verified",
            """
            SELECT COUNT(*)
            FROM planning.recovery_procurement p

            LEFT JOIN core.approved_alternates a
                ON p.component_part_id = a.part_id
               AND p.component_revision =
                   a.approved_revision
               AND a.approval_status = 'APPROVED'

            WHERE p.source_type = 'QUALIFIED_ALTERNATE'
              AND (
                  a.alternate_id IS NULL
                  OR a.qualification_date >
                     (SELECT MAX(snapshot_date)
                      FROM core.inventory)
              )
            """
        )

        check_zero(
            con,
            "No recovery arrivals before planning snapshot",
            """
            SELECT COUNT(*)
            FROM planning.recovery_procurement
            WHERE expected_arrival_date <
                (SELECT MAX(snapshot_date)
                 FROM core.inventory)
            """
        )

        check_zero(
            con,
            "Exactly 30 orders evaluated per scenario",
            """
            WITH counts AS (
                SELECT
                    scenario_id,
                    COUNT(*) AS rows_count,
                    COUNT(DISTINCT production_order_id)
                        AS unique_orders
                FROM planning.recovery_order_scenarios
                GROUP BY scenario_id
            )
            SELECT
                ABS(COUNT(*) - 3)
                + COALESCE(SUM(
                    ABS(rows_count - 30)
                    + ABS(unique_orders - 30)
                ), 0)
            FROM counts
            """
        )

        check_zero(
            con,
            "No missing recovery dates for blocked orders",
            """
            SELECT COUNT(*)
            FROM planning.recovery_order_scenarios
            WHERE readiness_status = 'BLOCKED'
              AND (
                  latest_recovery_arrival_date IS NULL
                  OR scenario_delay_days IS NULL
              )
            """
        )

        check_zero(
            con,
            "Standard recovery matches SQL06",
            """
            SELECT COUNT(*)
            FROM planning.recovery_order_scenarios
            WHERE scenario_id = 'STANDARD_PO'
              AND scenario_delay_days
                  IS DISTINCT FROM standard_reference_delay_days
            """
        )

        check_zero(
            con,
            "No scenario increases modeled delays",
            """
            SELECT COUNT(*)
            FROM planning.recovery_order_scenarios
            WHERE scenario_delay_days >
                  standard_reference_delay_days
               OR scenario_delay_days < 0
            """
        )

        check_zero(
            con,
            "Scenario procurement costs reconcile",
            """
            SELECT COUNT(*)
            FROM planning.recovery_procurement
            WHERE ABS(
                modeled_procurement_cost_usd
                - sourced_qty * scenario_unit_cost_usd
            ) > 0.01
            """
        )

        check_zero(
            con,
            "Executive scenario totals reconcile",
            """
            SELECT COUNT(*)
            FROM planning.recovery_scenario_kpis
            WHERE production_orders <> 30
               OR on_time_orders + delayed_orders <> 30
               OR modeled_order_delay_days_reduced <>
                  reference_total_order_delay_days
                  - modeled_total_order_delay_days
               OR modeled_procurement_cost_usd < 0
            """
        )

        print("\nRECOVERY SCENARIO COMPARISON")
        print("-" * 65)

        results = con.execute("""
            SELECT
                scenario_id,
                on_time_orders,
                delayed_orders,
                modeled_total_order_delay_days,
                modeled_order_delay_days_reduced,
                modeled_procurement_cost_usd,
                additional_spend_vs_standard_usd
            FROM planning.recovery_comparison
            ORDER BY
                CASE scenario_id
                    WHEN 'STANDARD_PO' THEN 1
                    WHEN 'EXPEDITE_ALL' THEN 2
                    ELSE 3
                END
        """).fetchall()

        assert len(results) == 3

        for row in results:
            (
                scenario,
                on_time,
                delayed,
                delay_days,
                reduced_days,
                cost,
                extra_spend,
            ) = row

            print(f"\nScenario: {scenario}")
            print(f"On-time orders: {on_time}")
            print(f"Delayed orders: {delayed}")
            print(f"Modeled order-delay days: {delay_days}")
            print(f"Delay days reduced: {reduced_days}")
            print(f"Procurement cost: ${cost:,.2f}")
            print(
                f"Additional spend vs standard: "
                f"${extra_spend:,.2f}"
            )

        alt_usage = con.execute("""
            SELECT
                COUNT(DISTINCT component_part_id),
                COALESCE(SUM(sourced_qty), 0)
            FROM planning.recovery_procurement
            WHERE scenario_id = 'QUALIFIED_ALTERNATE'
              AND source_type = 'QUALIFIED_ALTERNATE'
        """).fetchone()

        print("\nQUALIFIED ALTERNATE UTILIZATION")
        print("-" * 65)
        print(f"Components using alternates: {alt_usage[0]}")
        print(f"Alternate-sourced units: {alt_usage[1]}")

        print("\nSQL07 validation: PASSED")
        print("Integrity checks passed: 12")

    finally:
        con.close()


if __name__ == "__main__":
    main()
