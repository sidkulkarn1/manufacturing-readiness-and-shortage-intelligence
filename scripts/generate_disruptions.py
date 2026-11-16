
from pathlib import Path
from datetime import date, timedelta
from collections import Counter, defaultdict
import csv
import json
import random

# ============================================================
# Phase 1 / Step 5: Engineering Changes & Disruptions
# ============================================================

SEED = 2031
rng = random.Random(SEED)

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

SNAPSHOT = date(2027, 1, 4)
HORIZON_END = SNAPSHOT + timedelta(weeks=8)


# ------------------------------------------------------------
# 1. Load and Export Data
# ------------------------------------------------------------

def load_csv(filename):
    path = RAW / filename

    if not path.exists():
        raise FileNotFoundError(
            f"Missing {filename}. Run earlier generators first."
        )

    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(filename, records):
    if not records:
        raise ValueError(f"No records generated for {filename}")

    path = RAW / filename

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=list(records[0].keys())
        )
        writer.writeheader()
        writer.writerows(records)

    print(f"Created {filename}: {len(records)} records")


# ------------------------------------------------------------
# 2. Generate Engineering Changes
# ------------------------------------------------------------

def generate_engineering_changes(parts, bom, orders):
    changes = []
    referenced = Counter(
        line["component_part_id"] for line in bom
    )

    family_components = defaultdict(list)

    for part in parts:
        if (
            part["part_type"] == "PURCHASED_COMPONENT"
            and part["part_id"] in referenced
        ):
            family_components[
                part["product_family_id"]
            ].append(part)

    reasons = [
        "DESIGN_IMPROVEMENT",
        "RELIABILITY_UPDATE",
        "QUALIFICATION_CHANGE",
        "OBSOLESCENCE_MITIGATION",
    ]

    for family_id in sorted(family_components):
        candidates = sorted(
            family_components[family_id],
            key=lambda p: p["part_id"]
        )

        selected = rng.sample(candidates, 3)

        # Choose effective dates with scheduled production
        # remaining for the relevant product family.
        future_dates = sorted({
            date.fromisoformat(o["material_required_date"])
            for o in orders
            if (
                o["product_family_id"] == family_id
                and date.fromisoformat(
                    o["material_required_date"]
                ) > SNAPSHOT
            )
        })

        if not future_dates:
            raise ValueError(
                f"No future production orders for {family_id}"
            )

        for index, part in enumerate(selected):
            approved = index < 2

            effective_date = (
                rng.choice(future_dates).isoformat()
                if approved else ""
            )

            changes.append({
                "change_id": f"EC-{len(changes) + 1:03d}",
                "part_id": part["part_id"],
                "product_family_id": family_id,
                "old_revision": part["revision"],
                "proposed_revision": "B",
                "change_reason": rng.choice(reasons),
                "approval_status": (
                    "APPROVED" if approved else "PENDING"
                ),
                "effective_date": effective_date,
                "affected_bom_lines": referenced[
                    part["part_id"]
                ],
                "old_revision_accepted_after_cutover": (
                    "NO" if approved else "NOT_APPLICABLE"
                ),
                "implementation_mode": (
                    "SCENARIO_ONLY" if approved
                    else "NOT_RELEASED"
                ),
            })

    return changes


# ------------------------------------------------------------
# 3. Generate Approved Alternative Suppliers
# ------------------------------------------------------------

def generate_alternates(parts, suppliers, changes):
    alternates = []

    supplier_ids = sorted(
        s["supplier_id"] for s in suppliers
    )

    changed_parts = {
        c["part_id"] for c in changes
    }

    by_family = defaultdict(list)

    for part in parts:
        if (
            part["part_type"] == "PURCHASED_COMPONENT"
            and part["part_id"] not in changed_parts
        ):
            by_family[
                part["product_family_id"]
            ].append(part)

    for family_id in sorted(by_family):
        candidates = sorted(
            by_family[family_id],
            key=lambda p: p["part_id"]
        )

        selected = rng.sample(candidates, 10)

        for part in selected:
            primary = part["primary_supplier_id"]

            eligible_suppliers = [
                supplier_id for supplier_id in supplier_ids
                if supplier_id != primary
            ]

            alternate_supplier = rng.choice(
                eligible_suppliers
            )

            quoted_lead_time = max(
                3,
                int(part["lead_time_days"])
                - rng.randint(3, 10)
            )

            quoted_cost = round(
                float(part["unit_cost_usd"])
                * rng.uniform(1.08, 1.35),
                2
            )

            alternates.append({
                "alternate_id": (
                    f"ALT-{len(alternates) + 1:03d}"
                ),
                "part_id": part["part_id"],
                "approved_revision": part["revision"],
                "primary_supplier_id": primary,
                "alternate_supplier_id": alternate_supplier,
                "approval_status": "APPROVED",
                "qualification_date": "2026-12-01",
                "quoted_lead_time_days": quoted_lead_time,
                "quoted_unit_cost_usd": quoted_cost,
                "max_available_qty": rng.randint(50, 250),
            })

    return alternates


