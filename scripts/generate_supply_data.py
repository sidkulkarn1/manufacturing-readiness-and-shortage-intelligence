
from pathlib import Path
from collections import Counter, defaultdict
from datetime import date, timedelta
import csv
import json
import random

SEED = 2032
rng = random.Random(SEED)

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

SNAPSHOT = date(2027, 1, 4)
LOCATIONS = ["STOCK-01", "STOCK-02"]

# Synthetic operating conditions, not actual KPI results.
READY_DESIGN_COUNT = 10
INBOUND_DESIGN_COUNT = 8
BLOCKED_DESIGN_COUNT = 12

PRIORITY_RANK = {
    "HIGH": 1,
    "MEDIUM": 2,
    "LOW": 3,
}


# ------------------------------------------------------------
# 1. File Utilities
# ------------------------------------------------------------

def load_csv(filename):
    path = RAW / filename

    if not path.exists():
        raise FileNotFoundError(
            f"Missing {filename}. Run earlier generators first."
        )

    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(filename, rows):
    if not rows:
        raise ValueError(f"No records for {filename}")

    path = RAW / filename

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Created {filename}: {len(rows)} records")


# ------------------------------------------------------------
# 2. Calculate Multi-Level BOM Requirements
# ------------------------------------------------------------

def calculate_requirements(parts, bom, orders):
    lookup = {p["part_id"]: p for p in parts}
    children = defaultdict(list)

    for line in bom:
        parent = line["parent_part_id"]
        child = line["component_part_id"]

        assert parent in lookup
        assert child in lookup

        assert line["parent_revision"] == lookup[parent]["revision"]
        assert line["component_revision"] == lookup[child]["revision"]

        children[parent].append(line)

    requirements = Counter()

    for order in orders:
        order_id = order["production_order_id"]
        required_date = date.fromisoformat(
            order["material_required_date"]
        )

        stack = [
            (
                order["finished_good_id"],
                int(order["order_quantity"]),
                frozenset(),
            )
        ]

        while stack:
            part_id, quantity, ancestors = stack.pop()

            if part_id in ancestors:
                raise ValueError(f"Cyclic BOM: {part_id}")

            part = lookup[part_id]

            if part["part_type"] == "PURCHASED_COMPONENT":
                requirements[(order_id, part_id)] += quantity
                continue

            if part_id not in children:
                raise ValueError(f"Missing BOM: {part_id}")

            valid_children = 0

            for line in children[part_id]:
                start = date.fromisoformat(
                    line["effective_start_date"]
                )

                end_value = line["effective_end_date"]
                end = (
                    date.fromisoformat(end_value)
                    if end_value else None
                )

                if required_date < start:
                    continue

                if end and required_date > end:
                    continue

                child_id = line["component_part_id"]
                qty_per = int(line["quantity_per_parent"])

                if qty_per <= 0:
                    raise ValueError("Invalid BOM quantity")

                stack.append((
                    child_id,
                    quantity * qty_per,
                    ancestors | {part_id},
                ))

                valid_children += 1

            if valid_children == 0:
                raise ValueError(
                    f"No effective BOM lines for {part_id}"
                )

    return requirements


# ------------------------------------------------------------
# 3. Define Controlled Manufacturing Conditions
# ------------------------------------------------------------

def define_supply_conditions(orders, purchased):
    ordered = sorted(
        orders,
        key=lambda o: (
            o["material_required_date"],
            PRIORITY_RANK[o["priority"]],
            o["production_order_id"],
        ),
    )

    assert len(ordered) == 30

    ready_ids = {
        o["production_order_id"]
        for o in ordered[:READY_DESIGN_COUNT]
    }

    inbound_ids = {
        o["production_order_id"]
        for o in ordered[
            READY_DESIGN_COUNT:
            READY_DESIGN_COUNT + INBOUND_DESIGN_COUNT
        ]
    }

    blocked_ids = {
        o["production_order_id"]
        for o in ordered[
            READY_DESIGN_COUNT + INBOUND_DESIGN_COUNT:
        ]
    }

    assert len(blocked_ids) == BLOCKED_DESIGN_COUNT

    by_family = defaultdict(list)

    for part in purchased:
        by_family[part["product_family_id"]].append(
            part["part_id"]
        )

    critical_parts = set()

    # Three critical bottleneck components per family.
    for family_id in sorted(by_family):
        candidates = sorted(by_family[family_id])

        critical_parts.update(
            rng.sample(candidates, 3)
        )

    assert len(critical_parts) == 12

    return (
        ordered,
        ready_ids,
        inbound_ids,
        blocked_ids,
        critical_parts,
    )


