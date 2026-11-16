
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parents[1]

DB_PATH = (
    ROOT / "data" / "processed"
    / "manufacturing_readiness.duckdb"
)

SQL_PATH = ROOT / "sql" / "02_data_integrity_checks.sql"

EXPECTED_TABLES = 11

# ------------------------------------------------------------
# 1. Primary Key Definitions
# ------------------------------------------------------------

PRIMARY_KEYS = {
    "product_families": "family_id",
    "suppliers": "supplier_id",
    "part_master": "part_id",
    "bom_structure": "bom_line_id",
    "production_orders": "production_order_id",
    "inventory": "inventory_record_id",
    "inventory_allocations": "allocation_id",
    "purchase_orders": "purchase_order_id",
    "engineering_changes": "change_id",
    "approved_alternates": "alternate_id",
    "disruption_scenarios": "scenario_id",
}


# ------------------------------------------------------------
# 2. Build Validation Queries
# ------------------------------------------------------------

def build_validation_checks():
    checks = []

    # A. Primary key uniqueness and non-null identifiers
    for table, key in PRIMARY_KEYS.items():
        checks.append((
            f"Primary key integrity: {table}",
            f"""
            SELECT COUNT(*) - COUNT(DISTINCT {key})
            FROM core.{table}
            """
        ))

    # B. Manufacturing relational integrity
    checks.extend([

        (
            "Part family references",
            """
            SELECT COUNT(*)
            FROM core.part_master p
            LEFT JOIN core.product_families f
                ON p.product_family_id = f.family_id
            WHERE f.family_id IS NULL
            """
        ),

        (
            "Purchased component supplier references",
            """
            SELECT COUNT(*)
            FROM core.part_master p
            LEFT JOIN core.suppliers s
                ON p.primary_supplier_id = s.supplier_id
            WHERE p.part_type = 'PURCHASED_COMPONENT'
              AND (
                  s.supplier_id IS NULL
                  OR p.unit_cost_usd IS NULL
                  OR p.unit_cost_usd <= 0
                  OR p.lead_time_days IS NULL
                  OR p.lead_time_days <= 0
              )
            """
        ),

        (
            "BOM component references and revisions",
            """
            SELECT COUNT(*)
            FROM core.bom_structure b
            LEFT JOIN core.part_master p
                ON b.parent_part_id = p.part_id
            LEFT JOIN core.part_master c
                ON b.component_part_id = c.part_id
            WHERE p.part_id IS NULL
               OR c.part_id IS NULL
               OR b.parent_revision IS DISTINCT FROM p.revision
               OR b.component_revision IS DISTINCT FROM c.revision
               OR b.quantity_per_parent IS NULL
               OR b.quantity_per_parent <= 0
            """
        ),

        (
            "BOM manufacturing hierarchy",
            """
            SELECT COUNT(*)
            FROM core.bom_structure b
            JOIN core.part_master p
                ON b.parent_part_id = p.part_id
            JOIN core.part_master c
                ON b.component_part_id = c.part_id
            WHERE p.product_family_id <> c.product_family_id
               OR NOT (
                   (
                       p.part_type = 'FINISHED_GOOD'
                       AND c.part_type = 'SUBASSEMBLY'
                   )
                   OR
                   (
                       p.part_type = 'SUBASSEMBLY'
                       AND c.part_type = 'PURCHASED_COMPONENT'
                   )
               )
            """
        ),

        (
            "Production order references and dates",
            """
            SELECT COUNT(*)
            FROM core.production_orders o
            LEFT JOIN core.part_master p
                ON o.finished_good_id = p.part_id
            WHERE p.part_id IS NULL
               OR p.part_type <> 'FINISHED_GOOD'
               OR o.finished_good_revision IS DISTINCT FROM p.revision
               OR o.product_family_id IS DISTINCT FROM p.product_family_id
               OR o.order_quantity IS NULL
               OR o.order_quantity <= 0
               OR o.planned_start_date IS NULL
               OR o.material_required_date IS NULL
               OR o.planned_due_date IS NULL
               OR o.material_required_date <> o.planned_start_date
               OR o.planned_due_date <= o.planned_start_date
               OR o.planned_week NOT BETWEEN 1 AND 8
            """
        ),

        (
            "Inventory quantity and revision integrity",
            """
            SELECT COUNT(*)
            FROM core.inventory i
            LEFT JOIN core.part_master p
                ON i.part_id = p.part_id
            WHERE p.part_id IS NULL
               OR p.part_type <> 'PURCHASED_COMPONENT'
               OR i.revision IS DISTINCT FROM p.revision
               OR i.on_hand_qty IS NULL
               OR i.quality_hold_qty IS NULL
               OR i.on_hand_qty < 0
               OR i.quality_hold_qty < 0
               OR i.quality_hold_qty > i.on_hand_qty
            """
        ),

        (
            "Inventory allocation references",
            """
            SELECT COUNT(*)
            FROM core.inventory_allocations a
            LEFT JOIN core.production_orders o
                ON a.production_order_id = o.production_order_id
            LEFT JOIN core.inventory i
                ON a.part_id = i.part_id
               AND a.revision = i.revision
               AND a.location_id = i.location_id
            WHERE o.production_order_id IS NULL
               OR i.inventory_record_id IS NULL
               OR a.allocated_qty IS NULL
               OR a.allocated_qty <= 0
            """
        ),

        (
            "Inventory overallocations",
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    i.inventory_record_id,
                    i.on_hand_qty,
                    i.quality_hold_qty,
                    COALESCE(
                        SUM(a.allocated_qty), 0
                    ) AS total_allocated
                FROM core.inventory i
                LEFT JOIN core.inventory_allocations a
                    ON i.part_id = a.part_id
                   AND i.revision = a.revision
                   AND i.location_id = a.location_id
                GROUP BY
                    i.inventory_record_id,
                    i.on_hand_qty,
                    i.quality_hold_qty
            ) x
            WHERE total_allocated >
                on_hand_qty - quality_hold_qty
            """
        ),

        (
            "Purchase order supplier and date integrity",
            """
            SELECT COUNT(*)
            FROM core.purchase_orders po
            LEFT JOIN core.part_master p
                ON po.part_id = p.part_id
            LEFT JOIN core.suppliers s
                ON po.supplier_id = s.supplier_id
            WHERE p.part_id IS NULL
               OR s.supplier_id IS NULL
               OR po.revision IS DISTINCT FROM p.revision
               OR po.supplier_id IS DISTINCT FROM p.primary_supplier_id
               OR po.ordered_qty IS NULL
               OR po.ordered_qty <= 0
               OR po.unit_cost_usd IS NULL
               OR po.unit_cost_usd <= 0
               OR po.order_date IS NULL
               OR po.original_promised_date IS NULL
               OR po.expected_receipt_date IS NULL
               OR po.original_promised_date <= po.order_date
               OR po.expected_receipt_date <
                  po.original_promised_date
               OR po.delay_days IS NULL
               OR po.delay_days <> date_diff(
                   'day',
                   po.original_promised_date,
                   po.expected_receipt_date
               )
            """
        ),

        (
            "Engineering change references",
            """
            SELECT COUNT(*)
            FROM core.engineering_changes e
            LEFT JOIN core.part_master p
                ON e.part_id = p.part_id
            WHERE p.part_id IS NULL
               OR p.part_type <> 'PURCHASED_COMPONENT'
               OR e.old_revision IS DISTINCT FROM p.revision
               OR e.proposed_revision IS NULL
               OR e.proposed_revision = e.old_revision
               OR e.affected_bom_lines IS NULL
               OR e.affected_bom_lines <= 0
               OR (
                   e.approval_status = 'APPROVED'
                   AND e.effective_date IS NULL
               )
               OR (
                   e.approval_status = 'PENDING'
                   AND e.effective_date IS NOT NULL
               )
               OR e.approval_status NOT IN (
                   'APPROVED', 'PENDING'
               )
            """
        ),

        (
            "Approved alternative sourcing references",
            """
            SELECT COUNT(*)
            FROM core.approved_alternates a
            LEFT JOIN core.part_master p
                ON a.part_id = p.part_id
            LEFT JOIN core.suppliers s
                ON a.alternate_supplier_id = s.supplier_id
            WHERE p.part_id IS NULL
               OR s.supplier_id IS NULL
               OR a.primary_supplier_id IS DISTINCT FROM
                  p.primary_supplier_id
               OR a.approved_revision IS DISTINCT FROM p.revision
               OR a.alternate_supplier_id =
                  a.primary_supplier_id
               OR a.approval_status <> 'APPROVED'
               OR a.quoted_lead_time_days IS NULL
               OR a.quoted_lead_time_days <= 0
               OR a.quoted_unit_cost_usd IS NULL
               OR a.quoted_unit_cost_usd <= 0
               OR a.max_available_qty IS NULL
               OR a.max_available_qty <= 0
            """
        ),

        (
            "Disruption scenario target references",
            """
            SELECT COUNT(*)
            FROM core.disruption_scenarios d
            LEFT JOIN core.purchase_orders po
                ON d.target_type = 'PURCHASE_ORDER'
               AND d.target_id = po.purchase_order_id
            LEFT JOIN core.inventory i
                ON d.target_type = 'INVENTORY_RECORD'
               AND d.target_id = i.inventory_record_id
            LEFT JOIN core.production_orders o
                ON d.target_type = 'PRODUCTION_ORDER'
               AND d.target_id = o.production_order_id
            LEFT JOIN core.engineering_changes e
                ON d.target_type = 'ENGINEERING_CHANGE'
               AND d.target_id = e.change_id
            WHERE (
                d.target_type = 'PURCHASE_ORDER'
                AND po.purchase_order_id IS NULL
            )
            OR (
                d.target_type = 'INVENTORY_RECORD'
                AND i.inventory_record_id IS NULL
            )
            OR (
                d.target_type = 'PRODUCTION_ORDER'
                AND o.production_order_id IS NULL
            )
            OR (
                d.target_type = 'ENGINEERING_CHANGE'
                AND e.change_id IS NULL
            )
            OR d.target_type IS NULL
            OR d.target_type NOT IN (
                'PURCHASE_ORDER',
                'INVENTORY_RECORD',
                'PRODUCTION_ORDER',
                'ENGINEERING_CHANGE'
            )
            """
        ),

    ])

    return checks


# ------------------------------------------------------------
# 3. Validate Core Table Count
# ------------------------------------------------------------

def validate_core_tables(con):
    result = con.execute("""
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = 'core'
          AND table_type = 'BASE TABLE'
    """).fetchone()[0]

    if result != EXPECTED_TABLES:
        raise AssertionError(
            f"Expected {EXPECTED_TABLES} core tables, "
            f"found {result}"
        )

    print(f"Core manufacturing tables: {result}")


# ------------------------------------------------------------
# 4. Run Integrity Checks
# ------------------------------------------------------------

def run_integrity_checks(con):
    checks = build_validation_checks()
    failures = []

    print("\nManufacturing integrity checks:\n")

    for name, query in checks:
        issue_count = con.execute(query).fetchone()[0]

        if issue_count == 0:
            print(f"[PASS] {name}")
        else:
            print(
                f"[FAIL] {name}: "
                f"{issue_count} issue(s)"
            )
            failures.append((name, issue_count))

    if failures:
        print("\nValidation failures:")

        for name, count in failures:
            print(f" - {name}: {count}")

        raise AssertionError(
            "SQL02 manufacturing integrity validation failed."
        )

    print("\nSQL02 validation: PASSED")
    print(f"Integrity checks passed: {len(checks)}")


# ------------------------------------------------------------
# 5. Main Execution
# ------------------------------------------------------------

def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(
            "Manufacturing database missing. "
            "Run SQL01 first."
        )

    if not SQL_PATH.exists():
        raise FileNotFoundError(
            "SQL02 file missing: "
            "sql/02_data_integrity_checks.sql"
        )

    sql = SQL_PATH.read_text(encoding="utf-8")

    # Ensure the full SQL02 script was saved.
    required_statements = [
        "CREATE SCHEMA IF NOT EXISTS core",
        "core.product_families",
        "core.disruption_scenarios",
        "COMMIT;",
    ]

    for statement in required_statements:
        if statement.lower() not in sql.lower():
            raise ValueError(
                "SQL02 file is incomplete. Missing: "
                f"{statement}"
            )

    con = duckdb.connect(str(DB_PATH))

    try:
        print("Starting SQL02 manufacturing validation...")

        print("\nCreating typed manufacturing tables...")
        con.execute(sql)

        validate_core_tables(con)
        run_integrity_checks(con)

        print("\nPhase 2 / SQL02 completed successfully.")
        print(f"Database: {DB_PATH.name}")

    finally:
        con.close()


if __name__ == "__main__":
    main()
