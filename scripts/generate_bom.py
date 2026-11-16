
from pathlib import Path
from collections import Counter, defaultdict
import csv
import random

# ============================================================python3 scripts/generate_bom.py
# Phase 1 / Step 2: Multi-Level Manufacturing BOM
# ============================================================

SEED = 2028
rng = random.Random(SEED)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"

PART_MASTER = RAW_DIR / "part_master.csv"
BOM_OUTPUT = RAW_DIR / "bom_structure.csv"

EFFECTIVE_START = "2027-01-04"


# ------------------------------------------------------------
# 1. Load Part Master
# ------------------------------------------------------------

def load_parts():
    with PART_MASTER.open(
        "r", newline="", encoding="utf-8"
    ) as file:
        parts = list(csv.DictReader(file))

    assert len(parts) == 428, (
        f"Expected 428 parts, found {len(parts)}"
    )

    print(f"Loaded part master: {len(parts)} records")
    return parts


# ------------------------------------------------------------
# 2. Generate BOM Relationships
# ------------------------------------------------------------

def generate_bom(parts):
    bom = []

    families = sorted({
        part["product_family_id"] for part in parts
    })

    def add_line(parent, component, quantity):
        bom.append({
            "bom_line_id": f"BOM-{len(bom) + 1:05d}",
            "parent_part_id": parent["part_id"],
            "parent_revision": parent["revision"],
            "component_part_id": component["part_id"],
            "component_revision": component["revision"],
            "quantity_per_parent": quantity,
            "effective_start_date": EFFECTIVE_START,
            "effective_end_date": "",
        })

    for family_id in families:

        family_parts = [
            p for p in parts
            if p["product_family_id"] == family_id
        ]

        finished_goods = [
            p for p in family_parts
            if p["part_type"] == "FINISHED_GOOD"
        ]

        subassemblies = sorted(
            [
                p for p in family_parts
                if p["part_type"] == "SUBASSEMBLY"
            ],
            key=lambda p: p["part_id"]
        )

        components = sorted(
            [
                p for p in family_parts
                if p["part_type"] == "PURCHASED_COMPONENT"
            ],
            key=lambda p: p["part_id"]
        )

        assert len(finished_goods) == 1
        assert len(subassemblies) == 6
        assert len(components) == 100

        finished_good = finished_goods[0]

        # Level 1: Finished good -> Subassemblies
        for subassembly in subassemblies:
            add_line(
                finished_good,
                subassembly,
                quantity=1
            )

        # Level 2: Subassemblies -> Purchased components
        # Every purchased component receives an initial
        # assignment to one subassembly.
        for index, component in enumerate(components):
            subassembly = subassemblies[
                index % len(subassemblies)
            ]

            add_line(
                subassembly,
                component,
                quantity=rng.randint(1, 4)
            )

        # Add shared components across subassemblies.
        # This creates realistic common-material dependencies.
        for subassembly in subassemblies:

            already_used = {
                line["component_part_id"]
                for line in bom
                if line["parent_part_id"]
                == subassembly["part_id"]
            }

            candidates = [
                component for component in components
                if component["part_id"] not in already_used
            ]

            shared_components = rng.sample(
                candidates, 3
            )

            for component in shared_components:
                add_line(
                    subassembly,
                    component,
                    quantity=rng.randint(1, 3)
                )

    return bom


# ------------------------------------------------------------
# 3. Validate BOM
# ------------------------------------------------------------

def validate_bom(parts, bom):

    part_lookup = {
        part["part_id"]: part for part in parts
    }

    purchased = {
        p["part_id"] for p in parts
        if p["part_type"] == "PURCHASED_COMPONENT"
    }

    subassemblies = {
        p["part_id"] for p in parts
        if p["part_type"] == "SUBASSEMBLY"
    }

    finished_goods = {
        p["part_id"] for p in parts
        if p["part_type"] == "FINISHED_GOOD"
    }

    parent_children = defaultdict(list)
    component_usage = Counter()
    unique_links = set()

    for line in bom:

        parent_id = line["parent_part_id"]
        component_id = line["component_part_id"]

        assert parent_id in part_lookup
        assert component_id in part_lookup
        assert parent_id != component_id
        assert int(line["quantity_per_parent"]) > 0

        parent = part_lookup[parent_id]
        component = part_lookup[component_id]

        assert line["parent_revision"] == parent["revision"]
        assert line["component_revision"] == component["revision"]

        # Only valid hierarchy relationships are allowed.
        valid_relationship = (
            (
                parent["part_type"] == "FINISHED_GOOD"
                and component["part_type"] == "SUBASSEMBLY"
            )
            or
            (
                parent["part_type"] == "SUBASSEMBLY"
                and component["part_type"] == "PURCHASED_COMPONENT"
            )
        )

        assert valid_relationship
        assert (
            parent["product_family_id"]
            == component["product_family_id"]
        )

        link = (parent_id, component_id)
        assert link not in unique_links
        unique_links.add(link)

        parent_children[parent_id].append(component_id)

        if component_id in purchased:
            component_usage[component_id] += 1

    assert len(bom) == 496
    assert len(finished_goods) == 4
    assert len(subassemblies) == 24

    # Every finished good contains six subassemblies.
    for fg_id in finished_goods:
        assert len(parent_children[fg_id]) == 6

    # Every subassembly must contain purchased components.
    for sa_id in subassemblies:
        assert len(parent_children[sa_id]) >= 16

    # Every purchased component must appear in the BOM.
    assert set(component_usage) == purchased

    # Confirm some components are shared across assemblies.
    shared_count = sum(
        count > 1 for count in component_usage.values()
    )
    assert shared_count > 0

    print("BOM validation: PASSED")
    print(f"Finished goods: {len(finished_goods)}")
    print(f"Subassemblies: {len(subassemblies)}")
    print(f"Purchased components: {len(purchased)}")
    print(f"Total BOM relationships: {len(bom)}")
    print(f"Shared components: {shared_count}")


# ------------------------------------------------------------
# 4. Export BOM
# ------------------------------------------------------------

def export_bom(bom):

    with BOM_OUTPUT.open(
        "w", newline="", encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=list(bom[0].keys())
        )

        writer.writeheader()
        writer.writerows(bom)

    print(f"Created: {BOM_OUTPUT.name}")


# ------------------------------------------------------------
# 5. Main Execution
# ------------------------------------------------------------

def main():

    parts = load_parts()
    bom = generate_bom(parts)

    validate_bom(parts, bom)
    export_bom(bom)

    print("\nPhase 1 / Step 2 completed successfully.")


if __name__ == "__main__":
    main()
