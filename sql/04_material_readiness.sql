-- Business Objective:
-- Determine which scheduled production orders have sufficient
-- usable materials, accounting for inventory reservations,
-- quality holds, supplier receipts, and requirement dates.
--
-- Allocation Policy:
-- 1. Protect existing production-order reservations.
-- 2. Exclude quality-held inventory.
-- 3. Allocate remaining supply by material requirement date.
-- 4. Use production priority to break same-date ties.
-- 5. Count supplier receipts only by their expected arrival.
-- 6. Never allocate the same available supply twice.
-- 7. Do not consume stock for previously unfulfilled demand.
--
-- All manufacturing records are synthetic.

BEGIN TRANSACTION;

CREATE SCHEMA IF NOT EXISTS planning;


-- ============================================================
-- 1. INVENTORY POSITION
-- ============================================================

CREATE OR REPLACE TABLE planning.inventory_position AS

WITH stock AS (

    SELECT
        part_id,
        revision,
        SUM(on_hand_qty)::BIGINT
            AS on_hand_qty,
        SUM(quality_hold_qty)::BIGINT
            AS quality_hold_qty

    FROM core.inventory

    GROUP BY
        part_id,
        revision

),

reservations AS (

    SELECT
        part_id,
        revision,
        SUM(allocated_qty)::BIGINT
            AS total_reserved_qty

    FROM core.inventory_allocations

    GROUP BY
        part_id,
        revision

)

SELECT
    p.part_id,
    p.revision,

    COALESCE(s.on_hand_qty, 0)::BIGINT
        AS on_hand_qty,

    COALESCE(s.quality_hold_qty, 0)::BIGINT
        AS quality_hold_qty,

    COALESCE(r.total_reserved_qty, 0)::BIGINT
        AS total_reserved_qty,

    (
        COALESCE(s.on_hand_qty, 0)
        - COALESCE(s.quality_hold_qty, 0)
        - COALESCE(r.total_reserved_qty, 0)
    )::BIGINT AS free_stock_qty

FROM core.part_master p

LEFT JOIN stock s
    ON p.part_id = s.part_id
   AND p.revision = s.revision

LEFT JOIN reservations r
    ON p.part_id = r.part_id
   AND p.revision = r.revision

WHERE p.part_type = 'PURCHASED_COMPONENT';


-- ============================================================
-- 2. EXISTING PRODUCTION ORDER RESERVATIONS
-- ============================================================

CREATE OR REPLACE TABLE planning.order_reservations AS

SELECT
    production_order_id,
    part_id,
    revision,

    SUM(allocated_qty)::BIGINT
        AS reserved_qty

FROM core.inventory_allocations

GROUP BY
    production_order_id,
    part_id,
    revision;


-- ============================================================
-- 3. INCOMING SUPPLIER RECEIPT SCHEDULE
-- ============================================================

CREATE OR REPLACE TABLE planning.receipt_schedule AS

SELECT
    part_id,
    revision,
    expected_receipt_date,

    SUM(ordered_qty)::BIGINT
        AS inbound_qty

FROM core.purchase_orders

WHERE order_status = 'OPEN'

GROUP BY
    part_id,
    revision,
    expected_receipt_date;


-- ============================================================
-- 4. PRODUCTION MATERIAL DEMAND QUEUE
-- ============================================================

CREATE OR REPLACE TABLE planning.demand_queue AS

WITH demand AS (

    SELECT
        r.production_order_id,
        r.component_part_id,
        r.component_revision,
        r.material_required_date,
        o.priority,

        r.gross_required_qty,

        COALESCE(a.reserved_qty, 0)::BIGINT
            AS reserved_qty,

        (
            r.gross_required_qty
            - COALESCE(a.reserved_qty, 0)
        )::BIGINT AS unreserved_requirement_qty

    FROM planning.component_requirements r

    JOIN core.production_orders o
        ON r.production_order_id
         = o.production_order_id

    LEFT JOIN planning.order_reservations a
        ON r.production_order_id
         = a.production_order_id
       AND r.component_part_id = a.part_id
       AND r.component_revision = a.revision

)

SELECT
    d.*,

    COALESCE(
        SUM(d.unreserved_requirement_qty) OVER (
            PARTITION BY
                d.component_part_id,
                d.component_revision

            ORDER BY
                d.material_required_date,

                CASE d.priority
                    WHEN 'HIGH' THEN 1
                    WHEN 'MEDIUM' THEN 2
                    ELSE 3
                END,

                d.production_order_id

            ROWS BETWEEN UNBOUNDED PRECEDING
                 AND 1 PRECEDING
        ),
        0
    )::BIGINT AS prior_unreserved_demand_qty

FROM demand d;


-- ============================================================
-- 5. TIME-PHASED MATERIAL ALLOCATION
-- ============================================================

-- This section replaces the earlier allocation approach.
--
-- Rather than subtracting all earlier demand, the recursive
-- allocation tracks only quantities actually covered.
--
-- If an earlier order cannot be fully supplied, its unmet
-- quantity is recorded as a shortage rather than consuming
-- material that does not exist.
--
-- Later receipts may therefore support later orders.
-- Unmet demand is not automatically backordered.

CREATE OR REPLACE TABLE planning.component_readiness AS

