
from pathlib import Path
import duckdb


ROOT = Path(__file__).resolve().parents[1]

DB_PATH = (
    ROOT / "data" / "processed"
    / "manufacturing_readiness.duckdb"
)

SQL_PATH = ROOT / "sql" / "06_production_impact.sql"


def check_zero(con, label, query):
    issues = con.execute(query).fetchone()[0]

    if issues != 0:
        raise AssertionError(
            f"{label}: {issues} issue(s)"
        )

    print(f"[PASS] {label}")


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError("Database missing.")

    if not SQL_PATH.exists():
        raise FileNotFoundError("SQL06 file missing.")

    con = duckdb.connect(str(DB_PATH))

    try:
        # Verify previous analytical milestone.
        con.execute("""
            SELECT COUNT(*)
            FROM planning.shortage_exceptions
        """).fetchone()

        print("Running SQL06 production impact analysis...")

        con.execute(
            SQL_PATH.read_text(encoding="utf-8")
        )

        print("\nValidating production impact:\n")

        check_zero(
            con,
            "Every production order evaluated once",
            """
            SELECT
                ABS(COUNT(*) - 30)
                + (
                    COUNT(*)
                    - COUNT(DISTINCT production_order_id)
                )
            FROM planning.production_impact
            """
        )

        check_zero(
            con,
            "Readiness classifications reconcile",
            """
            SELECT COUNT(*)
            FROM planning.production_impact i
            JOIN planning.production_order_readiness r
                ON i.production_order_id =
                   r.production_order_id
            WHERE i.readiness_status
                  IS DISTINCT FROM r.readiness_status
            """
        )

        check_zero(
            con,
            "Order shortage quantities reconcile",
            """
            SELECT COUNT(*)
            FROM planning.production_impact i
            JOIN planning.production_order_readiness r
                ON i.production_order_id =
                   r.production_order_id
            WHERE i.shortage_component_count
                  <> r.shortage_component_count
               OR i.total_missing_component_units
                  <> r.total_shortage_units
            """
        )

        check_zero(
            con,
            "Only blocked orders have shortage exposure",
            """
            SELECT COUNT(*)
            FROM planning.production_impact
            WHERE (
                readiness_status = 'BLOCKED'
                AND (
                    shortage_component_count <= 0
                    OR total_missing_component_units <= 0
                )
            )
            OR (
                readiness_status <> 'BLOCKED'
                AND (
                    shortage_component_count <> 0
                    OR total_missing_component_units <> 0
                )
            )
            """
        )

        check_zero(
            con,
            "No negative modeled delays",
            """
            SELECT COUNT(*)
            FROM planning.production_impact
            WHERE illustrative_replenishment_delay_days < 0
               OR illustrative_replenishment_delay_days
                  IS NULL
            """
        )

        check_zero(
            con,
            "Unblocked orders retain original dates",
            """
            SELECT COUNT(*)
            FROM planning.production_impact
            WHERE readiness_status <> 'BLOCKED'
              AND (
                  illustrative_replenishment_delay_days <> 0
                  OR illustrative_replenishment_start_date
                     <> planned_start_date
                  OR illustrative_replenishment_due_date
                     <> planned_due_date
              )
            """
        )

        check_zero(
            con,
            "Illustrative schedule dates reconcile",
            """
            SELECT COUNT(*)
            FROM planning.production_impact
            WHERE illustrative_replenishment_start_date
                  < planned_start_date

               OR illustrative_replenishment_due_date
                  <> planned_due_date
                  + illustrative_replenishment_delay_days

               OR illustrative_replenishment_due_date
                  <= illustrative_replenishment_start_date
            """
        )

        check_zero(
            con,
            "Missing material units reconcile with SQL05",
            """
            SELECT ABS(
                (
                    SELECT SUM(total_missing_component_units)
                    FROM planning.production_impact
                )
                -
                (
                    SELECT SUM(shortage_qty)
                    FROM planning.shortage_exceptions
                )
            )
            """
        )

        check_zero(
            con,
            "Missing material value reconciles with SQL05",
            """
            SELECT CASE
                WHEN ABS(
                    (
                        SELECT SUM(
                            modeled_missing_material_value_usd
                        )
                        FROM planning.production_impact
                    )
                    -
                    (
                        SELECT SUM(
                            modeled_missing_material_value_usd
                        )
                        FROM planning.shortage_exceptions
                    )
                ) > 0.01
                THEN 1 ELSE 0
            END
            """
        )

        check_zero(
            con,
            "Product family totals reconcile",
            """
            SELECT
                ABS(
                    (SELECT SUM(total_orders)
                     FROM planning.family_production_exposure)
                    - 30
                )
                +
                ABS(
                    (SELECT SUM(blocked_orders)
                     FROM planning.family_production_exposure)
                    -
                    (SELECT COUNT(*)
                     FROM planning.production_impact
                     WHERE readiness_status = 'BLOCKED')
                )
            """
        )

        check_zero(
            con,
            "Component blast radius reconciles",
            """
            SELECT ABS(
                (
                    SELECT SUM(affected_orders)
                    FROM planning.component_blast_radius
                )
                -
                (
                    SELECT COUNT(*)
                    FROM planning.shortage_exceptions
                )
            )
            """
        )

        check_zero(
            con,
            "Order delays not double-counted in KPIs",
            """
            SELECT ABS(
                (
                    SELECT illustrative_total_order_delay_days
                    FROM planning.production_impact_kpis
                )
                -
                (
                    SELECT SUM(
                        illustrative_replenishment_delay_days
                    )
                    FROM planning.production_impact
                )
            )
            """
        )

        results = con.execute("""
            SELECT
                total_production_orders,
                ready_orders,
                at_risk_orders,
                blocked_orders,
                orders_with_illustrative_delay,
                illustrative_total_order_delay_days,
                total_missing_component_units,
                modeled_missing_material_value_usd
            FROM planning.production_impact_kpis
        """).fetchone()

        (
            total,
            ready,
            at_risk,
            blocked,
            delayed,
            delay_days,
            missing_units,
            missing_value,
        ) = results

        assert total == 30
        assert ready + at_risk + blocked == total

        print("\nMANUFACTURING PRODUCTION IMPACT")
        print("-" * 50)
        print(f"Total production orders: {total}")
        print(f"Material ready: {ready}")
        print(f"At risk: {at_risk}")
        print(f"Blocked: {blocked}")
        print(f"Missing component units: {missing_units}")
        print(f"Modeled missing material value: ${missing_value:,.2f}")

        print("\nILLUSTRATIVE STANDARD REPLENISHMENT")
        print("-" * 50)
        print(f"Orders with modeled delays: {delayed}")
        print(f"Sum of modeled order-delay days: {delay_days}")
        print("Assumption: New standard POs placed at snapshot.")
        print("These are not confirmed baseline delays.")

        print("\nTOP 10 ORDERS BY MODELED SCHEDULE EXPOSURE")
        print("-" * 50)

        top_orders = con.execute("""
            SELECT
                production_order_id,
                product_family_id,
                shortage_component_count,
                illustrative_replenishment_delay_days
            FROM planning.production_impact
            WHERE readiness_status = 'BLOCKED'
            ORDER BY
                illustrative_replenishment_delay_days DESC,
                shortage_component_count DESC,
                production_order_id
            LIMIT 10
        """).fetchall()

        for row in top_orders:
            print(
                f"{row[0]:<10} "
                f"Family: {row[1]:<7} "
                f"Short parts: {row[2]:<3} "
                f"Illustrative delay: {row[3]} days"
            )

        print("\nSQL06 validation: PASSED")
        print("Integrity checks passed: 12")
        print("Phase 2 / SQL06 completed successfully.")

    finally:
        con.close()


if __name__ == "__main__":
    main()
