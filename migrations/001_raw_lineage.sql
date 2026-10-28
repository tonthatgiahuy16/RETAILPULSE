-- Slice 1: immutable source manifest, attempt audit, and raw physical rows.
-- This migration is not yet executed against a PostgreSQL database.

create schema if not exists ops;
create schema if not exists raw;

create table if not exists ops.source_file (
    source_file_id bigint generated always as identity primary key,
    sha256 char(64) not null unique,
    source_uri text not null,
    original_filename text not null,
    byte_size bigint not null check (byte_size > 0),
    source_retrieved_at timestamptz not null,
    registered_at timestamptz not null default now(),
    expected_row_count bigint not null check (expected_row_count >= 0)
);

create table if not exists ops.ingestion_batch (
    batch_id uuid primary key,
    source_file_id bigint references ops.source_file(source_file_id),
    attempted_at timestamptz not null default now(),
    completed_at timestamptz,
    status text not null check (status in ('STARTED', 'SUCCEEDED', 'FAILED', 'SKIPPED_ALREADY_LOADED')),
    failure_reason text,
    committed_row_count bigint,
    check (
        (status in ('SUCCEEDED', 'SKIPPED_ALREADY_LOADED') and completed_at is not null)
        or (status in ('STARTED', 'FAILED') and completed_at is null)
    )
);

create table if not exists raw.online_retail_line (
    source_file_id bigint not null references ops.source_file(source_file_id),
    sheet_name text not null,
    source_row_number bigint not null check (source_row_number > 0),
    first_ingestion_batch_id uuid not null references ops.ingestion_batch(batch_id),
    ingested_at timestamptz not null default now(),
    invoice_no_raw text,
    stock_code_raw text,
    description_raw text,
    quantity_raw text,
    invoice_date_raw text,
    unit_price_raw text,
    customer_id_raw text,
    country_raw text,
    primary key (source_file_id, sheet_name, source_row_number)
);

create index if not exists ix_raw_online_retail_line_batch
    on raw.online_retail_line (first_ingestion_batch_id);