WITH RECURSIVE eligible_supply AS (

    SELECT
        q.*,

        i.free_stock_qty,

        COALESCE((
            SELECT SUM(po.inbound_qty)

            FROM planning.receipt_schedule po

            WHERE po.part_id = q.component_part_id
              AND po.revision = q.component_revision
              AND po.expected_receipt_date
                  <= q.material_required_date

        ), 0)::BIGINT AS inbound_qty_by_date,

        ROW_NUMBER() OVER (

            PARTITION BY
                q.component_part_id,
                q.component_revision

            ORDER BY
                q.material_required_date,

                CASE q.priority
                    WHEN 'HIGH' THEN 1
                    WHEN 'MEDIUM' THEN 2
                    ELSE 3
                END,

                q.production_order_id

        ) AS queue_position

    FROM planning.demand_queue q

    JOIN planning.inventory_position i
        ON q.component_part_id = i.part_id
       AND q.component_revision = i.revision

),

allocation AS (

    -- --------------------------------------------------------
    -- Initial allocation for the first order per component
    -- --------------------------------------------------------

    SELECT
        e.*,

        0::BIGINT AS prior_covered_qty,

        LEAST(
            e.unreserved_requirement_qty,

            GREATEST(
                0,
                e.free_stock_qty
                + e.inbound_qty_by_date
            )

        )::BIGINT AS covered_unreserved_qty

    FROM eligible_supply e

    WHERE e.queue_position = 1

    UNION ALL

    -- --------------------------------------------------------
    -- Allocate remaining supply to subsequent orders
    -- --------------------------------------------------------

    SELECT
        e.*,

        (
            a.prior_covered_qty
            + a.covered_unreserved_qty
        )::BIGINT AS prior_covered_qty,

        LEAST(
            e.unreserved_requirement_qty,

            GREATEST(
                0,

                e.free_stock_qty
                + e.inbound_qty_by_date
                - a.prior_covered_qty
                - a.covered_unreserved_qty
            )

        )::BIGINT AS covered_unreserved_qty

    FROM eligible_supply e

    JOIN allocation a
        ON e.component_part_id
         = a.component_part_id
       AND e.component_revision
         = a.component_revision
       AND e.queue_position
         = a.queue_position + 1

),

final_calculation AS (

    SELECT
        *,

        LEAST(
            covered_unreserved_qty,

            GREATEST(
                0,
                free_stock_qty
                - prior_covered_qty
            )

        )::BIGINT AS covered_from_stock_only_qty,

        (
            unreserved_requirement_qty
            - covered_unreserved_qty
        )::BIGINT AS shortage_qty

    FROM allocation

)

SELECT
    production_order_id,
    component_part_id,
    component_revision,
    material_required_date,
    priority,

    gross_required_qty,
    reserved_qty,
    unreserved_requirement_qty,

    prior_unreserved_demand_qty,
    free_stock_qty,
    inbound_qty_by_date,

    covered_unreserved_qty,
    covered_from_stock_only_qty,
    shortage_qty,

    CASE

        WHEN shortage_qty > 0
            THEN 'SHORTAGE'

        WHEN covered_unreserved_qty
             > covered_from_stock_only_qty
            THEN 'INBOUND_DEPENDENT'

        ELSE 'STOCK_COVERED'

    END AS component_status

FROM final_calculation;


-- ============================================================
-- 6. PRODUCTION ORDER READINESS CLASSIFICATION
-- ============================================================

CREATE OR REPLACE TABLE planning.production_order_readiness AS

WITH summary AS (

    SELECT
        o.production_order_id,
        o.finished_good_id,
        o.product_family_id,
        o.order_quantity,
        o.planned_week,
        o.material_required_date,
        o.planned_due_date,
        o.priority,

        COUNT(c.component_part_id)
            AS required_component_count,

        COALESCE(
            SUM(
                CASE
                    WHEN c.shortage_qty > 0
                    THEN 1
                    ELSE 0
                END
            ),
            0
        ) AS shortage_component_count,

        COALESCE(
            SUM(c.shortage_qty),
            0
        ) AS total_shortage_units,

        COALESCE(
            SUM(
                CASE
                    WHEN c.component_status
                         = 'INBOUND_DEPENDENT'
                    THEN 1
                    ELSE 0
                END
            ),
            0
        ) AS inbound_dependent_component_count

    FROM core.production_orders o

    LEFT JOIN planning.component_readiness c
        ON o.production_order_id
         = c.production_order_id

    GROUP BY
        o.production_order_id,
        o.finished_good_id,
        o.product_family_id,
        o.order_quantity,
        o.planned_week,
        o.material_required_date,
        o.planned_due_date,
        o.priority

)

SELECT
    *,

    CASE

        WHEN required_component_count = 0
            THEN 'BLOCKED'

        WHEN shortage_component_count > 0
            THEN 'BLOCKED'

        WHEN inbound_dependent_component_count > 0
            THEN 'AT_RISK'

        ELSE 'MATERIAL_READY'

    END AS readiness_status

FROM summary;


-- ============================================================
-- 7. EXECUTIVE MANUFACTURING READINESS KPIs
-- ============================================================

CREATE OR REPLACE VIEW planning.readiness_kpis AS

SELECT

    COUNT(*)
        AS total_production_orders,

    COUNT(*) FILTER (
        WHERE readiness_status = 'MATERIAL_READY'
    ) AS ready_orders,

    COUNT(*) FILTER (
        WHERE readiness_status = 'AT_RISK'
    ) AS at_risk_orders,

    COUNT(*) FILTER (
        WHERE readiness_status = 'BLOCKED'
    ) AS blocked_orders,

    ROUND(
        100.0 * COUNT(*) FILTER (
            WHERE readiness_status = 'MATERIAL_READY'
        ) / NULLIF(COUNT(*), 0),
        2
    ) AS readiness_rate_pct

FROM planning.production_order_readiness;


COMMIT;

-- ============================================================
-- END SQL04
-- ============================================================
