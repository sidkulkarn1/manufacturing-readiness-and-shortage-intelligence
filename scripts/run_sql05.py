
from pathlib import Path
import duckdb


ROOT = Path(__file__).resolve().parents[1]

DB_PATH = (
    ROOT / "data" / "processed"
    / "manufacturing_readiness.duckdb"
)

SQL_PATH = ROOT / "sql" / "05_shortage_analysis.sql"


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
            "Manufacturing database missing."
        )

    if not SQL_PATH.exists():
        raise FileNotFoundError(
            "SQL05 script missing."
        )

    con = duckdb.connect(str(DB_PATH))

    try:
        # Require the material-readiness outputs before shortage analysis.
        con.execute("""
            SELECT COUNT(*)
            FROM planning.component_readiness
        """).fetchone()

        print("Running SQL05 shortage intelligence...")

        con.execute(
            SQL_PATH.read_text(encoding="utf-8")
        )

        print("\nValidating shortage calculations:\n")

        # ----------------------------------------------------
        # 1. Shortages must be positive
        # ----------------------------------------------------

        check_zero(
            con,
            "Positive shortage quantities",
            """
            SELECT COUNT(*)
            FROM planning.shortage_exceptions
            WHERE shortage_qty <= 0
               OR shortage_qty IS NULL
            """
        )

        # ----------------------------------------------------
        # 2. No missing component or supplier data
        # ----------------------------------------------------

        check_zero(
            con,
            "Component and supplier completeness",
            """
            SELECT COUNT(*)
            FROM planning.shortage_exceptions
            WHERE component_part_id IS NULL
               OR production_order_id IS NULL
               OR supplier_id IS NULL
               OR supplier_name IS NULL
               OR unit_cost_usd IS NULL
               OR lead_time_days IS NULL
            """
        )

        # ----------------------------------------------------
        # 3. No duplicate shortage records
        # ----------------------------------------------------

        check_zero(
            con,
            "Unique production-order component exceptions",
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    production_order_id,
                    component_part_id,
                    component_revision,
                    COUNT(*) AS records
                FROM planning.shortage_exceptions
                GROUP BY 1, 2, 3
                HAVING COUNT(*) > 1
            )
            """
        )

        # ----------------------------------------------------
        # 4. Source shortage line counts reconcile
        # ----------------------------------------------------

        check_zero(
            con,
            "Shortage lines reconcile with SQL04",
            """
            SELECT ABS(
                (SELECT COUNT(*)
                 FROM planning.shortage_exceptions)

                -

                (SELECT COUNT(*)
                 FROM planning.component_readiness
                 WHERE shortage_qty > 0)
            )
            """
        )

        # ----------------------------------------------------
        # 5. Shortage quantities reconcile with SQL04
        # ----------------------------------------------------

        check_zero(
            con,
            "Shortage units reconcile with SQL04",
            """
            SELECT ABS(
                (SELECT COALESCE(SUM(shortage_qty), 0)
                 FROM planning.shortage_exceptions)

                -

                (SELECT COALESCE(SUM(shortage_qty), 0)
                 FROM planning.component_readiness)
            )
            """
        )

        # ----------------------------------------------------
        # 6. Individual shortage records reconcile
        # ----------------------------------------------------

        check_zero(
            con,
            "Individual component shortages reconcile",
            """
            SELECT COUNT(*)
            FROM planning.shortage_exceptions e

            LEFT JOIN planning.component_readiness c
                ON e.production_order_id =
                   c.production_order_id
               AND e.component_part_id =
                   c.component_part_id
               AND e.component_revision =
                   c.component_revision

            WHERE c.production_order_id IS NULL
               OR e.shortage_qty <> c.shortage_qty
            """
        )

        # ----------------------------------------------------
        # 7. Blocked production orders reconcile
        # ----------------------------------------------------

        check_zero(
            con,
            "Blocked order classification",
            """
            WITH shortages AS (
                SELECT
                    production_order_id,
                    COUNT(*) AS shortage_lines,
                    SUM(shortage_qty) AS missing_units
                FROM planning.shortage_exceptions
                GROUP BY production_order_id
            )

            SELECT COUNT(*)
            FROM planning.production_order_readiness r

            LEFT JOIN shortages s
                ON r.production_order_id =
                   s.production_order_id

            WHERE COALESCE(s.shortage_lines, 0)
                    <> r.shortage_component_count

               OR COALESCE(s.missing_units, 0)
                    <> r.total_shortage_units

               OR (
                   r.readiness_status = 'BLOCKED'
               ) <> (
                   COALESCE(s.shortage_lines, 0) > 0
               )
            """
        )

        # ----------------------------------------------------
        # 8. Missing material values reconcile
        # ----------------------------------------------------

        check_zero(
            con,
            "Modeled missing material value",
            """
            SELECT COUNT(*)
            FROM planning.shortage_exceptions
            WHERE ABS(
                modeled_missing_material_value_usd
                - shortage_qty * unit_cost_usd
            ) > 0.01
            """
        )

        # ----------------------------------------------------
        # 9. Component priority summaries reconcile
        # ----------------------------------------------------

        check_zero(
            con,
            "Component priority aggregation",
            """
            WITH expected AS (
                SELECT
                    component_part_id,
                    component_revision,
                    SUM(shortage_qty) AS expected_qty,
                    COUNT(DISTINCT production_order_id)
                        AS expected_orders
                FROM planning.shortage_exceptions
                GROUP BY 1, 2
            )

            SELECT COUNT(*)
            FROM expected e

            FULL OUTER JOIN planning.shortage_priority p
                ON e.component_part_id = p.component_part_id
               AND e.component_revision = p.component_revision

            WHERE e.component_part_id IS NULL
               OR p.component_part_id IS NULL
               OR e.expected_qty <> p.total_shortage_units
               OR e.expected_orders <> p.affected_orders
            """
        )

        # ----------------------------------------------------
        # 10. Priority scores are valid
        # ----------------------------------------------------

        check_zero(
            con,
            "Risk scores and severity classifications",
            """
            SELECT COUNT(*)
            FROM planning.shortage_priority
            WHERE risk_score NOT BETWEEN 0 AND 100
               OR risk_score IS NULL
               OR shortage_severity NOT IN (
                   'CRITICAL', 'HIGH', 'MODERATE'
               )
            """
        )

        # ----------------------------------------------------
        # 11. Supplier quantities reconcile
        # ----------------------------------------------------

        check_zero(
            con,
            "Supplier shortage quantities reconcile",
            """
            SELECT ABS(
                (SELECT COALESCE(SUM(total_shortage_units), 0)
                 FROM planning.supplier_shortage_exposure)

                -

                (SELECT COALESCE(SUM(shortage_qty), 0)
                 FROM planning.shortage_exceptions)
            )
            """
        )

        # ----------------------------------------------------
        # 12. Executive KPI affected orders reconcile
        # ----------------------------------------------------

        check_zero(
            con,
            "Affected production order KPI",
            """
            SELECT ABS(
                (SELECT affected_production_orders
                 FROM planning.shortage_kpis)

                -

                (SELECT COUNT(*)
                 FROM planning.production_order_readiness
                 WHERE readiness_status = 'BLOCKED')
            )
            """
        )

        # ----------------------------------------------------
        # Business Outputs
        # ----------------------------------------------------

        kpis = con.execute("""
            SELECT *
            FROM planning.shortage_kpis
        """).fetchone()

        (
            components,
            affected_orders,
            shortage_lines,
            shortage_units,
            missing_value,
            critical,
            high,
        ) = kpis

        print("\nMANUFACTURING SHORTAGE INTELLIGENCE")
        print("-" * 50)

        print(f"Unique short components: {components}")
        print(f"Affected production orders: {affected_orders}")
        print(f"Shortage exception lines: {shortage_lines}")
        print(f"Total missing component units: {shortage_units}")
        print(f"Critical components: {critical}")
        print(f"High-severity components: {high}")

        print(
            f"Modeled missing material value: "
            f"${missing_value:,.2f}"
        )

        print("\nTOP 10 COMPONENT SHORTAGES")
        print("-" * 50)

        top_shortages = con.execute("""
            SELECT
                shortage_rank,
                component_part_id,
                affected_orders,
                total_shortage_units,
                risk_score,
                shortage_severity
            FROM planning.shortage_priority
            ORDER BY shortage_rank
            LIMIT 10
        """).fetchall()

        for row in top_shortages:
            print(
                f"#{row[0]:<3} "
                f"{row[1]:<10} "
                f"Orders: {row[2]:<3} "
                f"Missing: {row[3]:<6} "
                f"Score: {row[4]:<3} "
                f"{row[5]}"
            )

        print("\nSQL05 validation: PASSED")
        print("Integrity checks passed: 12")

    finally:
        con.close()


if __name__ == "__main__":
    main()
