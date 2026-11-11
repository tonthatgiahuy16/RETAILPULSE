# Non-`C` negative-quantity adjustment contract

## Decision

A published, typed source row with an invoice that does not begin with `C`
(case-insensitively) and `quantity < 0` is an `ADJUSTMENT`. It is neither a
`SALE` nor a `CANCELLATION`, and it is not asserted to be a customer return.
`CANCELLATION` remains reserved for parse-valid invoices beginning `C`; return
matching remains a separate candidate-only diagnostic.

`ADJUSTMENT` rows preserve the complete raw and staging lineage but are excluded
from `mart.revenue_daily`, `dw.fct_sales_line`, `bi.sales_daily`, and
`bi.sales_line`. Revenue metrics continue to include only `SALE` and
`CANCELLATION` rows.

## Evidence and scope

The decision was probed directly in PostgreSQL on the published source snapshot
with SHA-256 `bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980`
on 2026-11-11:

| Measure | Observed value |
|---|---:|
| Non-`C` negative-quantity rows | 3,457 |
| Distinct invoices | 3,393 |
| Signed quantity | -573,085 |
| Rows with non-zero price | 0 |
| Rows with non-zero signed amount | 0 |
| Signed amount | 0 |

Descriptions include `adjustment`, `damaged`, `missing`, `stock check`,
`wrong barcode`, and `thrown away`; 2,689 rows have no description. The text is
supporting operational context, not proof of a return. The zero-price result
means this reclassification has zero Gross Sales and Net Transaction Amount
impact for this snapshot; it must not be generalized to another snapshot.

## Gate

`tests/sql/022_revenue_adjustment_contract.sql` requires no negative `SALE`,
requires every `ADJUSTMENT` to be a non-`C`, negative-quantity row, and locks
the above snapshot baseline including its zero-revenue impact. A different
snapshot may contain priced adjustments, so its impact must be assessed and its
contract baseline added deliberately rather than silently accepted.
