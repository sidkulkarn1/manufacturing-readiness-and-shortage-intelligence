
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parents[1]

DB_PATH = (
    ROOT / "data" / "processed"
    / "manufacturing_readiness.duckdb"
)

SQL_PATH = ROOT / "sql" / "04_material_readiness.sql"


def assert_zero(con, label, query):
    issues = con.execute(query).fetchone()[0]

    if issues != 0:
        raise AssertionError(
            f"{label}: {issues} issue(s)"
        )

    print(f"[PASS] {label}")


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(
            "Database missing. Run SQL01 first."
        )

    if not SQL_PATH.exists():
        raise FileNotFoundError("SQL04 script missing.")

    con = duckdb.connect(str(DB_PATH))

    try:
        # Confirm SQL03 has been executed.
        con.execute("""
            SELECT COUNT(*)
            FROM planning.component_requirements
        """).fetchone()

        print("Running SQL04 material readiness analysis...")

        con.execute(
            SQL_PATH.read_text(encoding="utf-8")
        )

        print("\nValidating material availability:\n")

        assert_zero(
            con,
            "No negative free inventory",
            """
            SELECT COUNT(*)
            FROM planning.inventory_position
            WHERE free_stock_qty < 0
            """
        )

        assert_zero(
            con,
            "Reservations do not exceed requirements",
            """
            SELECT COUNT(*)
            FROM planning.demand_queue
            WHERE reserved_qty < 0
               OR unreserved_requirement_qty < 0
            """
        )

        assert_zero(
            con,
            "Component quantities reconcile",
            """
            SELECT COUNT(*)
            FROM planning.component_readiness
            WHERE gross_required_qty <>
                reserved_qty
                + covered_unreserved_qty
                + shortage_qty
               OR shortage_qty < 0
               OR covered_unreserved_qty < 0
            """
        )

        assert_zero(
            con,
            "No component allocated beyond its requirement",
            """
            SELECT COUNT(*)
            FROM planning.component_readiness
            WHERE covered_unreserved_qty
                  > unreserved_requirement_qty
               OR covered_from_stock_only_qty
                  > covered_unreserved_qty
            """
        )

        assert_zero(
            con,
            "Time-phased supply capacity respected",
            """
            WITH dates AS (
                SELECT DISTINCT
                    component_part_id,
                    component_revision,
                    material_required_date
                FROM planning.component_readiness
            ),
            usage AS (
                SELECT
                    d.component_part_id,
                    d.component_revision,
                    d.material_required_date,
                    SUM(c.covered_unreserved_qty)
                        AS cumulative_covered_qty
                FROM dates d
                JOIN planning.component_readiness c
                    ON d.component_part_id =
                       c.component_part_id
                   AND d.component_revision =
                       c.component_revision
                   AND c.material_required_date
                       <= d.material_required_date
                GROUP BY
                    d.component_part_id,
                    d.component_revision,
                    d.material_required_date
            )
            SELECT COUNT(*)
            FROM usage u
            JOIN planning.inventory_position i
                ON u.component_part_id = i.part_id
               AND u.component_revision = i.revision
            WHERE u.cumulative_covered_qty >
                i.free_stock_qty + COALESCE((
                    SELECT SUM(po.inbound_qty)
                    FROM planning.receipt_schedule po
                    WHERE po.part_id = u.component_part_id
                      AND po.revision = u.component_revision
                      AND po.expected_receipt_date
                          <= u.material_required_date
                ), 0)
            """
        )

        expected_rows = con.execute("""
            SELECT COUNT(*)
            FROM planning.component_requirements
        """).fetchone()[0]

        actual_rows = con.execute("""
            SELECT COUNT(*)
            FROM planning.component_readiness
        """).fetchone()[0]

        assert expected_rows == actual_rows, (
            "Component coverage is incomplete."
        )

        assert expected_rows == 3000, (
            f"Expected 3000 requirements, "
            f"found {expected_rows}"
        )

        print("[PASS] All component requirements evaluated")

        results = con.execute("""
            SELECT
                total_production_orders,
                ready_orders,
                at_risk_orders,
                blocked_orders,
                readiness_rate_pct
            FROM planning.readiness_kpis
        """).fetchone()

        total, ready, at_risk, blocked, rate = results

        assert total == 30, (
            f"Expected 30 production orders, found {total}"
        )

        assert ready + at_risk + blocked == total

        assert con.execute("""
            SELECT COUNT(*)
            FROM planning.production_order_readiness
            WHERE required_component_count <> 100
        """).fetchone()[0] == 0

        assert_zero(
            con,
            "Production order status classification",
            """
            SELECT COUNT(*)
            FROM planning.production_order_readiness
            WHERE
                (readiness_status = 'MATERIAL_READY'
                 AND (
                    shortage_component_count <> 0
                    OR inbound_dependent_component_count <> 0
                 ))
                OR
                (readiness_status = 'AT_RISK'
                 AND (
                    shortage_component_count <> 0
                    OR inbound_dependent_component_count = 0
                 ))
                OR
                (readiness_status = 'BLOCKED'
                 AND shortage_component_count = 0)
            """
        )

        print("\nManufacturing Readiness Results")
        print("-" * 40)
        print(f"Total production orders: {total}")
        print(f"Material ready: {ready}")
        print(f"At risk: {at_risk}")
        print(f"Blocked: {blocked}")
        print(f"Readiness rate: {rate}%")

        print("\nSQL04 validation: PASSED")

    finally:
        con.close()


if __name__ == "__main__":
    main()
