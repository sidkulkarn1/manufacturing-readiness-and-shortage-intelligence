-- Compare three independent procurement strategies:
-- 1. STANDARD_PO: Standard replenishment
-- 2. EXPEDITE_ALL: Expedited primary supplier purchases
-- 3. QUALIFIED_ALTERNATE: Approved alternate sourcing
--    with standard-supplier fallback.
--
-- Assumptions:
-- All new purchases are placed at the planning snapshot.
-- Expediting reduces lead time by 35% and adds 25% cost.
-- Alternate sourcing uses approved revisions, quoted
-- lead times, prices and total available quantities.
-- Existing reservations and covered demand are protected.
-- Every shortage unit must receive one sourcing assignment.
-- Supplier expediting capability is assumed, not verified.
-- These scenarios do not model plant capacity or labor.
--
-- Cost results represent modeled procurement expenditures,
-- not actual savings, profit, or avoided revenue losses.

BEGIN TRANSACTION;

CREATE SCHEMA IF NOT EXISTS planning;


-- ============================================================
-- 1. PREPARE SHORTAGE RECOVERY DEMAND
-- ============================================================

CREATE OR REPLACE TABLE planning.recovery_demand AS

WITH snapshot AS (
    SELECT MAX(snapshot_date) AS snapshot_date
    FROM core.inventory
),

sequenced AS (
    SELECT
        e.production_order_id,
        e.component_part_id,
        e.component_revision,
        e.material_required_date,
        e.order_priority,

        e.shortage_qty::BIGINT AS shortage_qty,
        e.unit_cost_usd AS base_unit_cost_usd,
        p.lead_time_days,
        s.snapshot_date,

        a.alternate_supplier_id,
        a.quoted_lead_time_days,
        a.quoted_unit_cost_usd,
        a.max_available_qty,

        COALESCE(
            SUM(e.shortage_qty) OVER (
                PARTITION BY
                    e.component_part_id,
                    e.component_revision
                ORDER BY
                    e.material_required_date,
                    CASE e.order_priority
                        WHEN 'HIGH' THEN 1
                        WHEN 'MEDIUM' THEN 2
                        ELSE 3
                    END,
                    e.production_order_id
                ROWS BETWEEN UNBOUNDED PRECEDING
                    AND 1 PRECEDING
            ), 0
        )::BIGINT AS earlier_shortage_units

    FROM planning.shortage_exceptions e

    JOIN core.part_master p
        ON e.component_part_id = p.part_id
       AND e.component_revision = p.revision

    CROSS JOIN snapshot s

    LEFT JOIN core.approved_alternates a
        ON e.component_part_id = a.part_id
       AND e.component_revision = a.approved_revision
       AND a.approval_status = 'APPROVED'
       AND a.qualification_date <= s.snapshot_date
)

SELECT
    *,

    CASE
        WHEN alternate_supplier_id IS NOT NULL
        THEN LEAST(
            shortage_qty,
            GREATEST(
                0,
                max_available_qty - earlier_shortage_units
            )
        )
        ELSE 0
    END::BIGINT AS alternate_allocated_qty,

    GREATEST(
        1,
        CEIL(lead_time_days * 0.65)::INTEGER
    ) AS expedited_lead_time_days

FROM sequenced;


-- ============================================================
-- 2. GENERATE PROCUREMENT OPTIONS
-- ============================================================

CREATE OR REPLACE TABLE planning.recovery_procurement AS

WITH options AS (

    -- Scenario 1: Standard new purchase orders
    SELECT
        'STANDARD_PO' AS scenario_id,
        production_order_id,
        component_part_id,
        component_revision,
        'PRIMARY_STANDARD' AS source_type,
        shortage_qty AS sourced_qty,
        snapshot_date + lead_time_days
            AS expected_arrival_date,
        base_unit_cost_usd AS scenario_unit_cost_usd,
        base_unit_cost_usd

    FROM planning.recovery_demand

    UNION ALL

    -- Scenario 2: Expedited primary supplier purchases
    SELECT
        'EXPEDITE_ALL' AS scenario_id,
        production_order_id,
        component_part_id,
        component_revision,
        'PRIMARY_EXPEDITED' AS source_type,
        shortage_qty AS sourced_qty,
        snapshot_date + expedited_lead_time_days
            AS expected_arrival_date,
        ROUND(
            base_unit_cost_usd * 1.25, 2
        )::DECIMAL(14,2) AS scenario_unit_cost_usd,
        base_unit_cost_usd

    FROM planning.recovery_demand

    UNION ALL

    -- Scenario 3A: Qualified alternate supplier
    SELECT
        'QUALIFIED_ALTERNATE' AS scenario_id,
        production_order_id,
        component_part_id,
        component_revision,
        'QUALIFIED_ALTERNATE' AS source_type,
        alternate_allocated_qty AS sourced_qty,
        snapshot_date + quoted_lead_time_days
            AS expected_arrival_date,
        quoted_unit_cost_usd AS scenario_unit_cost_usd,
        base_unit_cost_usd

    FROM planning.recovery_demand
    WHERE alternate_allocated_qty > 0

    UNION ALL

    -- Scenario 3B: Primary supplier fills remaining demand
    SELECT
        'QUALIFIED_ALTERNATE' AS scenario_id,
        production_order_id,
        component_part_id,
        component_revision,
        'PRIMARY_STANDARD' AS source_type,
        shortage_qty - alternate_allocated_qty
            AS sourced_qty,
        snapshot_date + lead_time_days
            AS expected_arrival_date,
        base_unit_cost_usd AS scenario_unit_cost_usd,
        base_unit_cost_usd

    FROM planning.recovery_demand
    WHERE shortage_qty - alternate_allocated_qty > 0
)