# ------------------------------------------------------------
# 4. Generate Inventory With Quality Holds
# ------------------------------------------------------------

def generate_inventory(
    purchased, ordered, requirements, ready_ids
):
    inventory = []
    usable_by_location = {}

    for part in purchased:
        pid = part["part_id"]

        # Initial usable stock covers the designated
        # stock-ready production requirements.
        ready_demand = sum(
            requirements.get(
                (o["production_order_id"], pid), 0
            )
            for o in ordered
            if o["production_order_id"] in ready_ids
        )

        # Quality-held quantities are additional
        # physical stock, not usable stock.
        hold_qty = 0

        if rng.random() < 0.20:
            hold_qty = max(
                1,
                round(
                    ready_demand
                    * rng.uniform(0.05, 0.12)
                )
            )

        first_usable = round(
            ready_demand * rng.uniform(0.55, 0.80)
        )

        second_usable = ready_demand - first_usable

        first_hold = hold_qty // 2
        second_hold = hold_qty - first_hold

        balances = [
            (first_usable, first_hold),
            (second_usable, second_hold),
        ]

        for index, (usable, held) in enumerate(balances):
            location = LOCATIONS[index]

            usable_by_location[(pid, location)] = usable

            inventory.append({
                "inventory_record_id":
                    f"INV-{len(inventory) + 1:05d}",
                "part_id": pid,
                "revision": part["revision"],
                "location_id": location,
                "snapshot_date": SNAPSHOT.isoformat(),
                "on_hand_qty": usable + held,
                "quality_hold_qty": held,
            })

    return inventory, usable_by_location


# ------------------------------------------------------------
# 5. Generate Protected Production Reservations
# ------------------------------------------------------------

def generate_allocations(
    purchased, ordered, requirements,
    ready_ids, usable_by_location
):
    allocations = []
    remaining = usable_by_location.copy()

    for part in purchased:
        pid = part["part_id"]

        for order in ordered:
            oid = order["production_order_id"]

            if oid not in ready_ids:
                continue

            required = requirements.get((oid, pid), 0)

            if required <= 0:
                continue

            target = min(
                required,
                max(
                    1,
                    round(
                        required
                        * rng.uniform(0.20, 0.40)
                    )
                )
            )

            for location in LOCATIONS:
                key = (pid, location)

                assigned = min(
                    target,
                    remaining[key]
                )

                if assigned <= 0:
                    continue

                allocations.append({
                    "allocation_id":
                        f"ALLOC-{len(allocations) + 1:05d}",
                    "production_order_id": oid,
                    "part_id": pid,
                    "revision": part["revision"],
                    "location_id": location,
                    "allocated_qty": assigned,
                    "allocation_date": SNAPSHOT.isoformat(),
                })

                remaining[key] -= assigned
                target -= assigned

                if target == 0:
                    break

            assert target == 0, (
                f"Insufficient reservation stock: {oid}, {pid}"
            )

    return allocations


# ------------------------------------------------------------
# 6. Generate Time-Phased Supplier Purchase Orders
# ------------------------------------------------------------

