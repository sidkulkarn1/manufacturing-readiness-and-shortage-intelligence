
from pathlib import Path
import csv
import duckdb

ROOT = Path(__file__).resolve().parents[1]

DB_PATH = (
    ROOT / "data" / "processed"
    / "manufacturing_readiness.duckdb"
)

SQL_PATH = ROOT / "sql" / "08_dashboard_reporting.sql"

EXPORT_DIR = ROOT / "data" / "reporting"

EXPORTS = [
    "readiness_orders",
    "weekly_readiness",
    "shortage_detail",
    "supplier_risk",
    "production_recovery",
    "recovery_comparison",
    "action_screening",
    "executive_kpis",
    "family_summary",
    "shortage_priority",
]


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
        raise FileNotFoundError("SQL08 file missing.")

    sql = SQL_PATH.read_text(encoding="utf-8")

    if "CREATE OR REPLACE VIEW" not in sql:
        raise ValueError("SQL08 file is incomplete.")

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(DB_PATH))

    try:
        print("Running SQL08 dashboard reporting...")
        con.execute(sql)

        print("\nValidating reporting layer:\n")

        check_zero(
            con,
            "Exactly 30 production orders",
            """
            SELECT ABS(
                COUNT(DISTINCT production_order_id) - 30
            )
            FROM reporting.readiness_orders
            """
        )

        check_zero(
            con,
            "Eight planning weeks",
            """
            SELECT ABS(COUNT(*) - 8)
            FROM reporting.weekly_readiness
            """
        )

        check_zero(
            con,
            "Readiness statuses reconcile",
            """
            SELECT COUNT(*)
            FROM reporting.executive_kpis
            WHERE ready_orders + at_risk_orders
                  + blocked_orders
                  <> total_production_orders
            """
        )

        check_zero(
            con,
            "Shortage exception counts reconcile",
            """
            SELECT ABS(
                (SELECT COUNT(*)
                 FROM reporting.shortage_detail)
                -
                (SELECT shortage_exception_lines
                 FROM planning.shortage_kpis)
            )
            """
        )

        check_zero(
            con,
            "Supplier shortage units reconcile",
            """
            SELECT ABS(
                (SELECT SUM(total_shortage_units)
                 FROM reporting.supplier_risk)
                -
                (SELECT total_shortage_units
                 FROM planning.shortage_kpis)
            )
            """
        )

        check_zero(
            con,
            "Production recovery covers 30 orders",
            """
            SELECT ABS(COUNT(*) - 30)
            FROM reporting.production_recovery
            """
        )

        check_zero(
            con,
            "Four procurement scenarios reported",
            """
            SELECT ABS(
                COUNT(DISTINCT scenario_id) - 4
            )
            FROM reporting.recovery_comparison
            """
        )

        check_zero(
            con,
            "Targeted recovery KPI reconciliation",
            """
            SELECT COUNT(*)
            FROM reporting.executive_kpis e
            JOIN planning.targeted_expediting_kpis t
                ON TRUE
            WHERE e.targeted_delay_days <>
                  t.targeted_delay_days
               OR e.delay_days_reduced <>
                  t.delay_days_reduced
               OR e.expedited_lines <>
                  t.expedited_lines
            """
        )

        check_zero(
            con,
            "Two operational screening actions",
            """
            SELECT ABS(COUNT(*) - 2)
            FROM reporting.action_screening
            """
        )

        check_zero(
            con,
            "Four product families",
            """
            SELECT ABS(COUNT(*) - 4)
            FROM reporting.family_summary
            """
        )

        print("\nExporting Tableau datasets:\n")

        for name in EXPORTS:
            row_count = con.execute(
                f"SELECT COUNT(*) FROM reporting.{name}"
            ).fetchone()[0]

            output_path = EXPORT_DIR / f"{name}.csv"

            # Escape apostrophes for a SQL string literal.
            destination = str(output_path).replace("'", "''")

            con.execute(f"""
                COPY (
                    SELECT * FROM reporting.{name}
                )
                TO '{destination}'
                (FORMAT CSV, HEADER TRUE)
            """)

            if not output_path.exists():
                raise AssertionError(
                    f"Export missing: {output_path}"
                )

            with output_path.open(
                "r", newline="", encoding="utf-8"
            ) as f:
                reader = csv.reader(f)
                header = next(reader, None)
                exported_count = sum(1 for _ in reader)

            if not header:
                raise AssertionError(
                    f"Missing CSV header: {name}"
                )

            if exported_count != row_count:
                raise AssertionError(
                    f"{name}: database count {row_count}, "
                    f"CSV count {exported_count}"
                )

            print(
                f"[PASS] {name}.csv "
                f"({exported_count} rows)"
            )

        kpis = con.execute("""
            SELECT
                total_production_orders,
                ready_orders,
                at_risk_orders,
                blocked_orders,
                readiness_rate_pct,
                total_shortage_units,
                standard_reference_delay_days,
                targeted_delay_days,
                delay_days_reduced,
                targeted_additional_spend_usd,
                savings_vs_expedite_all_usd
            FROM reporting.executive_kpis
        """).fetchone()

        print("\nEXECUTIVE REPORTING SUMMARY")
        print("-" * 55)

        labels = [
            "Production orders",
            "Material ready",
            "At risk",
            "Blocked",
            "Readiness rate (%)",
            "Missing component units",
            "Standard reference delay days",
            "Targeted delay days",
            "Delay days reduced",
            "Targeted additional spend ($)",
            "Savings vs full expediting ($)",
        ]

        for label, value in zip(labels, kpis):
            print(f"{label}: {value}")

        print("\nSQL08 validation: PASSED")
        print("Reporting checks passed: 10")
        print(f"CSV exports verified: {len(EXPORTS)}")
        print(f"Export folder: {EXPORT_DIR}")

    finally:
        con.close()


if __name__ == "__main__":
    main()
