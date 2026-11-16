-- Business Objective:
-- Identify component shortages, affected production orders,
-- supplier exposure, material value, and intervention priority.
--
-- All operational and financial results are simulated.
-- Missing material value is not lost revenue or realized cost.

BEGIN TRANSACTION;

CREATE SCHEMA IF NOT EXISTS planning;


-- ============================================================
-- 1. COMPONENT SHORTAGE EXCEPTION REPORT
-- ============================================================

CREATE OR REPLACE TABLE planning.shortage_exceptions AS

WITH snapshot AS (
    SELECT MAX(snapshot_date) AS snapshot_date
    FROM core.inventory
)

SELECT
    c.production_order_id,
    o.finished_good_id,
    o.product_family_id,
    o.priority AS order_priority,

    c.material_required_date,
    o.planned_due_date,

    c.component_part_id,
    c.component_revision,

    p.part_description,
    p.category AS component_category,

    p.primary_supplier_id AS supplier_id,
    s.supplier_name,
    p.lead_time_days,

    c.gross_required_qty,
    c.reserved_qty,
    c.covered_unreserved_qty,
    c.inbound_qty_by_date,
    c.shortage_qty,

    p.unit_cost_usd,

    CAST(
        c.shortage_qty * p.unit_cost_usd
        AS DECIMAL(18,2)
    ) AS modeled_missing_material_value_usd,

    date_diff(
        'day',
        snap.snapshot_date,
        c.material_required_date
    ) AS days_to_requirement,

    (
        SELECT MIN(po.expected_receipt_date)
        FROM core.purchase_orders po
        WHERE po.part_id = c.component_part_id
          AND po.revision = c.component_revision
          AND po.order_status = 'OPEN'
          AND po.expected_receipt_date
              > c.material_required_date
    ) AS next_open_receipt_after_requirement

FROM planning.component_readiness c

JOIN core.production_orders o
    ON c.production_order_id = o.production_order_id

JOIN core.part_master p
    ON c.component_part_id = p.part_id
   AND c.component_revision = p.revision

JOIN core.suppliers s
    ON p.primary_supplier_id = s.supplier_id

CROSS JOIN snapshot snap

WHERE c.shortage_qty > 0;


-- ============================================================
-- 2. COMPONENT-LEVEL SHORTAGE SUMMARY
-- ============================================================

CREATE OR REPLACE TABLE planning.shortage_priority AS

WITH component_summary AS (

    SELECT
        component_part_id,
        component_revision,

        MAX(part_description) AS part_description,
        MAX(component_category) AS component_category,
        MAX(supplier_id) AS supplier_id,
        MAX(supplier_name) AS supplier_name,
        MAX(lead_time_days) AS lead_time_days,

        COUNT(DISTINCT production_order_id)
            AS affected_orders,

        COUNT(DISTINCT production_order_id)
            FILTER (
                WHERE order_priority = 'HIGH'
            ) AS high_priority_orders,

        SUM(shortage_qty)::BIGINT
            AS total_shortage_units,

        CAST(
            SUM(modeled_missing_material_value_usd)
            AS DECIMAL(18,2)
        ) AS modeled_missing_material_value_usd,

        MIN(material_required_date)
            AS earliest_requirement_date,

        MIN(days_to_requirement)
            AS days_to_next_requirement,

        MIN(next_open_receipt_after_requirement)
            AS earliest_late_receipt_date

    FROM planning.shortage_exceptions

    GROUP BY
        component_part_id,
        component_revision

),

risk_scores AS (

    SELECT
        *,

        (
            -- Production order exposure: maximum 30 points
            LEAST(30, affected_orders * 10)

            -- High-priority production exposure: 20 points
            + CASE
                WHEN high_priority_orders > 0 THEN 20
                ELSE 0
              END

            -- Shortage urgency: maximum 25 points
            + CASE
                WHEN days_to_next_requirement <= 7 THEN 25
                WHEN days_to_next_requirement <= 14 THEN 15
                WHEN days_to_next_requirement <= 28 THEN 5
                ELSE 0
              END

            -- Supplier lead-time exposure: maximum 15 points
            + CASE
                WHEN lead_time_days >= 35 THEN 15
                WHEN lead_time_days >= 21 THEN 10
                ELSE 0
              END

            -- Shortage magnitude: maximum 10 points
            + CASE
                WHEN total_shortage_units >= 50 THEN 10
                ELSE 0
              END

        )::INTEGER AS risk_score

    FROM component_summary

)

SELECT
    ROW_NUMBER() OVER (
        ORDER BY
            risk_score DESC,
            affected_orders DESC,
            total_shortage_units DESC,
            component_part_id
    ) AS shortage_rank,

    *,

    CASE
        WHEN risk_score >= 70 THEN 'CRITICAL'
        WHEN risk_score >= 40 THEN 'HIGH'
        ELSE 'MODERATE'
    END AS shortage_severity

FROM risk_scores;


-- ============================================================
-- 3. SUPPLIER SHORTAGE EXPOSURE
-- ============================================================

CREATE OR REPLACE TABLE planning.supplier_shortage_exposure AS

SELECT
    supplier_id,
    supplier_name,

    COUNT(DISTINCT component_part_id)
        AS short_components,

    COUNT(DISTINCT production_order_id)
        AS affected_production_orders,

    COUNT(*) AS shortage_exception_lines,

    SUM(shortage_qty)::BIGINT
        AS total_shortage_units,

    CAST(
        SUM(modeled_missing_material_value_usd)
        AS DECIMAL(18,2)
    ) AS modeled_missing_material_value_usd,

    MIN(material_required_date)
        AS earliest_material_required_date,

    MAX(lead_time_days)
        AS longest_component_lead_time_days

FROM planning.shortage_exceptions

GROUP BY
    supplier_id,
    supplier_name;


-- ============================================================
-- 4. EXECUTIVE SHORTAGE KPIs
-- ============================================================

CREATE OR REPLACE VIEW planning.shortage_kpis AS

SELECT
    (SELECT COUNT(*)
     FROM planning.shortage_priority)
        AS unique_short_components,

    (SELECT COUNT(DISTINCT production_order_id)
     FROM planning.shortage_exceptions)
        AS affected_production_orders,

    (SELECT COUNT(*)
     FROM planning.shortage_exceptions)
        AS shortage_exception_lines,

    (SELECT COALESCE(SUM(shortage_qty), 0)
     FROM planning.shortage_exceptions)
        AS total_shortage_units,

    (SELECT COALESCE(
         SUM(modeled_missing_material_value_usd), 0)
     FROM planning.shortage_exceptions)
        AS modeled_missing_material_value_usd,

    (SELECT COUNT(*)
     FROM planning.shortage_priority
     WHERE shortage_severity = 'CRITICAL')
        AS critical_short_components,

    (SELECT COUNT(*)
     FROM planning.shortage_priority
     WHERE shortage_severity = 'HIGH')
        AS high_severity_components;

COMMIT;

-- ============================================================
-- END SQL05
-- ============================================================
