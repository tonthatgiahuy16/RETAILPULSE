-- Slice 5: immutable record of migration files applied by the pipeline runner.
-- The runner creates this table before it can record this migration, so this
-- SQL remains deliberately idempotent for databases already using earlier
-- migrations.

create schema if not exists ops;

create table if not exists ops.schema_migration (
    migration_id integer primary key check (migration_id > 0),
    filename text not null unique,
    checksum char(64) not null,
    applied_at timestamptz not null default now()
);
