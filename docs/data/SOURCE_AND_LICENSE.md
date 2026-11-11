# Source and license

## Verified source

- Dataset: Online Retail II
- Publisher: UCI Machine Learning Repository
- Canonical page: https://archive.ics.uci.edu/dataset/502/online+retail+ii
- DOI: https://doi.org/10.24432/C5CG6D
- UCI citation: Chen, D. (2012). *Online Retail II* [Dataset]. UCI Machine Learning Repository.
- License: Creative Commons Attribution 4.0 International (CC BY 4.0)

The repository must retain the citation and license attribution in user-facing documentation. The original workbook must not be committed.

## Local snapshot verified on 2026-10-29

- Download archive SHA-256: `572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb`
- Workbook: `online_retail_II.xlsx`
- Workbook SHA-256: `bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980`
- Workbook size: 45,622,278 bytes
- Source snapshot is stored only under ignored `data/raw/`.

## Verification status against the complete workbook

Profiled locally on 2026-10-29 against the hash-recorded workbook, covering both
sheets (`1,067,371` data rows). See [`DATA_PROFILE.md`](DATA_PROFILE.md) for the
counts.

- Parsed data types and timestamp representation: **verified** for both sheets;
  `InvoiceDate` had zero missing or unparseable values, and timestamps carry no
  timezone (UCI does not supply one).
- Duplicate policy: **verified** — raw ingestion retains every physical workbook
  row, and `InvoiceNo` is a business attribute, not a raw-row key.
- Exact-workbook duplicate counts: **not yet measured**. The profile script does
  not deduplicate or count duplicate rows, so no duplicate-count claim is made.