SELECT
    *,

    CAST(
        sourced_qty * scenario_unit_cost_usd
        AS DECIMAL(18,2)
    ) AS modeled_procurement_cost_usd,

    CAST(
        sourced_qty * (
            scenario_unit_cost_usd - base_unit_cost_usd
        )
        AS DECIMAL(18,2)
    ) AS modeled_incremental_premium_usd

FROM options;


-- ============================================================
-- 3. CALCULATE ORDER-LEVEL RECOVERY IMPACT
-- ============================================================

CREATE OR REPLACE TABLE planning.recovery_order_scenarios AS

WITH scenarios AS (
    SELECT scenario_id
    FROM (
        VALUES
            ('STANDARD_PO'),
            ('EXPEDITE_ALL'),
            ('QUALIFIED_ALTERNATE')
    ) AS v(scenario_id)
),

arrivals AS (
    SELECT
        scenario_id,
        production_order_id,
        MAX(expected_arrival_date)
            AS latest_recovery_arrival_date

    FROM planning.recovery_procurement

    GROUP BY
        scenario_id,
        production_order_id
),

order_comparison AS (
    SELECT
        s.scenario_id,

        p.production_order_id,
        p.finished_good_id,
        p.product_family_id,
        p.priority,
        p.readiness_status,

        p.planned_start_date,
        p.planned_due_date,

        p.shortage_component_count,

        p.illustrative_replenishment_delay_days
            AS standard_reference_delay_days,

        a.latest_recovery_arrival_date,

        CASE
            WHEN p.readiness_status = 'BLOCKED'
            THEN GREATEST(
                0,
                date_diff(
                    'day',
                    p.planned_start_date,
                    a.latest_recovery_arrival_date
                )
            )
            ELSE 0
        END::INTEGER AS scenario_delay_days

    FROM planning.production_impact p

    CROSS JOIN scenarios s

    LEFT JOIN arrivals a
        ON s.scenario_id = a.scenario_id
       AND p.production_order_id =
           a.production_order_id
)

SELECT
    *,

    planned_start_date + scenario_delay_days
        AS scenario_start_date,

    planned_due_date + scenario_delay_days
        AS scenario_due_date

FROM order_comparison;


-- ============================================================
-- 4. SCENARIO-LEVEL COST AND SCHEDULE KPIs
-- ============================================================

CREATE OR REPLACE TABLE planning.recovery_scenario_kpis AS

WITH schedule_summary AS (
    SELECT
        scenario_id,

        COUNT(*) AS production_orders,

        COUNT(*) FILTER (
            WHERE scenario_delay_days = 0
        ) AS on_time_orders,

        COUNT(*) FILTER (
            WHERE scenario_delay_days > 0
        ) AS delayed_orders,

        COUNT(*) FILTER (
            WHERE readiness_status = 'BLOCKED'
              AND scenario_delay_days = 0
        ) AS formerly_blocked_orders_on_time,

        SUM(scenario_delay_days)
            AS modeled_total_order_delay_days,

        SUM(standard_reference_delay_days)
            AS reference_total_order_delay_days

    FROM planning.recovery_order_scenarios

    GROUP BY scenario_id
),

cost_summary AS (
    SELECT
        scenario_id,

        SUM(sourced_qty)::BIGINT
            AS purchased_component_units,

        CAST(
            SUM(modeled_procurement_cost_usd)
            AS DECIMAL(18,2)
        ) AS modeled_procurement_cost_usd,

        CAST(
            SUM(modeled_incremental_premium_usd)
            AS DECIMAL(18,2)
        ) AS modeled_incremental_premium_usd

    FROM planning.recovery_procurement

    GROUP BY scenario_id
),

standard_reference AS (
    SELECT
        modeled_procurement_cost_usd
            AS standard_procurement_cost_usd
    FROM cost_summary
    WHERE scenario_id = 'STANDARD_PO'
)

SELECT
    s.scenario_id,
    s.production_orders,
    s.on_time_orders,
    s.delayed_orders,
    s.formerly_blocked_orders_on_time,

    s.modeled_total_order_delay_days,
    s.reference_total_order_delay_days,

    (
        s.reference_total_order_delay_days
        - s.modeled_total_order_delay_days
    ) AS modeled_order_delay_days_reduced,

    c.purchased_component_units,
    c.modeled_procurement_cost_usd,
    c.modeled_incremental_premium_usd,

    CAST(
        c.modeled_procurement_cost_usd
        - r.standard_procurement_cost_usd
        AS DECIMAL(18,2)
    ) AS additional_spend_vs_standard_usd

FROM schedule_summary s

JOIN cost_summary c
    ON s.scenario_id = c.scenario_id

CROSS JOIN standard_reference r;


-- ============================================================
-- 5. REPORTING VIEW
-- ============================================================

CREATE OR REPLACE VIEW planning.recovery_comparison AS

SELECT
    scenario_id,
    production_orders,
    on_time_orders,
    delayed_orders,
    formerly_blocked_orders_on_time,
    modeled_total_order_delay_days,
    modeled_order_delay_days_reduced,
    purchased_component_units,
    modeled_procurement_cost_usd,
    additional_spend_vs_standard_usd

FROM planning.recovery_scenario_kpis;

COMMIT;

-- ============================================================
-- END SQL07
-- ============================================================