# ------------------------------------------------------------
# 4. Generate Manufacturing Disruption Scenarios
# ------------------------------------------------------------

def generate_scenarios(
    inventory, allocations, purchase_orders, orders, changes
):
    # Calculate inventory not already held or allocated.
    allocated = Counter()

    for allocation in allocations:
        key = (
            allocation["part_id"],
            allocation["location_id"]
        )
        allocated[key] += int(
            allocation["allocated_qty"]
        )

    available_rows = []

    for row in inventory:
        key = (row["part_id"], row["location_id"])

        unreserved = (
            int(row["on_hand_qty"])
            - int(row["quality_hold_qty"])
            - allocated[key]
        )

        if unreserved >= 5:
            available_rows.append((row, unreserved))

    if len(available_rows) < 2:
        raise ValueError(
            "Insufficient unreserved inventory for scenarios"
        )

    quality_target, damage_target = rng.sample(
        available_rows, 2
    )

    quality_row, quality_available = quality_target
    damage_row, damage_available = damage_target

    extra_quality_hold = max(
        1, round(quality_available * 0.25)
    )

    damaged_stock = max(
        1, round(damage_available * 0.20)
    )

    eligible_pos = [
        po for po in purchase_orders
        if (
            date.fromisoformat(
                po["expected_receipt_date"]
            )
            <= HORIZON_END - timedelta(days=14)
            and date.fromisoformat(
                po["expected_receipt_date"]
            ) > SNAPSHOT
        )
    ]

    if not eligible_pos:
        raise ValueError(
            "No eligible purchase order for delay scenario"
        )

    delayed_po = rng.choice(eligible_pos)

    eligible_orders = [
        o for o in orders
        if date.fromisoformat(
            o["material_required_date"]
        ) > SNAPSHOT
    ]

    demand_order = rng.choice(eligible_orders)

    approved_changes = [
        change for change in changes
        if change["approval_status"] == "APPROVED"
    ]

    revision_change = rng.choice(approved_changes)

    scenarios = [
        {
            "scenario_id": "SCN-001",
            "scenario_name": "Supplier Delivery Disruption",
            "event_type": "SUPPLIER_DELAY",
            "target_type": "PURCHASE_ORDER",
            "target_id": delayed_po["purchase_order_id"],
            "effective_date": SNAPSHOT.isoformat(),
            "parameter_name": "additional_delay_days",
            "numeric_value": 14,
            "text_value": "",
            "description": (
                "Add 14 days to the expected receipt date."
            ),
        },
        {
            "scenario_id": "SCN-002",
            "scenario_name": "Additional Quality Hold",
            "event_type": "QUALITY_HOLD",
            "target_type": "INVENTORY_RECORD",
            "target_id": quality_row["inventory_record_id"],
            "effective_date": SNAPSHOT.isoformat(),
            "parameter_name": "additional_hold_qty",
            "numeric_value": extra_quality_hold,
            "text_value": "",
            "description": (
                "Place additional unreserved material on hold."
            ),
        },
        {
            "scenario_id": "SCN-003",
            "scenario_name": "Warehouse Inventory Damage",
            "event_type": "INVENTORY_LOSS",
            "target_type": "INVENTORY_RECORD",
            "target_id": damage_row["inventory_record_id"],
            "effective_date": SNAPSHOT.isoformat(),
            "parameter_name": "lost_qty",
            "numeric_value": damaged_stock,
            "text_value": "",
            "description": (
                "Remove damaged, unreserved inventory."
            ),
        },
        {
            "scenario_id": "SCN-004",
            "scenario_name": "Priority Production Increase",
            "event_type": "DEMAND_INCREASE",
            "target_type": "PRODUCTION_ORDER",
            "target_id": demand_order["production_order_id"],
            "effective_date": SNAPSHOT.isoformat(),
            "parameter_name": "additional_finished_units",
            "numeric_value": max(
                1, round(
                    int(demand_order["order_quantity"]) * 0.5
                )
            ),
            "text_value": "",
            "description": (
                "Increase finished-unit requirements for one order."
            ),
        },
        {
            "scenario_id": "SCN-005",
            "scenario_name": "Engineering Revision Cutover",
            "event_type": "REVISION_CUTOVER",
            "target_type": "ENGINEERING_CHANGE",
            "target_id": revision_change["change_id"],
            "effective_date": revision_change["effective_date"],
            "parameter_name": "required_component_revision",
            "numeric_value": "",
            "text_value": revision_change["proposed_revision"],
            "description": (
                "Evaluate new revision requirements after cutover."
            ),
        },
    ]

    return scenarios


# ------------------------------------------------------------
# 5. Validate Engineering and Disruption Data
# ------------------------------------------------------------

