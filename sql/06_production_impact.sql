-- Business objective:
-- Connect component shortages to affected production orders,
-- measure operational exposure, and evaluate an illustrative
-- standard-replenishment scheduling assumption.
--
-- Important:
-- A blocked order does not have a confirmed recovery date.
-- The modeled delay below assumes that new purchase orders
-- are placed at the planning snapshot, suppliers can provide
-- all missing units, and standard lead times are achieved.
--
-- Therefore, these are conditional scenario estimates,
-- NOT confirmed baseline delays or actual company results.

BEGIN TRANSACTION;

CREATE SCHEMA IF NOT EXISTS planning;


-- ============================================================
-- 1. PRODUCTION ORDER SHORTAGE DRIVERS
-- ============================================================

CREATE OR REPLACE TABLE planning.order_shortage_drivers AS

WITH snapshot AS (
    SELECT MAX(snapshot_date) AS snapshot_date
    FROM core.inventory
)

SELECT
    e.production_order_id,

    COUNT(*) AS shortage_component_count,

    SUM(e.shortage_qty)::BIGINT
        AS total_missing_component_units,

    CAST(
        SUM(e.modeled_missing_material_value_usd)
        AS DECIMAL(18,2)
    ) AS modeled_missing_material_value_usd,

    COUNT(*) FILTER (
        WHERE p.shortage_severity = 'CRITICAL'
    ) AS critical_shortage_components,

    MAX(p.risk_score) AS highest_shortage_risk_score,

    MAX(e.lead_time_days)
        AS longest_short_component_lead_time,

    -- Hypothetical new procurement initiated at snapshot.
    MAX(
        s.snapshot_date + CAST(e.lead_time_days AS INTEGER)
    ) AS illustrative_latest_replenishment_date

FROM planning.shortage_exceptions e

JOIN planning.shortage_priority p
    ON e.component_part_id = p.component_part_id
   AND e.component_revision = p.component_revision

CROSS JOIN snapshot s

GROUP BY e.production_order_id;


-- ============================================================
-- 2. ORDER-LEVEL PRODUCTION IMPACT
-- ============================================================

CREATE OR REPLACE TABLE planning.production_impact AS

WITH base AS (

    SELECT
        o.production_order_id,
        o.finished_good_id,
        o.product_family_id,
        o.order_quantity,
        o.priority,
        o.planned_week,
        o.planned_start_date,
        o.material_required_date,
        o.planned_due_date,

        r.readiness_status,

        COALESCE(
            d.shortage_component_count, 0
        ) AS shortage_component_count,

        COALESCE(
            d.total_missing_component_units, 0
        )::BIGINT AS total_missing_component_units,

        CAST(
            COALESCE(
                d.modeled_missing_material_value_usd, 0
            ) AS DECIMAL(18,2)
        ) AS modeled_missing_material_value_usd,

        COALESCE(
            d.critical_shortage_components, 0
        ) AS critical_shortage_components,

        COALESCE(
            d.highest_shortage_risk_score, 0
        ) AS highest_shortage_risk_score,

        d.longest_short_component_lead_time,

        d.illustrative_latest_replenishment_date,

        CASE
            WHEN r.readiness_status = 'BLOCKED'
            THEN GREATEST(
                o.planned_start_date,
                d.illustrative_latest_replenishment_date
            )
            ELSE o.planned_start_date
        END AS illustrative_replenishment_start_date

    FROM core.production_orders o

    JOIN planning.production_order_readiness r
        ON o.production_order_id = r.production_order_id

    LEFT JOIN planning.order_shortage_drivers d
        ON o.production_order_id = d.production_order_id

),

delays AS (

    SELECT
        *,

        CAST(
            date_diff(
                'day',
                planned_start_date,
                illustrative_replenishment_start_date
            ) AS INTEGER
        ) AS illustrative_replenishment_delay_days

    FROM base

)

SELECT
    *,

    planned_due_date
        + illustrative_replenishment_delay_days
        AS illustrative_replenishment_due_date,

    CASE
        WHEN readiness_status = 'BLOCKED'
            THEN 'NEW_STANDARD_PO_AT_SNAPSHOT'
        ELSE 'NO_NEW_PO_REQUIRED'
    END AS schedule_model_assumption

FROM delays;


-- ============================================================
-- 3. COMPONENT PRODUCTION BLAST RADIUS
-- ============================================================

CREATE OR REPLACE TABLE planning.component_blast_radius AS

WITH family_exposure AS (

    SELECT
        component_part_id,
        component_revision,

        COUNT(DISTINCT product_family_id)
            AS affected_product_families

    FROM planning.shortage_exceptions

    GROUP BY
        component_part_id,
        component_revision

)

SELECT
    p.shortage_rank,
    p.component_part_id,
    p.component_revision,
    p.part_description,
    p.supplier_id,
    p.supplier_name,

    p.affected_orders,
    f.affected_product_families,
    p.high_priority_orders,

    p.total_shortage_units,
    p.modeled_missing_material_value_usd,

    p.risk_score,
    p.shortage_severity

FROM planning.shortage_priority p

JOIN family_exposure f
    ON p.component_part_id = f.component_part_id
   AND p.component_revision = f.component_revision;


-- ============================================================
-- 4. PRODUCTION IMPACT BY PRODUCT FAMILY
-- ============================================================

CREATE OR REPLACE TABLE planning.family_production_exposure AS

SELECT
    product_family_id,

    COUNT(*) AS total_orders,

    COUNT(*) FILTER (
        WHERE readiness_status = 'MATERIAL_READY'
    ) AS ready_orders,

    COUNT(*) FILTER (
        WHERE readiness_status = 'AT_RISK'
    ) AS at_risk_orders,

    COUNT(*) FILTER (
        WHERE readiness_status = 'BLOCKED'
    ) AS blocked_orders,

    SUM(total_missing_component_units)
        AS total_missing_component_units,

    CAST(
        SUM(modeled_missing_material_value_usd)
        AS DECIMAL(18,2)
    ) AS modeled_missing_material_value_usd,

    SUM(illustrative_replenishment_delay_days)
        AS illustrative_delay_days,

    ROUND(
        100.0 * COUNT(*) FILTER (
            WHERE readiness_status = 'BLOCKED'
        ) / NULLIF(COUNT(*), 0),
        2
    ) AS blocked_order_pct

FROM planning.production_impact

GROUP BY product_family_id;


-- ============================================================
-- 5. EXECUTIVE PRODUCTION IMPACT KPIs
-- ============================================================

CREATE OR REPLACE VIEW planning.production_impact_kpis AS

SELECT
    COUNT(*) AS total_production_orders,

    COUNT(*) FILTER (
        WHERE readiness_status = 'MATERIAL_READY'
    ) AS ready_orders,

    COUNT(*) FILTER (
        WHERE readiness_status = 'AT_RISK'
    ) AS at_risk_orders,

    COUNT(*) FILTER (
        WHERE readiness_status = 'BLOCKED'
    ) AS blocked_orders,

    COUNT(*) FILTER (
        WHERE illustrative_replenishment_delay_days > 0
    ) AS orders_with_illustrative_delay,

    SUM(illustrative_replenishment_delay_days)
        AS illustrative_total_order_delay_days,

    SUM(total_missing_component_units)
        AS total_missing_component_units,

    CAST(
        SUM(modeled_missing_material_value_usd)
        AS DECIMAL(18,2)
    ) AS modeled_missing_material_value_usd

FROM planning.production_impact;

COMMIT;
