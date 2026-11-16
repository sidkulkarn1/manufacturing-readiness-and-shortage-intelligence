
-- Reallocation rules:
-- 1. Same part and approved revision.
-- 2. Same production site.
-- 3. Donor has a later material requirement date.
-- 4. Donor has lower operational priority.
-- 5. Transfer cannot exceed the donor reservation or
--    recipient shortage for an individual candidate.
--
-- Resequencing rules:
-- 1. Blocked order exchanges slots with a later ready order.
-- 2. Both orders belong to the same production site.
-- 3. Blocked order is materially recoverable by later slot.
-- 4. Later slot lies before the blocked order's due date.
--
-- Candidates require subsequent full schedule feasibility
-- and donor-impact evaluation before execution.

BEGIN TRANSACTION;

CREATE SCHEMA IF NOT EXISTS planning;


-- ============================================================
-- 1. INVENTORY REALLOCATION CANDIDATES
-- ============================================================

CREATE OR REPLACE TABLE planning.reallocation_candidates AS

SELECT
    a.allocation_id,

    a.production_order_id AS donor_order_id,
    s.production_order_id AS receiver_order_id,

    a.part_id AS component_part_id,
    a.revision AS component_revision,
    a.location_id,

    d.production_site_id,

    d.priority AS donor_priority,
    r.priority AS receiver_priority,

    d.material_required_date AS donor_required_date,
    r.material_required_date AS receiver_required_date,

    a.allocated_qty::BIGINT AS donor_reserved_qty,
    s.shortage_qty::BIGINT AS receiver_shortage_qty,

    LEAST(
        a.allocated_qty,
        s.shortage_qty
    )::BIGINT AS pairwise_transfer_upper_bound_qty

FROM core.inventory_allocations a

JOIN core.production_orders d
    ON a.production_order_id = d.production_order_id

JOIN planning.shortage_exceptions s
    ON a.part_id = s.component_part_id
   AND a.revision = s.component_revision

JOIN core.production_orders r
    ON s.production_order_id = r.production_order_id

WHERE a.production_order_id <> s.production_order_id

  AND d.production_site_id = r.production_site_id

  AND d.material_required_date > r.material_required_date

  AND (
    CASE d.priority
        WHEN 'HIGH' THEN 1
        WHEN 'MEDIUM' THEN 2
        ELSE 3
    END
  ) > (
    CASE r.priority
        WHEN 'HIGH' THEN 1
        WHEN 'MEDIUM' THEN 2
        ELSE 3
    END
  )

  AND a.allocated_qty > 0
  AND s.shortage_qty > 0;


-- ============================================================
-- 2. PRODUCTION RESEQUENCING CANDIDATES
-- ============================================================

CREATE OR REPLACE TABLE planning.resequencing_candidates AS

SELECT
    blocked.production_order_id AS blocked_order_id,
    ready.production_order_id AS ready_donor_order_id,

    blocked.product_family_id AS blocked_family_id,
    ready.product_family_id AS ready_family_id,

    bo.production_site_id,

    blocked.priority AS blocked_priority,
    ready.priority AS ready_priority,

    bo.planned_start_date AS blocked_original_start,
    ro.planned_start_date AS ready_original_start,

    bo.planned_due_date AS blocked_original_due,

    target.recovery_start_date
        AS earliest_targeted_material_ready_date,

    ro.planned_start_date AS proposed_blocked_start,

    bo.planned_start_date AS proposed_ready_start,

    date_diff(
        'day',
        bo.planned_start_date,
        ro.planned_start_date
    )::INTEGER AS blocked_start_shift_days

FROM planning.production_impact blocked

JOIN core.production_orders bo
    ON blocked.production_order_id =
       bo.production_order_id

JOIN planning.production_impact ready
    ON ready.readiness_status = 'MATERIAL_READY'
   AND ready.production_order_id <>
       blocked.production_order_id

JOIN core.production_orders ro
    ON ready.production_order_id =
       ro.production_order_id

JOIN planning.targeted_expediting_orders target
    ON blocked.production_order_id =
       target.production_order_id

WHERE blocked.readiness_status = 'BLOCKED'

  AND bo.production_site_id = ro.production_site_id

  AND ro.planned_start_date > bo.planned_start_date

  AND ro.planned_start_date <= bo.planned_due_date

  AND target.recovery_start_date <= ro.planned_start_date;


-- ============================================================
-- 3. EXECUTIVE NON-PROCUREMENT ACTION SCREENING
-- ============================================================

CREATE OR REPLACE VIEW
planning.nonprocurement_action_screening AS

SELECT
    'INVENTORY_REALLOCATION' AS action_type,

    COUNT(*)::BIGINT AS candidate_pairs,

    COUNT(DISTINCT donor_order_id)::BIGINT
        AS potential_donor_orders,

    COUNT(DISTINCT receiver_order_id)::BIGINT
        AS potentially_affected_orders,

    CASE
        WHEN COUNT(*) = 0
            THEN 'NO_ELIGIBLE_CANDIDATES'
        ELSE 'REQUIRES_DONOR_IMPACT_MODEL'
    END AS screening_status

FROM planning.reallocation_candidates

UNION ALL

SELECT
    'PRODUCTION_RESEQUENCING' AS action_type,

    COUNT(*)::BIGINT AS candidate_pairs,

    COUNT(DISTINCT ready_donor_order_id)::BIGINT
        AS potential_donor_orders,

    COUNT(DISTINCT blocked_order_id)::BIGINT
        AS potentially_affected_orders,

    CASE
        WHEN COUNT(*) = 0
            THEN 'NO_ELIGIBLE_CANDIDATES'
        ELSE 'REQUIRES_CAPACITY_VALIDATION'
    END AS screening_status

FROM planning.resequencing_candidates;

COMMIT;
