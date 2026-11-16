
BEGIN TRANSACTION;

CREATE SCHEMA IF NOT EXISTS raw;

CREATE OR REPLACE TABLE raw.product_families AS
SELECT * FROM read_csv('data/raw/product_families.csv', all_varchar=true);

CREATE OR REPLACE TABLE raw.suppliers AS
SELECT * FROM read_csv('data/raw/suppliers.csv', all_varchar=true);

CREATE OR REPLACE TABLE raw.part_master AS
SELECT * FROM read_csv('data/raw/part_master.csv', all_varchar=true);

CREATE OR REPLACE TABLE raw.bom_structure AS
SELECT * FROM read_csv('data/raw/bom_structure.csv', all_varchar=true);

CREATE OR REPLACE TABLE raw.production_orders AS
SELECT * FROM read_csv('data/raw/production_orders.csv', all_varchar=true);

CREATE OR REPLACE TABLE raw.inventory AS
SELECT * FROM read_csv('data/raw/inventory.csv', all_varchar=true);

CREATE OR REPLACE TABLE raw.inventory_allocations AS
SELECT * FROM read_csv('data/raw/inventory_allocations.csv', all_varchar=true);

CREATE OR REPLACE TABLE raw.purchase_orders AS
SELECT * FROM read_csv('data/raw/purchase_orders.csv', all_varchar=true);

CREATE OR REPLACE TABLE raw.engineering_changes AS
SELECT * FROM read_csv('data/raw/engineering_changes.csv', all_varchar=true);

CREATE OR REPLACE TABLE raw.approved_alternates AS
SELECT * FROM read_csv('data/raw/approved_alternates.csv', all_varchar=true);

CREATE OR REPLACE TABLE raw.disruption_scenarios AS
SELECT * FROM read_csv('data/raw/disruption_scenarios.csv', all_varchar=true);

COMMIT;