def validate_outputs(
    changes, alternates, scenarios,
    parts, suppliers, inventory, purchase_orders, orders
):
    part_lookup = {p["part_id"]: p for p in parts}
    supplier_ids = {s["supplier_id"] for s in suppliers}

    assert len(changes) == 12
    assert len(alternates) == 40
    assert len(scenarios) == 5

    assert len({c["change_id"] for c in changes}) == 12
    assert len({c["part_id"] for c in changes}) == 12
    assert len({a["part_id"] for a in alternates}) == 40
    assert len({s["scenario_id"] for s in scenarios}) == 5

    approved = [
        c for c in changes
        if c["approval_status"] == "APPROVED"
    ]
    pending = [
        c for c in changes
        if c["approval_status"] == "PENDING"
    ]

    assert len(approved) == 8
    assert len(pending) == 4

    for change in changes:
        part = part_lookup[change["part_id"]]

        assert part["part_type"] == "PURCHASED_COMPONENT"
        assert change["old_revision"] == part["revision"]
        assert change["proposed_revision"] != part["revision"]
        assert change["affected_bom_lines"] > 0

        if change["approval_status"] == "APPROVED":
            effective = date.fromisoformat(
                change["effective_date"]
            )
            assert SNAPSHOT < effective < HORIZON_END
            assert (
                change["old_revision_accepted_after_cutover"]
                == "NO"
            )
        else:
            assert change["effective_date"] == ""

    for alternate in alternates:
        part = part_lookup[alternate["part_id"]]

        assert (
            alternate["primary_supplier_id"]
            == part["primary_supplier_id"]
        )
        assert alternate["alternate_supplier_id"] in supplier_ids
        assert (
            alternate["alternate_supplier_id"]
            != alternate["primary_supplier_id"]
        )
        assert alternate["approved_revision"] == part["revision"]
        assert alternate["quoted_lead_time_days"] > 0
        assert alternate["max_available_qty"] > 0
        assert alternate["quoted_unit_cost_usd"] > 0

    valid_targets = {
        "PURCHASE_ORDER": {
            x["purchase_order_id"] for x in purchase_orders
        },
        "INVENTORY_RECORD": {
            x["inventory_record_id"] for x in inventory
        },
        "PRODUCTION_ORDER": {
            x["production_order_id"] for x in orders
        },
        "ENGINEERING_CHANGE": {
            x["change_id"] for x in changes
        },
    }

    for scenario in scenarios:
        assert (
            scenario["target_id"]
            in valid_targets[scenario["target_type"]]
        )
        assert (
            SNAPSHOT
            <= date.fromisoformat(scenario["effective_date"])
            < HORIZON_END
        )
        assert (
            scenario["numeric_value"] != ""
            or scenario["text_value"] != ""
        )

    assert {
        s["event_type"] for s in scenarios
    } == {
        "SUPPLIER_DELAY",
        "QUALITY_HOLD",
        "INVENTORY_LOSS",
        "DEMAND_INCREASE",
        "REVISION_CUTOVER",
    }

    print("Engineering and disruption validation: PASSED")
    print(f"Engineering changes: {len(changes)}")
    print(f"Approved changes: {len(approved)}")
    print(f"Pending changes: {len(pending)}")
    print(f"Approved alternative sources: {len(alternates)}")
    print(f"Disruption scenarios: {len(scenarios)}")


# ------------------------------------------------------------
# 6. Main Execution
# ------------------------------------------------------------

def main():
    parts = load_csv("part_master.csv")
    suppliers = load_csv("suppliers.csv")
    bom = load_csv("bom_structure.csv")
    orders = load_csv("production_orders.csv")
    inventory = load_csv("inventory.csv")
    allocations = load_csv("inventory_allocations.csv")
    purchase_orders = load_csv("purchase_orders.csv")

    changes = generate_engineering_changes(
        parts, bom, orders
    )

    alternates = generate_alternates(
        parts, suppliers, changes
    )

    scenarios = generate_scenarios(
        inventory, allocations, purchase_orders,
        orders, changes
    )

    validate_outputs(
        changes, alternates, scenarios,
        parts, suppliers, inventory, purchase_orders, orders
    )

    write_csv("engineering_changes.csv", changes)
    write_csv("approved_alternates.csv", alternates)
    write_csv("disruption_scenarios.csv", scenarios)

    manifest = {
        "project": "Manufacturing Readiness & Shortage Intelligence",
        "data_type": "SYNTHETIC",
        "random_seed": SEED,
        "snapshot_date": SNAPSHOT.isoformat(),
        "planning_horizon_end_exclusive": HORIZON_END.isoformat(),
        "engineering_changes": len(changes),
        "qualified_alternative_sources": len(alternates),
        "disruption_scenarios": len(scenarios),
        "scenario_mode": "INDEPENDENT_BASELINE_COMPARISONS",
        "assumptions": [
            "Engineering changes are hypothetical.",
            "Only approved changes have effective dates.",
            "Revision B is not interchangeable with revision A.",
            "Engineering cutovers are applied only in simulations.",
            "Alternative suppliers are simulated as qualified.",
            "Disruptions do not alter original baseline datasets.",
            "Scenario costs and recovery effects require modeling.",
        ],
    }

    with (
        RAW / "disruption_manifest.json"
    ).open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print("Created disruption_manifest.json")
    print("\nPhase 1 / Step 5 completed successfully.")


if __name__ == "__main__":
    main()
