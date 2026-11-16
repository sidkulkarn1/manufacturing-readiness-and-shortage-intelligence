-- BUSINESS OBJECTIVE:
-- Match the scheduling outcome of EXPEDITE_ALL while
-- minimizing the number and cost of expedited shortage lines.
--
-- Assumptions:
-- - Existing SQL07 lead times and procurement costs apply.
-- - Each shortage line can use standard or expedited supply.
-- - No shared supplier capacity or factory sequencing
--   constraints are modeled in this version.
-- - All outcomes are synthetic and illustrative.

BEGIN TRANSACTION;

-- ============================================================
-- 1. COMPARE STANDARD AND EXPEDITED PROCUREMENT
-- ============================================================

CREATE OR REPLACE TABLE planning.targeted_expediting_decisions AS

WITH paired_options AS (

    SELECT
        s.production_order_id,
        s.component_part_id,
        s.component_revision,
        s.sourced_qty,

        o.planned_start_date,

        s.expected_arrival_date
            AS standard_arrival_date,

        e.expected_arrival_date
            AS expedited_arrival_date,

        s.modeled_procurement_cost_usd
            AS standard_cost_usd,

        e.modeled_procurement_cost_usd
            AS expedited_cost_usd

    FROM planning.recovery_procurement s

    JOIN planning.recovery_procurement e
        ON s.production_order_id = e.production_order_id
       AND s.component_part_id = e.component_part_id
       AND s.component_revision = e.component_revision
       AND e.scenario_id = 'EXPEDITE_ALL'

    JOIN core.production_orders o
        ON s.production_order_id = o.production_order_id

    WHERE s.scenario_id = 'STANDARD_PO'
),

benchmark AS (

    SELECT
        *,

        GREATEST(
            planned_start_date,

            MAX(expedited_arrival_date) OVER (
                PARTITION BY production_order_id
            )
        ) AS full_expediting_start_date

    FROM paired_options

),

decisions AS (

    SELECT
        *,

        CASE
            WHEN standard_arrival_date >
                 full_expediting_start_date
                THEN 'EXPEDITE'
            ELSE 'STANDARD'
        END AS selected_action

    FROM benchmark
)

SELECT
    production_order_id,
    component_part_id,
    component_revision,
    sourced_qty,

    planned_start_date,
    full_expediting_start_date,

    standard_arrival_date,
    expedited_arrival_date,

    standard_cost_usd,
    expedited_cost_usd,

    selected_action,

    CASE
        WHEN selected_action = 'EXPEDITE'
            THEN expedited_arrival_date
        ELSE standard_arrival_date
    END AS selected_arrival_date,

    CAST(
        CASE
            WHEN selected_action = 'EXPEDITE'
                THEN expedited_cost_usd
            ELSE standard_cost_usd
        END AS DECIMAL(18,2)
    ) AS selected_cost_usd,

    CAST(
        CASE
            WHEN selected_action = 'EXPEDITE'
                THEN expedited_cost_usd - standard_cost_usd
            ELSE 0
        END AS DECIMAL(18,2)
    ) AS additional_spend_usd

FROM decisions;


-- ============================================================
-- 2. CALCULATE ORDER-LEVEL RECOVERY RESULTS
-- ============================================================

CREATE OR REPLACE TABLE planning.targeted_expediting_orders AS

WITH procurement_summary AS (

    SELECT
        production_order_id,

        COUNT(*) AS shortage_lines,

        COUNT(*) FILTER (
            WHERE selected_action = 'EXPEDITE'
        ) AS expedited_lines,

        MAX(selected_arrival_date)
            AS latest_selected_arrival_date,

        CAST(
            SUM(selected_cost_usd)
            AS DECIMAL(18,2)
        ) AS procurement_cost_usd,

        CAST(
            SUM(additional_spend_usd)
            AS DECIMAL(18,2)
        ) AS additional_spend_usd

    FROM planning.targeted_expediting_decisions

    GROUP BY production_order_id

),

order_dates AS (

    SELECT
        o.production_order_id,
        o.finished_good_id,
        o.product_family_id,
        o.priority,
        o.planned_start_date,
        o.planned_due_date,

        i.readiness_status,

        i.illustrative_replenishment_delay_days
            AS standard_delay_days,

        COALESCE(p.shortage_lines, 0)
            AS shortage_lines,

        COALESCE(p.expedited_lines, 0)
            AS expedited_lines,

        COALESCE(p.procurement_cost_usd, 0)
            AS procurement_cost_usd,

        COALESCE(p.additional_spend_usd, 0)
            AS additional_spend_usd,

        CASE
            WHEN i.readiness_status = 'BLOCKED'
                THEN GREATEST(
                    o.planned_start_date,
                    p.latest_selected_arrival_date
                )
            ELSE o.planned_start_date
        END AS recovery_start_date

    FROM core.production_orders o

    JOIN planning.production_impact i
        ON o.production_order_id = i.production_order_id

    LEFT JOIN procurement_summary p
        ON o.production_order_id = p.production_order_id

)

SELECT
    *,

    CAST(
        date_diff(
            'day',
            planned_start_date,
            recovery_start_date
        ) AS INTEGER
    ) AS recovery_delay_days,

    CAST(
        date_diff(
            'day',
            planned_start_date,
            recovery_start_date
        ) AS INTEGER
    ) AS recovery_due_date_shift_days,

    standard_delay_days
      - CAST(
            date_diff(
                'day',
                planned_start_date,
                recovery_start_date
            ) AS INTEGER
        ) AS delay_days_reduced

FROM order_dates;


-- ============================================================
-- 3. EXECUTIVE TARGETED RECOVERY KPIs
-- ============================================================

CREATE OR REPLACE VIEW planning.targeted_expediting_kpis AS

WITH order_summary AS (

    SELECT
        COUNT(*) AS production_orders,

        COUNT(*) FILTER (
            WHERE recovery_delay_days = 0
        ) AS on_time_orders,

        COUNT(*) FILTER (
            WHERE recovery_delay_days > 0
        ) AS delayed_orders,

        SUM(standard_delay_days)
            AS standard_delay_days,

        SUM(recovery_delay_days)
            AS targeted_delay_days,

        SUM(delay_days_reduced)
            AS delay_days_reduced,

        SUM(shortage_lines)
            AS total_shortage_lines,

        SUM(expedited_lines)
            AS expedited_lines,

        CAST(
            SUM(procurement_cost_usd)
            AS DECIMAL(18,2)
        ) AS procurement_cost_usd,

        CAST(
            SUM(additional_spend_usd)
            AS DECIMAL(18,2)
        ) AS additional_spend_usd

    FROM planning.targeted_expediting_orders

),

benchmark AS (

    SELECT
        modeled_total_order_delay_days
            AS expedite_all_delay_days,

        modeled_procurement_cost_usd
            AS expedite_all_procurement_cost_usd,

        additional_spend_vs_standard_usd
            AS expedite_all_additional_spend_usd

    FROM planning.recovery_scenario_kpis

    WHERE scenario_id = 'EXPEDITE_ALL'
)

SELECT
    s.*,

    b.expedite_all_delay_days,
    b.expedite_all_additional_spend_usd,

    CAST(
        b.expedite_all_procurement_cost_usd
        - s.procurement_cost_usd
        AS DECIMAL(18,2)
    ) AS savings_vs_expedite_all_usd

FROM order_summary s

CROSS JOIN benchmark b;

COMMIT;
