
from pathlib import Path
from collections import defaultdict, Counter
from datetime import date, timedelta
import csv
import json
import random

# ============================================================
# Phase 1 / Step 4: Inventory, Allocations & Purchase Orders
# ============================================================

SEED = 2030
rng = random.Random(SEED)

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

SNAPSHOT = date(2027, 1, 4)
LOCATIONS = ["STOCK-01", "STOCK-02"]


# ------------------------------------------------------------
# 1. Load Existing Manufacturing Data
# ------------------------------------------------------------

def load_csv(filename):
    path = RAW / filename

    if not path.exists():
        raise FileNotFoundError(
            f"Missing {filename}. Run the earlier generators first."
        )

    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(filename, rows):
    if not rows:
        raise ValueError(f"No records generated for {filename}")

    path = RAW / filename

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Created {filename}: {len(rows)} records")


# ------------------------------------------------------------
# 2. Calculate Component Demand From the BOM
# ------------------------------------------------------------

def calculate_requirements(parts, bom, orders):
    part_lookup = {p["part_id"]: p for p in parts}
    children = defaultdict(list)

    for line in bom:
        parent = line["parent_part_id"]
        child = line["component_part_id"]

        if parent not in part_lookup or child not in part_lookup:
            raise ValueError("Invalid BOM part reference")

        if (
            line["parent_revision"] != part_lookup[parent]["revision"]
            or line["component_revision"] != part_lookup[child]["revision"]
        ):
            raise ValueError("BOM revision mismatch")

        children[parent].append(
            (child, int(line["quantity_per_parent"]))
        )

    requirements = Counter()

    for order in orders:
        order_id = order["production_order_id"]
        fg_id = order["finished_good_id"]
        fg_qty = int(order["order_quantity"])

        stack = [(fg_id, fg_qty, frozenset())]

        while stack:
            part_id, quantity, ancestors = stack.pop()

            if part_id in ancestors:
                raise ValueError(f"Cyclic BOM detected: {part_id}")

            part = part_lookup[part_id]

            if part["part_type"] == "PURCHASED_COMPONENT":
                requirements[(order_id, part_id)] += quantity
                continue

            if part_id not in children:
                raise ValueError(f"Missing BOM children: {part_id}")

            for child_id, qty_per in children[part_id]:
                if qty_per <= 0:
                    raise ValueError("BOM quantities must be positive")

                stack.append((
                    child_id,
                    quantity * qty_per,
                    ancestors | {part_id},
                ))

    return requirements


# ------------------------------------------------------------
# 3. Generate Inventory and Quality Holds
# ------------------------------------------------------------

def generate_inventory(purchased, total_demand):
    inventory = []
    usable_by_part = {}

    for part in purchased:
        pid = part["part_id"]
        demand = total_demand[pid]

        # Simulate different inventory coverage levels.
        coverage = rng.choice([0.25, 0.50, 0.75, 1.10])
        total_stock = round(demand * coverage)

        # Some components have material on quality hold.
        hold_qty = 0

        if total_stock > 0 and rng.random() < 0.25:
            hold_qty = round(
                total_stock * rng.uniform(0.05, 0.20)
            )

        first_stock = round(
            total_stock * rng.uniform(0.55, 0.85)
        )
        second_stock = total_stock - first_stock

        first_hold = min(
            first_stock,
            round(hold_qty * first_stock / max(total_stock, 1))
        )
        second_hold = hold_qty - first_hold

        balances = [
            (first_stock, first_hold),
            (second_stock, second_hold),
        ]

        usable_by_part[pid] = total_stock - hold_qty

        for index, (stock, held) in enumerate(balances):
            inventory.append({
                "inventory_record_id": (
                    f"INV-{len(inventory) + 1:05d}"
                ),
                "part_id": pid,
                "revision": part["revision"],
                "location_id": LOCATIONS[index],
                "snapshot_date": SNAPSHOT.isoformat(),
                "on_hand_qty": stock,
                "quality_hold_qty": held,
            })

    return inventory, usable_by_part


