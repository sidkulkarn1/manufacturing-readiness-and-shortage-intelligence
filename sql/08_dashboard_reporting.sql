-- All source records and modeled results are synthetic.
-- Views do not modify baseline manufacturing data.

BEGIN TRANSACTION;

CREATE SCHEMA IF NOT EXISTS reporting;


-- ============================================================
-- 1. PRODUCTION ORDER READINESS
-- ============================================================

CREATE OR REPLACE VIEW reporting.readiness_orders AS

SELECT
    o.production_order_id,
    o.finished_good_id,
    o.product_family_id,
    o.production_site_id,
    o.priority,
    o.order_quantity,
    o.planned_week,
    o.planned_start_date,
    o.material_required_date,
    o.planned_due_date,

    r.readiness_status,
    r.required_component_count,
    r.shortage_component_count,
    r.total_shortage_units,
    r.inbound_dependent_component_count

FROM core.production_orders o

JOIN planning.production_order_readiness r
    ON o.production_order_id = r.production_order_id;


-- ============================================================
-- 2. WEEKLY MATERIAL READINESS
-- ============================================================

CREATE OR REPLACE VIEW reporting.weekly_readiness AS

SELECT
    planned_week,

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

    SUM(total_shortage_units)
        AS missing_component_units,

    ROUND(
        100.0 * COUNT(*) FILTER (
            WHERE readiness_status = 'MATERIAL_READY'
        ) / NULLIF(COUNT(*), 0),
        2
    ) AS readiness_rate_pct

FROM reporting.readiness_orders

GROUP BY planned_week;


-- ============================================================
-- 3. DETAILED SHORTAGE EXCEPTIONS
-- ============================================================

CREATE OR REPLACE VIEW reporting.shortage_detail AS

SELECT
    e.production_order_id,
    e.finished_good_id,
    e.product_family_id,
    e.order_priority,
    e.material_required_date,

    e.component_part_id,
    e.component_revision,
    e.part_description,
    e.component_category,

    e.supplier_id,
    e.supplier_name,
    e.lead_time_days,

    e.shortage_qty,
    e.unit_cost_usd,
    e.modeled_missing_material_value_usd,
    e.days_to_requirement,

    p.shortage_rank,
    p.risk_score,
    p.shortage_severity

FROM planning.shortage_exceptions e

JOIN planning.shortage_priority p
    ON e.component_part_id = p.component_part_id
   AND e.component_revision = p.component_revision;


-- ============================================================
-- 4. SUPPLIER SHORTAGE EXPOSURE
-- ============================================================

CREATE OR REPLACE VIEW reporting.supplier_risk AS

SELECT
    s.supplier_id,
    s.supplier_name,
    s.region,

    COALESCE(p.short_components, 0)
        AS short_components,

    COALESCE(p.affected_production_orders, 0)
        AS affected_production_orders,

    COALESCE(p.shortage_exception_lines, 0)
        AS shortage_exception_lines,

    COALESCE(p.total_shortage_units, 0)
        AS total_shortage_units,

    COALESCE(
        p.modeled_missing_material_value_usd, 0
    ) AS modeled_missing_material_value_usd,

    p.earliest_material_required_date,
    p.longest_component_lead_time_days

FROM core.suppliers s

LEFT JOIN planning.supplier_shortage_exposure p
    ON s.supplier_id = p.supplier_id;


-- ============================================================
-- 5. PRODUCTION IMPACT & TARGETED RECOVERY
-- ============================================================

CREATE OR REPLACE VIEW reporting.production_recovery AS

SELECT
    p.production_order_id,
    p.finished_good_id,
    p.product_family_id,
    p.priority,
    p.readiness_status,

    p.planned_start_date,
    p.planned_due_date,

    p.shortage_component_count,
    p.total_missing_component_units,

    p.illustrative_replenishment_delay_days
        AS standard_delay_days,

    t.recovery_start_date
        AS targeted_recovery_start_date,

    t.recovery_delay_days
        AS targeted_delay_days,

    t.delay_days_reduced,

    t.expedited_lines,

    t.procurement_cost_usd,
    t.additional_spend_usd

FROM planning.production_impact p

JOIN planning.targeted_expediting_orders t
    ON p.production_order_id = t.production_order_id;


-- ============================================================
-- 6. PROCUREMENT RECOVERY SCENARIO COMPARISON
-- ============================================================

CREATE OR REPLACE VIEW reporting.recovery_comparison AS

SELECT
    scenario_id,
    on_time_orders,
    delayed_orders,

    modeled_total_order_delay_days
        AS modeled_order_delay_days,

    modeled_order_delay_days_reduced
        AS delay_days_reduced,

    modeled_procurement_cost_usd
        AS procurement_cost_usd,

    additional_spend_vs_standard_usd,

    'SIMULATED_PROCUREMENT_SCENARIO'
        AS evidence_level

FROM planning.recovery_scenario_kpis

UNION ALL

SELECT
    'TARGETED_EXPEDITING' AS scenario_id,

    on_time_orders,
    delayed_orders,

    targeted_delay_days AS modeled_order_delay_days,

    delay_days_reduced,

    procurement_cost_usd,

    additional_spend_usd
        AS additional_spend_vs_standard_usd,

    'SIMULATED_TARGETED_PROCUREMENT'
        AS evidence_level

FROM planning.targeted_expediting_kpis;


-- ============================================================
-- 7. NON-PROCUREMENT ACTION FEASIBILITY
-- ============================================================

CREATE OR REPLACE VIEW reporting.action_screening AS

SELECT *
FROM planning.nonprocurement_action_screening;


-- ============================================================
-- 8. EXECUTIVE KPI SUMMARY
-- ============================================================

CREATE OR REPLACE VIEW reporting.executive_kpis AS

SELECT
    r.total_production_orders,
    r.ready_orders,
    r.at_risk_orders,
    r.blocked_orders,
    r.readiness_rate_pct,

    s.unique_short_components,
    s.shortage_exception_lines,
    s.total_shortage_units,
    s.critical_short_components,

    s.modeled_missing_material_value_usd,

    p.illustrative_total_order_delay_days
        AS standard_reference_delay_days,

    t.targeted_delay_days,
    t.delay_days_reduced,

    t.total_shortage_lines,
    t.expedited_lines,

    t.procurement_cost_usd
        AS targeted_procurement_cost_usd,

    t.additional_spend_usd
        AS targeted_additional_spend_usd,

    t.savings_vs_expedite_all_usd

FROM planning.readiness_kpis r

CROSS JOIN planning.shortage_kpis s

CROSS JOIN planning.production_impact_kpis p

CROSS JOIN planning.targeted_expediting_kpis t;


-- ============================================================
-- 9. PRODUCT FAMILY EXPOSURE
-- ============================================================

CREATE OR REPLACE VIEW reporting.family_summary AS

SELECT *
FROM planning.family_production_exposure;


-- ============================================================
-- 10. RANKED COMPONENT SHORTAGES
-- ============================================================

CREATE OR REPLACE VIEW reporting.shortage_priority AS

SELECT *
FROM planning.shortage_priority;

COMMIT;
