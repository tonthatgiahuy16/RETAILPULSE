{{ config(alias='online_retail_transaction') }}

-- This adapter deliberately preserves the already-verified PostgreSQL contract.
-- Classification remains defined by migrations/002_staging_transaction_classification.sql;
-- dbt supplies discoverability, test execution, and a separate analytics relation.
select *
from {{ source('postgres_staging_contract', 'online_retail_transaction') }}
