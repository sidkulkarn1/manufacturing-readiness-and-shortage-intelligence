
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parents[1]

DB_PATH = (
    ROOT / "data" / "processed"
    / "manufacturing_readiness.duckdb"
)

SQL_PATH = ROOT / "sql" / "03_material_requirements.sql"


def main():

    if not DB_PATH.exists():
        raise FileNotFoundError("Run SQL01 and SQL02 first.")

    if not SQL_PATH.exists():
        raise FileNotFoundError("SQL03 script is missing.")

    con = duckdb.connect(str(DB_PATH))

    try:
        print("Running SQL03 BOM explosion...")

        con.execute(
            SQL_PATH.read_text(encoding="utf-8")
        )

        results = con.execute("""
            SELECT
                COUNT(*) AS requirement_rows,
                COUNT(DISTINCT production_order_id)
                    AS production_orders,
                COUNT(DISTINCT component_part_id)
                    AS purchased_components,
                MIN(gross_required_qty) AS minimum_qty
            FROM planning.component_requirements
        """).fetchone()

        rows, orders, components, min_qty = results

        print(f"Component requirement rows: {rows}")
        print(f"Production orders covered: {orders}")
        print(f"Unique purchased components: {components}")

        if rows != 3000:
            raise AssertionError(
                f"Expected 3000 requirement rows; found {rows}"
            )

        if orders != 30 or components != 400:
            raise AssertionError(
                "Incomplete manufacturing requirements."
            )

        if min_qty is None or min_qty <= 0:
            raise AssertionError(
                "Invalid component requirement quantities."
            )

        # Independently reconcile the recursive explosion
        # against the known two-level manufacturing BOM.
        mismatch_count = con.execute("""
            WITH expected AS (
                SELECT
                    o.production_order_id,
                    b2.component_part_id,
                    SUM(
                        CAST(o.order_quantity AS BIGINT)
                        * b1.quantity_per_parent
                        * b2.quantity_per_parent
                    ) AS expected_qty
                FROM core.production_orders o

                JOIN core.bom_structure b1
                    ON o.finished_good_id = b1.parent_part_id
                   AND o.finished_good_revision = b1.parent_revision

                JOIN core.bom_structure b2
                    ON b1.component_part_id = b2.parent_part_id
                   AND b1.component_revision = b2.parent_revision

                WHERE o.material_required_date
                    >= b1.effective_start_date
                  AND (
                      b1.effective_end_date IS NULL
                      OR o.material_required_date
                          <= b1.effective_end_date
                  )
                  AND o.material_required_date
                    >= b2.effective_start_date
                  AND (
                      b2.effective_end_date IS NULL
                      OR o.material_required_date
                          <= b2.effective_end_date
                  )

                GROUP BY
                    o.production_order_id,
                    b2.component_part_id
            )

            SELECT COUNT(*)
            FROM expected e

            FULL OUTER JOIN planning.component_requirements r
                ON e.production_order_id = r.production_order_id
               AND e.component_part_id = r.component_part_id

            WHERE e.expected_qty
                IS DISTINCT FROM r.gross_required_qty
        """).fetchone()[0]

        if mismatch_count != 0:
            raise AssertionError(
                f"BOM reconciliation failed: "
                f"{mismatch_count} mismatches"
            )

        summary = con.execute("""
            SELECT
                COUNT(*) AS orders,
                SUM(total_component_units) AS units,
                SUM(modeled_gross_material_cost_usd) AS cost
            FROM planning.order_material_summary
        """).fetchone()

        if summary[0] != 30:
            raise AssertionError(
                "Production-order summary is incomplete."
            )

        print("\nBOM reconciliation: PASSED")
        print(f"Total component units required: {summary[1]}")
        print(f"Modeled gross material value: ${summary[2]:,.2f}")

        print("\nSQL03 validation: PASSED")
        print("Phase 2 / SQL03 completed successfully.")

    finally:
        con.close()


if __name__ == "__main__":
    main()
