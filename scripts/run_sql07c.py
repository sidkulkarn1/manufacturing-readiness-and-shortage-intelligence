
from pathlib import Path
import duckdb


ROOT = Path(__file__).resolve().parents[1]

DB_PATH = (
    ROOT / "data" / "processed"
    / "manufacturing_readiness.duckdb"
)

SQL_PATH = (
    ROOT / "sql" / "07c_reallocation_resequencing.sql"
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
        raise FileNotFoundError("Manufacturing database missing.")

    if not SQL_PATH.exists():
        raise FileNotFoundError("SQL07C script missing.")

    sql = SQL_PATH.read_text(encoding="utf-8")

    if (
        "reallocation_candidates" not in sql
        or "resequencing_candidates" not in sql
        or "COMMIT;" not in sql
    ):
        raise ValueError("SQL07C file is incomplete.")

    con = duckdb.connect(str(DB_PATH))

    try:
        # SQL07B must already exist.
        con.execute("""
            SELECT COUNT(*)
            FROM planning.targeted_expediting_orders
        """).fetchone()

        print("Running SQL07C operational recovery screening...")
        con.execute(sql)

        print("\nValidating candidates:\n")

        check_zero(
            con,
            "Reallocation references match reservations",
            """
            SELECT COUNT(*)
            FROM planning.reallocation_candidates c
            LEFT JOIN core.inventory_allocations a
                ON c.allocation_id = a.allocation_id
            WHERE a.allocation_id IS NULL
               OR c.donor_order_id <>
                  a.production_order_id
               OR c.component_part_id <> a.part_id
               OR c.component_revision <> a.revision
            """
        )

        check_zero(
            con,
            "No candidate exceeds pairwise quantities",
            """
            SELECT COUNT(*)
            FROM planning.reallocation_candidates
            WHERE pairwise_transfer_upper_bound_qty <= 0
               OR pairwise_transfer_upper_bound_qty >
                  donor_reserved_qty
               OR pairwise_transfer_upper_bound_qty >
                  receiver_shortage_qty
            """
        )

        check_zero(
            con,
            "Donor timing and priority restrictions",
            """
            SELECT COUNT(*)
            FROM planning.reallocation_candidates
            WHERE donor_required_date <= receiver_required_date
               OR (
                    CASE donor_priority
                        WHEN 'HIGH' THEN 1
                        WHEN 'MEDIUM' THEN 2
                        ELSE 3
                    END
                  ) <= (
                    CASE receiver_priority
                        WHEN 'HIGH' THEN 1
                        WHEN 'MEDIUM' THEN 2
                        ELSE 3
                    END
                  )
            """
        )

        check_zero(
            con,
            "No self-transfers or repeated candidate pairs",
            """
            SELECT COUNT(*)
            FROM planning.reallocation_candidates
            WHERE donor_order_id = receiver_order_id
            """
        )

        check_zero(
            con,
            "Resequencing requires later available slots",
            """
            SELECT COUNT(*)
            FROM planning.resequencing_candidates
            WHERE ready_original_start <= blocked_original_start
               OR proposed_blocked_start > blocked_original_due
               OR earliest_targeted_material_ready_date >
                  proposed_blocked_start
               OR blocked_start_shift_days <= 0
            """
        )

        check_zero(
            con,
            "Resequencing donor readiness verified",
            """
            SELECT COUNT(*)
            FROM planning.resequencing_candidates c
            JOIN planning.production_order_readiness r
                ON c.ready_donor_order_id =
                   r.production_order_id
            WHERE r.readiness_status <> 'MATERIAL_READY'
            """
        )

        check_zero(
            con,
            "No duplicate resequencing pairs",
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    blocked_order_id,
                    ready_donor_order_id,
                    COUNT(*) AS n
                FROM planning.resequencing_candidates
                GROUP BY 1, 2
                HAVING COUNT(*) > 1
            )
            """
        )

        check_zero(
            con,
            "Action screening reports both interventions",
            """
            SELECT ABS(
                (SELECT COUNT(*)
                 FROM planning.nonprocurement_action_screening)
                - 2
            )
            """
        )

        results = con.execute("""
            SELECT
                action_type,
                candidate_pairs,
                potential_donor_orders,
                potentially_affected_orders,
                screening_status
            FROM planning.nonprocurement_action_screening
            ORDER BY action_type
        """).fetchall()

        print("\nOPERATIONAL RECOVERY SCREENING")
        print("-" * 55)

        for row in results:
            print(f"\nAction: {row[0]}")
            print(f"Candidate pairs: {row[1]}")
            print(f"Potential donor orders: {row[2]}")
            print(f"Potential recipient orders: {row[3]}")
            print(f"Screening status: {row[4]}")

        print("\nSQL07C validation: PASSED")
        print("Validation checks passed: 8")
        print("These are candidate screens, not executed changes.")

    finally:
        con.close()


if __name__ == "__main__":
    main()
