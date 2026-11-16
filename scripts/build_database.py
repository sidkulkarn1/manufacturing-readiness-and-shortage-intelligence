
from pathlib import Path
import os
import duckdb


ROOT = Path(__file__).resolve().parents[1]
DB_DIR = ROOT / "data" / "processed"
DB_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DB_DIR / "manufacturing_readiness.duckdb"
SQL_PATH = ROOT / "sql" / "01_create_schema.sql"

TABLES = [
    "product_families",
    "suppliers",
    "part_master",
    "bom_structure",
    "production_orders",
    "inventory",
    "inventory_allocations",
    "purchase_orders",
    "engineering_changes",
    "approved_alternates",
    "disruption_scenarios",
]

EXPECTED_COUNTS = {
    "product_families": 4,
    "suppliers": 8,
    "part_master": 428,
    "bom_structure": 496,
    "production_orders": 30,
    "inventory": 800,
    "engineering_changes": 12,
    "approved_alternates": 40,
    "disruption_scenarios": 5,
}


def main():
    # SQL CSV paths are relative to the repository root.
    os.chdir(ROOT)

    if not SQL_PATH.exists():
        raise FileNotFoundError(SQL_PATH)

    con = duckdb.connect(str(DB_PATH))

    try:
        print("Starting SQL01 manufacturing database build...")

        sql = SQL_PATH.read_text(encoding="utf-8")
        con.execute(sql)

        print("\nManufacturing tables loaded:\n")

        for table in TABLES:
            count = con.execute(
                f"SELECT COUNT(*) FROM raw.{table}"
            ).fetchone()[0]

            if table in EXPECTED_COUNTS:
                assert count == EXPECTED_COUNTS[table], (
                    f"{table}: expected "
                    f"{EXPECTED_COUNTS[table]}, found {count}"
                )
            else:
                assert count > 0, (
                    f"{table}: no source records imported"
                )

            print(f"{table:<25} {count:>6} records")

        table_count = con.execute("""
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = 'raw'
              AND table_type = 'BASE TABLE'
        """).fetchone()[0]

        assert table_count == len(TABLES)

        print("\nSQL01 validation: PASSED")
        print(f"Raw tables: {table_count}")
        print(f"Database: {DB_PATH.name}")

    finally:
        con.close()


if __name__ == "__main__":
    main()
