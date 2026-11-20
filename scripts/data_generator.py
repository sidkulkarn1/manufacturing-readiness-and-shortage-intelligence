

from pathlib import Path
import csv
import json
import random

# ============================================================
# Synthetic Manufacturing Master Data
# ============================================================

SEED = 2027
rng = random.Random(SEED)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------
# 1. Product Families
# ------------------------------------------------------------

families = [
    ("FAM-01", "Avionics Control Modules"),
    ("FAM-02", "Power Distribution Assemblies"),
    ("FAM-03", "Sensor and Communication Modules"),
    ("FAM-04", "Electromechanical Assemblies"),
]

family_records = [
    {
        "family_id": family_id,
        "family_name": family_name,
        "finished_good_id": f"FG-{i:03d}",
    }
    for i, (family_id, family_name) in enumerate(families, 1)
]

# ------------------------------------------------------------
# 2. Synthetic Suppliers
# ------------------------------------------------------------

supplier_regions = [
    "US Midwest",
    "US West",
    "US Northeast",
    "US Southeast",
    "Germany",
    "Japan",
    "Taiwan",
    "Mexico",
]

supplier_records = [
    {
        "supplier_id": f"SUP-{i:03d}",
        "supplier_name": f"Simulated Supplier {i:02d}",
        "region": region,
        "supplier_status": "ACTIVE",
    }
    for i, region in enumerate(supplier_regions, 1)
]

# ------------------------------------------------------------
# 3. Component Categories and Planning Assumptions
# ------------------------------------------------------------

category_parameters = {
    "Electronics": (20.0, 400.0, 14, 45),
    "Sensors": (35.0, 650.0, 21, 56),
    "Power": (25.0, 500.0, 21, 49),
    "Mechanical": (10.0, 300.0, 7, 35),
    "Connectors": (2.0, 80.0, 7, 28),
    "Fasteners": (0.5, 25.0, 5, 18),
}

family_categories = {
    "FAM-01": ["Electronics", "Sensors", "Connectors"],
    "FAM-02": ["Power", "Electronics", "Connectors"],
    "FAM-03": ["Sensors", "Electronics", "Connectors"],
    "FAM-04": ["Mechanical", "Fasteners", "Power"],
}

# ------------------------------------------------------------
# 4. Part Master
# ------------------------------------------------------------

part_records = []

# 400 purchased components: 100 assigned to each family
component_number = 1

for family_id, _ in families:
    for _ in range(100):
        category = rng.choice(family_categories[family_id])
        min_cost, max_cost, min_lt, max_lt = category_parameters[category]

        part_records.append({
            "part_id": f"CMP-{component_number:04d}",
            "part_description": f"{category} Component {component_number:04d}",
            "part_type": "PURCHASED_COMPONENT",
            "product_family_id": family_id,
            "category": category,
            "revision": "A",
            "uom": "EA",
            "unit_cost_usd": round(rng.uniform(min_cost, max_cost), 2),
            "primary_supplier_id": rng.choice(
                supplier_records
            )["supplier_id"],
            "lead_time_days": rng.randint(min_lt, max_lt),
            "lifecycle_status": "ACTIVE",
        })

        component_number += 1

# 24 manufactured subassemblies: 6 per family
for family_index, (family_id, _) in enumerate(families):
    for local_number in range(1, 7):
        assembly_number = family_index * 6 + local_number

        part_records.append({
            "part_id": f"SA-{assembly_number:03d}",
            "part_description": f"Subassembly {assembly_number:03d}",
            "part_type": "SUBASSEMBLY",
            "product_family_id": family_id,
            "category": "Manufactured Assembly",
            "revision": "A",
            "uom": "EA",
            "unit_cost_usd": "",
            "primary_supplier_id": "",
            "lead_time_days": "",
            "lifecycle_status": "ACTIVE",
        })

# 4 finished products
for i, (family_id, family_name) in enumerate(families, 1):
    part_records.append({
        "part_id": f"FG-{i:03d}",
        "part_description": family_name,
        "part_type": "FINISHED_GOOD",
        "product_family_id": family_id,
        "category": "Finished Product",
        "revision": "A",
        "uom": "EA",
        "unit_cost_usd": "",
        "primary_supplier_id": "",
        "lead_time_days": "",
        "lifecycle_status": "ACTIVE",
    })

# ------------------------------------------------------------
# 5. CSV Export
# ------------------------------------------------------------

def write_csv(filename, records):
    if not records:
        raise ValueError(f"No records supplied for {filename}")

    output_path = RAW_DIR / filename

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)

    print(f"Created {filename}: {len(records)} records")


# ------------------------------------------------------------
# 6. Basic Validation
# ------------------------------------------------------------

def validate_master_data():
    component_records = [
        p for p in part_records
        if p["part_type"] == "PURCHASED_COMPONENT"
    ]

    supplier_ids = {s["supplier_id"] for s in supplier_records}
    part_ids = [p["part_id"] for p in part_records]
    family_ids = {f["family_id"] for f in family_records}

    assert len(component_records) == 400
    assert len(supplier_records) == 8
    assert len(family_records) == 4
    assert len(part_records) == 428
    assert len(part_ids) == len(set(part_ids))

    for part in part_records:
        assert part["product_family_id"] in family_ids

    for part in component_records:
        assert part["primary_supplier_id"] in supplier_ids
        assert part["unit_cost_usd"] > 0
        assert part["lead_time_days"] > 0

    print("Master data validation: PASSED")


# ------------------------------------------------------------
# 7. Main Execution
# ------------------------------------------------------------

def main():
    validate_master_data()

    write_csv("product_families.csv", family_records)
    write_csv("suppliers.csv", supplier_records)
    write_csv("part_master.csv", part_records)

    manifest = {
        "project": "Manufacturing Readiness & Shortage Intelligence",
        "data_type": "SYNTHETIC",
        "random_seed": SEED,
        "purchased_components": 400,
        "subassemblies": 24,
        "finished_goods": 4,
        "suppliers": 8,
        "product_families": 4,
        "note": "All records and planning assumptions are simulated.",
    }

    with (RAW_DIR / "dataset_manifest.json").open(
        "w", encoding="utf-8"
    ) as f:
        json.dump(manifest, f, indent=2)

    print("Created dataset_manifest.json")


if __name__ == "__main__":
    main()


