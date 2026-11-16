
BEGIN TRANSACTION;

CREATE SCHEMA IF NOT EXISTS planning;

-- ------------------------------------------------------------
-- 1. Explode multi-level manufacturing BOMs
-- ------------------------------------------------------------

CREATE OR REPLACE TABLE planning.bom_explosion AS

WITH RECURSIVE explosion AS (

    -- Start with scheduled finished goods
    SELECT
        o.production_order_id,
        o.finished_good_id,
        o.finished_good_id AS part_id,
        o.finished_good_revision AS part_revision,
        CAST(o.order_quantity AS BIGINT) AS required_qty,
        o.material_required_date,
        0 AS bom_level,
        '|' || o.finished_good_id || '|' AS bom_path

    FROM core.production_orders o

    UNION ALL

    -- Expand each assembly into its child components
    SELECT
        e.production_order_id,
        e.finished_good_id,
        b.component_part_id,
        b.component_revision,
        e.required_qty * b.quantity_per_parent,
        e.material_required_date,
        e.bom_level + 1,
        e.bom_path || b.component_part_id || '|'

    FROM explosion e

    JOIN core.bom_structure b
        ON e.part_id = b.parent_part_id
       AND e.part_revision = b.parent_revision
       AND e.material_required_date >= b.effective_start_date
       AND (
           b.effective_end_date IS NULL
           OR e.material_required_date <= b.effective_end_date
       )

    WHERE e.bom_level < 10
      AND strpos(
          e.bom_path,
          '|' || b.component_part_id || '|'
      ) = 0
)

SELECT
    e.*,
    p.part_type,
    p.product_family_id

FROM explosion e

JOIN core.part_master p
    ON e.part_id = p.part_id
   AND e.part_revision = p.revision;


-- ------------------------------------------------------------
-- 2. Aggregate purchased component requirements
-- ------------------------------------------------------------

CREATE OR REPLACE TABLE planning.component_requirements AS

SELECT
    e.production_order_id,
    o.finished_good_id,
    o.product_family_id,

    e.part_id AS component_part_id,
    e.part_revision AS component_revision,
    e.material_required_date,

    CAST(SUM(e.required_qty) AS BIGINT)
        AS gross_required_qty,

    COUNT(*) AS bom_path_count,

    p.unit_cost_usd,

    CAST(
        SUM(e.required_qty) * p.unit_cost_usd
        AS DECIMAL(18,2)
    ) AS modeled_material_cost_usd

FROM planning.bom_explosion e

JOIN core.part_master p
    ON e.part_id = p.part_id

JOIN core.production_orders o
    ON e.production_order_id = o.production_order_id

WHERE p.part_type = 'PURCHASED_COMPONENT'

GROUP BY
    e.production_order_id,
    o.finished_good_id,
    o.product_family_id,
    e.part_id,
    e.part_revision,
    e.material_required_date,
    p.unit_cost_usd;


-- ------------------------------------------------------------
-- 3. Production Order Material Summary
-- ------------------------------------------------------------

CREATE OR REPLACE VIEW planning.order_material_summary AS

SELECT
    o.production_order_id,
    o.finished_good_id,
    o.product_family_id,
    o.order_quantity,
    o.material_required_date,

    COUNT(r.component_part_id)
        AS unique_required_components,

    SUM(r.gross_required_qty)
        AS total_component_units,

    SUM(r.modeled_material_cost_usd)
        AS modeled_gross_material_cost_usd

FROM core.production_orders o

LEFT JOIN planning.component_requirements r
    ON o.production_order_id = r.production_order_id

GROUP BY
    o.production_order_id,
    o.finished_good_id,
    o.product_family_id,
    o.order_quantity,
    o.material_required_date;

COMMIT;