# ------------------------------------------------------------
# 4. Generate Existing Production Allocations
# ------------------------------------------------------------

def generate_allocations(inventory, requirements, orders):
    allocations = []

    order_lookup = {
        o["production_order_id"]: o for o in orders
    }

    needs_by_part = defaultdict(list)

    for (order_id, part_id), qty in requirements.items():
        needs_by_part[part_id].append((order_id, qty))

    remaining = {}

    for row in inventory:
        key = (row["part_id"], row["location_id"])
        remaining[key] = (
            row["on_hand_qty"] - row["quality_hold_qty"]
        )

    priority_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

    for part_id, needs in sorted(needs_by_part.items()):

        needs.sort(key=lambda item: (
            priority_rank[order_lookup[item[0]]["priority"]],
            order_lookup[item[0]]["material_required_date"],
            item[0],
        ))

        # Reserve some stock for up to two competing builds.
        for order_id, required_qty in needs[:2]:
            target = max(
                1, round(required_qty * rng.uniform(0.20, 0.60))
            )

            target = min(target, required_qty)

            for location in LOCATIONS:
                key = (part_id, location)
                assigned = min(target, remaining[key])

                if assigned <= 0:
                    continue

                allocations.append({
                    "allocation_id": (
                        f"ALLOC-{len(allocations) + 1:05d}"
                    ),
                    "production_order_id": order_id,
                    "part_id": part_id,
                    "revision": "A",
                    "location_id": location,
                    "allocated_qty": assigned,
                    "allocation_date": SNAPSHOT.isoformat(),
                })

                remaining[key] -= assigned
                target -= assigned

                if target == 0:
                    break

    return allocations


# ------------------------------------------------------------
# 5. Generate Supplier Purchase Orders
# ------------------------------------------------------------

def generate_purchase_orders(purchased, total_demand, usable):
    purchase_orders = []

    for part in purchased:
        pid = part["part_id"]

        shortage_vs_horizon = max(
            0, total_demand[pid] - usable[pid]
        )

        # Not every component has a replenishment commitment.
        if shortage_vs_horizon == 0 or rng.random() < 0.15:
            continue

        ordered_qty = max(
            1,
            round(
                shortage_vs_horizon * rng.uniform(0.60, 1.20)
            )
        )

        lead_time = int(part["lead_time_days"])

        # Orders already placed by the planning snapshot.
        days_since_order = rng.randint(0, lead_time - 1)
        order_date = SNAPSHOT - timedelta(
            days=days_since_order
        )

        promised = order_date + timedelta(days=lead_time)

        # Simulate supplier delivery delays.
        delay_days = (
            rng.randint(5, 21)
            if rng.random() < 0.25
            else 0
        )

        expected = promised + timedelta(days=delay_days)

        purchase_orders.append({
            "purchase_order_id": (
                f"PO-{len(purchase_orders) + 1:05d}"
            ),
            "part_id": pid,
            "revision": part["revision"],
            "supplier_id": part["primary_supplier_id"],
            "ordered_qty": ordered_qty,
            "order_date": order_date.isoformat(),
            "original_promised_date": promised.isoformat(),
            "expected_receipt_date": expected.isoformat(),
            "delay_days": delay_days,
            "receiving_location_id": "STOCK-01",
            "unit_cost_usd": part["unit_cost_usd"],
            "order_status": "OPEN",
        })

    return purchase_orders


# ------------------------------------------------------------
# 6. Validate Generated Supply Data
# ------------------------------------------------------------

