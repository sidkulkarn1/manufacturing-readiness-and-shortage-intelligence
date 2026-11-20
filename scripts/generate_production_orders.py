
from pathlib import Path
from datetime import date, timedelta
from collections import Counter
import csv
import random

# ============================================================
# Production Orders & Schedule
# ============================================================

SEED = 2029
rng = random.Random(SEED)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"

PLANNING_START = date(2027, 1, 4)
PLANNING_WEEKS = 8
ORDER_COUNT = 30


# ------------------------------------------------------------
# 1. Load Manufacturing Master Data
# ------------------------------------------------------------

def load_csv(filename):
    path = RAW_DIR / filename

    if not path.exists():
        raise FileNotFoundError(
            f"Missing {filename}. Run the previous generator first."
        )

    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_finished_goods():
    parts = load_csv("part_master.csv")
    bom = load_csv("bom_structure.csv")

    finished_goods = sorted(
        [
            part for part in parts
            if part["part_type"] == "FINISHED_GOOD"
        ],
        key=lambda x: x["part_id"]
    )

    bom_parents = {
        line["parent_part_id"] for line in bom
    }

    assert len(finished_goods) == 4
    assert all(
        fg["part_id"] in bom_parents
        for fg in finished_goods
    )

    print("Manufacturing master data: VALIDATED")
    return finished_goods


# ------------------------------------------------------------
# 2. Generate Production Orders
# ------------------------------------------------------------

def generate_orders(finished_goods):
    orders = []

    for i in range(ORDER_COUNT):

        # Distribute 30 orders across 8 planning weeks.
        week_index = i % PLANNING_WEEKS

        week_start = PLANNING_START + timedelta(
            weeks=week_index
        )

        # Start Monday or Tuesday; due Thursday or Friday.
        start_date = week_start + timedelta(
            days=rng.choice([0, 1])
        )

        due_date = week_start + timedelta(
            days=rng.choice([3, 4])
        )

        # Rotate orders across the four finished products.
        product = finished_goods[i % len(finished_goods)]

        quantity = rng.randint(2, 12)

        priority = rng.choices(
            ["HIGH", "MEDIUM", "LOW"],
            weights=[25, 50, 25],
            k=1
        )[0]

        orders.append({
            "production_order_id": f"MO-{i+1:04d}",
            "finished_good_id": product["part_id"],
            "finished_good_revision": product["revision"],
            "product_family_id": product["product_family_id"],
            "order_quantity": quantity,
            "planned_week": week_index + 1,
            "planned_start_date": start_date.isoformat(),
            "material_required_date": start_date.isoformat(),
            "planned_due_date": due_date.isoformat(),
            "priority": priority,
            "production_site_id": "PLANT-01",
            "order_status": "PLANNED",
        })

    return sorted(
        orders,
        key=lambda x: (
            x["planned_start_date"],
            x["production_order_id"]
        )
    )


# ------------------------------------------------------------
# 3. Validate Production Schedule
# ------------------------------------------------------------

def validate_orders(orders, finished_goods):

    valid_products = {
        fg["part_id"] for fg in finished_goods
    }

    order_ids = [
        order["production_order_id"] for order in orders
    ]

    assert len(orders) == ORDER_COUNT
    assert len(set(order_ids)) == ORDER_COUNT

    planning_end = PLANNING_START + timedelta(
        weeks=PLANNING_WEEKS
    )

    for order in orders:
        start = date.fromisoformat(
            order["planned_start_date"]
        )
        due = date.fromisoformat(
            order["planned_due_date"]
        )
        material_date = date.fromisoformat(
            order["material_required_date"]
        )

        assert order["finished_good_id"] in valid_products
        assert order["order_quantity"] > 0
        assert PLANNING_START <= start < planning_end
        assert start < due < planning_end
        assert material_date == start
        assert 1 <= order["planned_week"] <= 8
        assert order["priority"] in {
            "HIGH", "MEDIUM", "LOW"
        }

    assert {o["planned_week"] for o in orders} == set(
        range(1, 9)
    )

    assert {
        o["finished_good_id"] for o in orders
    } == valid_products

    print("Production schedule validation: PASSED")
    print(f"Production orders: {len(orders)}")
    print(f"Planning weeks: {PLANNING_WEEKS}")
    print(
        "Total planned finished units:",
        sum(o["order_quantity"] for o in orders)
    )

    weekly_counts = Counter(
        o["planned_week"] for o in orders
    )

    for week in sorted(weekly_counts):
        print(
            f"Week {week}: {weekly_counts[week]} orders"
        )


# ------------------------------------------------------------
# 4. Export Production Orders
# ------------------------------------------------------------

def export_orders(orders):
    output = RAW_DIR / "production_orders.csv"

    with output.open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(orders[0].keys())
        )
        writer.writeheader()
        writer.writerows(orders)

    print(f"Created: {output.name}")


# ------------------------------------------------------------
# 5. Main Execution
# ------------------------------------------------------------

def main():
    finished_goods = load_finished_goods()

    orders = generate_orders(finished_goods)

    validate_orders(orders, finished_goods)

    export_orders(orders)


if __name__ == "__main__":
    main()
