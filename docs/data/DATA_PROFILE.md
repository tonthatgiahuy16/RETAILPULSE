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
| Negative `Quantity` | 12,326 | Not synonymous with cancellation; preserve and classify later |
| `Price <= 0` | 3,690 | Quarantine/flag candidate, pending business rule |
| Missing or non-datetime `InvoiceDate` | 0 | No timestamp parsing failure in this sheet |
| Timestamp span | 2009-12-01 07:45 to 2010-12-09 20:01 | No timezone is supplied by UCI |

## Pending evidence

The analogous row-level profile for `Year 2010-2011` must be run locally before setting quality thresholds for the entire source. The terminal here stops one full scan at 30 seconds; that is an execution constraint, not evidence that the sheet is malformed.

Run it locally:

```powershell
python scripts/profile_source.py data/raw/online_retail_ii/online_retail_II.xlsx "Year 2010-2011"
```