def validate_supply(
    purchased, requirements, inventory, allocations, purchase_orders
):
    purchased_lookup = {p["part_id"]: p for p in purchased}

    assert len(purchased) == 400
    assert len(inventory) == 800

    usable_by_location = {}

    for row in inventory:
        assert row["part_id"] in purchased_lookup
        assert row["revision"] == purchased_lookup[
            row["part_id"]
        ]["revision"]

        on_hand = row["on_hand_qty"]
        held = row["quality_hold_qty"]

        assert 0 <= held <= on_hand
        assert row["location_id"] in LOCATIONS

        key = (row["part_id"], row["location_id"])
        assert key not in usable_by_location
        usable_by_location[key] = on_hand - held

    allocated_by_location = Counter()
    allocated_by_order = Counter()

    for row in allocations:
        key = (row["part_id"], row["location_id"])
        order_key = (
            row["production_order_id"], row["part_id"]
        )

        assert row["allocated_qty"] > 0
        assert row["revision"] == purchased_lookup[
            row["part_id"]
        ]["revision"]
        assert order_key in requirements

        allocated_by_location[key] += row["allocated_qty"]
        allocated_by_order[order_key] += row["allocated_qty"]

    for key, qty in allocated_by_location.items():
        assert qty <= usable_by_location[key], (
            f"Inventory overallocated: {key}"
        )

    for key, qty in allocated_by_order.items():
        assert qty <= requirements[key], (
            f"Order overallocated: {key}"
        )

    for po in purchase_orders:
        part = purchased_lookup[po["part_id"]]

        ordered = date.fromisoformat(po["order_date"])
        promised = date.fromisoformat(
            po["original_promised_date"]
        )
        expected = date.fromisoformat(
            po["expected_receipt_date"]
        )

        assert po["supplier_id"] == part["primary_supplier_id"]
        assert po["revision"] == part["revision"]
        assert po["ordered_qty"] > 0
        assert ordered <= SNAPSHOT < promised
        assert (promised - ordered).days == int(
            part["lead_time_days"]
        )
        assert expected >= promised
        assert (expected - promised).days == po["delay_days"]

    print("Supply data validation: PASSED")
    print(f"Inventory records: {len(inventory)}")
    print(f"Allocation records: {len(allocations)}")
    print(f"Open purchase orders: {len(purchase_orders)}")
    print(
        "Delayed supplier orders:",
        sum(po["delay_days"] > 0 for po in purchase_orders)
    )


# ------------------------------------------------------------
# 7. Main
# ------------------------------------------------------------

def main():
    parts = load_csv("part_master.csv")
    bom = load_csv("bom_structure.csv")
    orders = load_csv("production_orders.csv")

    purchased = sorted(
        [
            p for p in parts
            if p["part_type"] == "PURCHASED_COMPONENT"
        ],
        key=lambda x: x["part_id"]
    )

    requirements = calculate_requirements(
        parts, bom, orders
    )

    total_demand = Counter()

    for (_, part_id), qty in requirements.items():
        total_demand[part_id] += qty

    assert len(total_demand) == 400
    assert all(qty > 0 for qty in total_demand.values())

    inventory, usable = generate_inventory(
        purchased, total_demand
    )

    allocations = generate_allocations(
        inventory, requirements, orders
    )

    purchase_orders = generate_purchase_orders(
        purchased, total_demand, usable
    )

    validate_supply(
        purchased,
        requirements,
        inventory,
        allocations,
        purchase_orders,
    )

    write_csv("inventory.csv", inventory)
    write_csv("inventory_allocations.csv", allocations)
    write_csv("purchase_orders.csv", purchase_orders)

    manifest = {
        "data_type": "SYNTHETIC",
        "random_seed": SEED,
        "snapshot_date": SNAPSHOT.isoformat(),
        "inventory_locations": LOCATIONS,
        "inventory_records": len(inventory),
        "allocation_records": len(allocations),
        "purchase_order_records": len(purchase_orders),
        "modeling_notes": [
            "On-hand inventory includes quality-held units.",
            "Reservations are part of on-hand stock, not additional stock.",
            "Both storage locations are within one production site.",
            "Purchase orders are open at the planning snapshot.",
            "Supplier delays and costs are simulated.",
            "Supply quantities use full-horizon gross BOM demand.",
            "Time-phased netting will be performed in the MRP engine.",
        ],
    }

    with (RAW / "supply_manifest.json").open(
        "w", encoding="utf-8"
    ) as f:
        json.dump(manifest, f, indent=2)

    print("Created supply_manifest.json")
    print("\nPhase 1 / Step 4 completed successfully.")


if __name__ == "__main__":
    main()
