BEGIN TRANSACTION;

CREATE SCHEMA IF NOT EXISTS core;

-- 1. Product Families
CREATE OR REPLACE TABLE core.product_families AS
SELECT *
FROM raw.product_families;

-- 2. Suppliers
CREATE OR REPLACE TABLE core.suppliers AS
SELECT *
FROM raw.suppliers;

-- 3. Part Master
CREATE OR REPLACE TABLE core.part_master AS
SELECT * REPLACE (
    CAST(NULLIF(unit_cost_usd, '') AS DECIMAL(14,2))
        AS unit_cost_usd,
    CAST(NULLIF(lead_time_days, '') AS INTEGER)
        AS lead_time_days
)
FROM raw.part_master;

-- 4. Manufacturing BOM
CREATE OR REPLACE TABLE core.bom_structure AS
SELECT * REPLACE (
    CAST(quantity_per_parent AS INTEGER)
        AS quantity_per_parent,
    CAST(effective_start_date AS DATE)
        AS effective_start_date,
    CAST(NULLIF(effective_end_date, '') AS DATE)
        AS effective_end_date
)
FROM raw.bom_structure;

-- 5. Production Orders
CREATE OR REPLACE TABLE core.production_orders AS
SELECT * REPLACE (
    CAST(order_quantity AS INTEGER)
        AS order_quantity,
    CAST(planned_week AS INTEGER)
        AS planned_week,
    CAST(planned_start_date AS DATE)
        AS planned_start_date,
    CAST(material_required_date AS DATE)
        AS material_required_date,
    CAST(planned_due_date AS DATE)
        AS planned_due_date
)
FROM raw.production_orders;

-- 6. Inventory
CREATE OR REPLACE TABLE core.inventory AS
SELECT * REPLACE (
    CAST(snapshot_date AS DATE)
        AS snapshot_date,
    CAST(on_hand_qty AS INTEGER)
        AS on_hand_qty,
    CAST(quality_hold_qty AS INTEGER)
        AS quality_hold_qty
)
FROM raw.inventory;

-- 7. Inventory Allocations
CREATE OR REPLACE TABLE core.inventory_allocations AS
SELECT * REPLACE (
    CAST(allocated_qty AS INTEGER)
        AS allocated_qty,
    CAST(allocation_date AS DATE)
        AS allocation_date
)
FROM raw.inventory_allocations;

-- 8. Purchase Orders
CREATE OR REPLACE TABLE core.purchase_orders AS
SELECT * REPLACE (
    CAST(ordered_qty AS INTEGER)
        AS ordered_qty,
    CAST(order_date AS DATE)
        AS order_date,
    CAST(original_promised_date AS DATE)
        AS original_promised_date,
    CAST(expected_receipt_date AS DATE)
        AS expected_receipt_date,
    CAST(delay_days AS INTEGER)
        AS delay_days,
    CAST(unit_cost_usd AS DECIMAL(14,2))
        AS unit_cost_usd
)
FROM raw.purchase_orders;

-- 9. Engineering Changes
CREATE OR REPLACE TABLE core.engineering_changes AS
SELECT * REPLACE (
    CAST(NULLIF(effective_date, '') AS DATE)
        AS effective_date,
    CAST(affected_bom_lines AS INTEGER)
        AS affected_bom_lines
)
FROM raw.engineering_changes;

-- 10. Approved Alternate Suppliers
CREATE OR REPLACE TABLE core.approved_alternates AS
SELECT * REPLACE (
    CAST(qualification_date AS DATE)
        AS qualification_date,
    CAST(quoted_lead_time_days AS INTEGER)
        AS quoted_lead_time_days,
    CAST(quoted_unit_cost_usd AS DECIMAL(14,2))
        AS quoted_unit_cost_usd,
    CAST(max_available_qty AS INTEGER)
        AS max_available_qty
)
FROM raw.approved_alternates;

-- 11. Disruption Scenarios
CREATE OR REPLACE TABLE core.disruption_scenarios AS
SELECT * REPLACE (
    CAST(effective_date AS DATE)
        AS effective_date,
    CAST(NULLIF(numeric_value, '') AS INTEGER)
        AS numeric_value
)
FROM raw.disruption_scenarios;

COMMIT;