def generate_purchase_orders(
    purchased, ordered, requirements,
    ready_ids, inbound_ids, critical_parts
):
    purchase_orders = []

    for part in purchased:
        pid = part["part_id"]

        inbound_needs = [
            o for o in ordered
            if (
                o["production_order_id"] in inbound_ids
                and requirements.get(
                    (o["production_order_id"], pid), 0
                ) > 0
            )
        ]

        if not inbound_needs:
            continue

        # Noncritical parts receive enough replenishment
        # for later planned orders as well.
        #
        # Critical parts receive replenishment only for
        # the inbound-dependent group. Later demand for
        # these components remains exposed to shortages.

        eligible_ids = (
            inbound_ids
            if pid in critical_parts
            else {
                o["production_order_id"]
                for o in ordered
                if o["production_order_id"] not in ready_ids
            }
        )

        ordered_qty = sum(
            requirements.get(
                (o["production_order_id"], pid), 0
            )
            for o in ordered
            if o["production_order_id"] in eligible_ids
        )

        if ordered_qty <= 0:
            continue

        first_needed = min(
            date.fromisoformat(
                o["material_required_date"]
            )
            for o in inbound_needs
        )

        lead_time = int(part["lead_time_days"])

        # Some suppliers experience manageable delays,
        # while deliveries still arrive before the first
        # inbound-dependent material requirement.
        delay_days = (
            rng.randint(2, 5)
            if rng.random() < 0.20
            else 0
        )

        # Purchase orders must have been placed by
        # the planning snapshot.
        promised = min(
            first_needed - timedelta(days=delay_days),
            SNAPSHOT + timedelta(days=lead_time)
        )

        order_date = promised - timedelta(days=lead_time)
        expected = promised + timedelta(days=delay_days)

        assert order_date <= SNAPSHOT
        assert promised > SNAPSHOT
        assert expected <= first_needed

        purchase_orders.append({
            "purchase_order_id":
                f"PO-{len(purchase_orders) + 1:05d}",
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
# 7. Validate Supply Data
# ------------------------------------------------------------

def validate_supply(
    purchased, orders, requirements,
    inventory, allocations, purchase_orders,
    critical_parts
):
    assert len(purchased) == 400
    assert len(orders) == 30
    assert len(requirements) == 3000
    assert len(inventory) == 800
    assert len(critical_parts) == 12

    parts = {p["part_id"]: p for p in purchased}
    order_ids = {
        o["production_order_id"] for o in orders
    }

    usable = {}

    for row in inventory:
        assert row["part_id"] in parts

        stock = row["on_hand_qty"]
        hold = row["quality_hold_qty"]

        assert 0 <= hold <= stock

        key = (
            row["part_id"],
            row["location_id"]
        )

        assert key not in usable

        usable[key] = stock - hold

    by_location = Counter()
    by_order = Counter()

    for row in allocations:
        pid = row["part_id"]
        oid = row["production_order_id"]
        location = row["location_id"]
        qty = row["allocated_qty"]

        assert oid in order_ids
        assert pid in parts
        assert qty > 0
        assert row["revision"] == parts[pid]["revision"]

        by_location[(pid, location)] += qty
        by_order[(oid, pid)] += qty

    for key, qty in by_location.items():
        assert qty <= usable[key], (
            f"Double allocation detected: {key}"
        )

    for key, qty in by_order.items():
        assert qty <= requirements[key], (
            f"Overreserved production demand: {key}"
        )

    for po in purchase_orders:
        part = parts[po["part_id"]]

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
        assert expected >= promised

        assert (promised - ordered).days == int(
            part["lead_time_days"]
        )

        assert (expected - promised).days == po["delay_days"]

    print("Supply data validation: PASSED")
    print(f"Inventory records: {len(inventory)}")
    print(f"Allocation records: {len(allocations)}")
    print(f"Purchase orders: {len(purchase_orders)}")
    print(f"Critical bottleneck parts: {len(critical_parts)}")


# ------------------------------------------------------------
# 8. Main Execution
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
        key=lambda p: p["part_id"]
    )

    requirements = calculate_requirements(
        parts, bom, orders
    )

    (
        ordered,
        ready_ids,
        inbound_ids,
        blocked_ids,
        critical_parts,
    ) = define_supply_conditions(orders, purchased)

    inventory, usable = generate_inventory(
        purchased, ordered, requirements, ready_ids
    )

    allocations = generate_allocations(
        purchased, ordered, requirements,
        ready_ids, usable
    )

    purchase_orders = generate_purchase_orders(
        purchased, ordered, requirements,
        ready_ids, inbound_ids, critical_parts
    )

    validate_supply(
        purchased, orders, requirements,
        inventory, allocations, purchase_orders,
        critical_parts
    )

    write_csv("inventory.csv", inventory)
    write_csv("inventory_allocations.csv", allocations)
    write_csv("purchase_orders.csv", purchase_orders)

    manifest = {
        "project": "Manufacturing Readiness & Shortage Intelligence",
        "data_type": "SYNTHETIC",
        "simulation_profile": "BALANCED_BASELINE_V2",
        "random_seed": SEED,
        "snapshot_date": SNAPSHOT.isoformat(),
        "design_groups": {
            "stock_coverage": len(ready_ids),
            "inbound_dependent": len(inbound_ids),
            "shortage_exposed": len(blocked_ids),
        },
        "critical_bottleneck_parts": sorted(critical_parts),
        "inventory_records": len(inventory),
        "allocation_records": len(allocations),
        "purchase_order_records": len(purchase_orders),
        "assumptions": [
            "Supply conditions are intentionally simulated.",
            "Existing reservations are protected.",
            "Quality-held materials are not usable.",
            "Open purchase orders are available on receipt date.",
            "Three critical components per family are constrained.",
            "No engineering revision substitution is assumed.",
            "Design groups are not calculated readiness outcomes.",
            "Recalibration is not a recovery improvement.",
        ],
    }

    with (
        RAW / "supply_manifest.json"
    ).open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print("Created supply_manifest.json")
    print("\nPhase 1 supply recalibration completed.")


if __name__ == "__main__":
    main()
