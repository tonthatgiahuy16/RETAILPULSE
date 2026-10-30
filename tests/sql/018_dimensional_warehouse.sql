do $$ declare failures bigint; begin
 select abs((select count(*) from dw.fct_sales_line) - (select count(*) from stg.online_retail_transaction where transaction_class = 'SALE')) into failures;
 if failures <> 0 then raise exception 'fact differs from staging SALE count by % rows', failures; end if;
 select count(*) into failures from dw.fct_sales_line f left join dw.dim_date d using (date_key) where d.date_key is null;
 if failures <> 0 then raise exception 'fact has % missing dates', failures; end if;
 select count(*) into failures from dw.fct_sales_line f left join dw.dim_customer d using (customer_key) where f.has_customer_key and d.customer_key is null;
 if failures <> 0 then raise exception 'fact has % missing customer dimensions', failures; end if;
 select count(*) into failures from dw.fct_sales_line f left join dw.dim_product d using (product_key) where f.has_product_key and d.product_key is null;
 if failures <> 0 then raise exception 'fact has % missing product dimensions', failures; end if;
 select count(*) into failures from (select source_file_id,sheet_name,source_row_number from dw.fct_sales_line group by 1,2,3 having count(*)<>1) x;
 if failures <> 0 then raise exception 'fact has % duplicate lineage rows', failures; end if;
end $$;
