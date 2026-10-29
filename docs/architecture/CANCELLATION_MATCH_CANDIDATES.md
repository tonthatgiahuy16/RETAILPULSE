# Cancellation-match candidates — Slice 7

`int.cancellation_sale_candidate` has one row per heuristic edge between a cancellation source row and an eligible sale source row. The rule requires one source snapshot, customer, stock code, exact absolute quantity, and a sale timestamp no later than the cancellation timestamp.

`int.cancellation_match_resolution` has exactly one row per `CANCELLATION` staging row. `MATCHED_CANDIDATE` means exactly one heuristic edge, `AMBIGUOUS` means more than one, and `UNMATCHED` means none. These are candidate labels only: they do not assert that a return was matched, alter `stg.cancellation_match_status`, or change revenue.

Missing Customer ID, missing stock code, invalid cancellation quantity, and no/multiple eligible sale candidates remain explicit reasons. Consumers must retain the source-row lineage columns when interpreting a candidate.

`int.eligible_sale_line` and `int.cancellation_line` are refreshable materialized projections used only to make candidate evaluation tractable. The operational runner refreshes both after a successful ingestion and before gates; raw and staging remain the source of truth.

For source snapshot 1 on 2026-10-29, the heuristic produced 4,907 `MATCHED_CANDIDATE` rows (25.17%), 1,833 `AMBIGUOUS` rows (9.40%), and 12,754 `UNMATCHED` rows (65.43%) out of 19,494 cancellations. These are diagnostics for this snapshot, not return-accounting facts.
