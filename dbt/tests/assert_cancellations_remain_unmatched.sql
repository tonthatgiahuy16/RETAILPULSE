select *
from {{ ref('stg_online_retail_transaction') }}
where (is_cancellation_invoice and cancellation_match_status <> 'NOT_EVALUATED')
   or (not is_cancellation_invoice and cancellation_match_status <> 'NOT_APPLICABLE')
