{{ config(alias='revenue_daily') }}

-- Do not reimplement revenue logic in dbt: the verified source contract is
-- migrations/003_mart_revenue_daily.sql, exposed here as a dbt model.
select *
from {{ source('postgres_mart_contract', 'revenue_daily') }}
