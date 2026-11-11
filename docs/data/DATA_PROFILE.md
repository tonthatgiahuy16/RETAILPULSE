# Data profile — first evidence

## Scope and method

Source: the local, hash-recorded UCI workbook in `data/raw/`.

The project script `scripts/profile_source.py` reads a sheet in streaming mode and counts quality-relevant conditions without modifying the workbook. It does not deduplicate rows, infer returns, or apply business transformations.

## Physical workbook structure

| Sheet | Data rows | Columns |
|---|---:|---:|
| `Year 2009-2010` | 525,461 | 8 |
| `Year 2010-2011` | 541,910 | 8 |
| **Total** | **1,067,371** | — |

Headers are exactly: `Invoice`, `StockCode`, `Description`, `Quantity`, `InvoiceDate`, `Price`, `Customer ID`, `Country`.

## Completed profile: `Year 2009-2010`

| Check | Observed count | Interpretation |
|---|---:|---|
| Data rows | 525,461 | Source rows; retain all in raw |
| Missing `Customer ID` | 107,927 | Retain for revenue; exclude later customer-level consumers |
| Missing `Description` | 2,928 | Flag in staging; do not mutate raw |
| Invoice beginning `C` | 10,206 | UCI-defined cancellation indicator, not yet a matched return |
| Negative `Quantity` | 12,326 | Not synonymous with cancellation; C-prefixed rows are `CANCELLATION`, other negative rows are `ADJUSTMENT` |
| `Price <= 0` | 3,690 | Quarantine/flag candidate, pending business rule |
| Missing or non-datetime `InvoiceDate` | 0 | No timestamp parsing failure in this sheet |
| Timestamp span | 2009-12-01 07:45 to 2010-12-09 20:01 | No timezone is supplied by UCI |

## Completed profile: `Year 2010-2011`

Profiled locally on 2026-10-29 against the hash-recorded workbook.

| Check | Observed count | Interpretation |
|---|---:|---|
| Data rows | 541,910 | Source rows; retain all in raw |
| Missing `Customer ID` | 135,080 | Retain for revenue; exclude later customer-level consumers |
| Missing `Description` | 1,454 | Flag in staging; do not mutate raw |
| Invoice beginning `C` | 9,288 | UCI-defined cancellation indicator, not yet a matched return |
| Negative `Quantity` | 10,624 | Not synonymous with cancellation; C-prefixed rows are `CANCELLATION`, other negative rows are `ADJUSTMENT` |
| `Price <= 0` | 2,517 | Quarantine/flag candidate, pending business rule |
| Missing or non-datetime `InvoiceDate` | 0 | No timestamp parsing failure in this sheet |
| Timestamp span | 2010-12-01 08:26 to 2011-12-09 12:50 | No timezone is supplied by UCI |
