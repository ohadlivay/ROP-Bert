# EDA 01: OMOP Table-Level Population Summary

Run date: 2026-05-29
Export folder: `/Users/razimreeh/Library/CloudStorage/GoogleDrive-razi.mreeh.rm@gmail.com/My Drive/OMOP_exports/mimic_omop2`

## Methodology

- Read exported OMOP Parquet files directly from the `mimic_omop2` export.
- Used Parquet metadata for total table row counts.
- For person-level statistics, streamed only the `person_id` column in batches and aggregated counts per patient.
- Avoided loading full clinical tables or unused columns into memory.
- Generated one row-count summary, three ranking tables, and three bar-chart visualizations.

## Summary Table

| table_name           | total_row_count   | unique_person_id_count   | avg_rows_per_person   | median_rows_per_person   |   min_rows_per_person | p25_rows_per_person   | p75_rows_per_person   | max_rows_per_person   | warning   |
|:---------------------|:------------------|:-------------------------|:----------------------|:-------------------------|----------------------:|:----------------------|:----------------------|:----------------------|:----------|
| person               | 46,520            | 46,520                   | 1.00                  | 1.00                     |                     1 | 1.00                  | 1.00                  | 1                     |           |
| visit_occurrence     | 58,976            | 46,520                   | 1.27                  | 1.00                     |                     1 | 1.00                  | 1.00                  | 42                    |           |
| measurement          | 365,181,104       | 46,518                   | 7,850.32              | 3,177.50                 |                     7 | 1,482.25              | 7,640.50              | 778,195               |           |
| observation          | 6,721,040         | 46,520                   | 144.48                | 50.00                    |                     3 | 11.00                 | 148.00                | 7,309                 |           |
| condition_occurrence | 716,595           | 46,520                   | 15.40                 | 11.00                    |                     1 | 7.00                  | 18.00                 | 574                   |           |
| drug_exposure        | 24,934,751        | 44,050                   | 566.06                | 200.00                   |                     1 | 83.00                 | 497.00                | 42,224                |           |
| procedure_occurrence | 1,063,525         | 45,354                   | 23.45                 | 12.00                    |                     1 | 5.00                  | 27.00                 | 877                   |           |
| death                | 14,849            | 14,849                   | 1.00                  | 1.00                     |                     1 | 1.00                  | 1.00                  | 1                     |           |

## Ranking: Row Count

| table_name           | total_row_count   | unique_person_id_count   | avg_rows_per_person   |
|:---------------------|:------------------|:-------------------------|:----------------------|
| measurement          | 365,181,104       | 46,518                   | 7,850.32              |
| drug_exposure        | 24,934,751        | 44,050                   | 566.06                |
| observation          | 6,721,040         | 46,520                   | 144.48                |
| procedure_occurrence | 1,063,525         | 45,354                   | 23.45                 |
| condition_occurrence | 716,595           | 46,520                   | 15.40                 |
| visit_occurrence     | 58,976            | 46,520                   | 1.27                  |
| person               | 46,520            | 46,520                   | 1.00                  |
| death                | 14,849            | 14,849                   | 1.00                  |

## Ranking: Unique Patients

| table_name           | unique_person_id_count   | total_row_count   | avg_rows_per_person   |
|:---------------------|:-------------------------|:------------------|:----------------------|
| person               | 46,520                   | 46,520            | 1.00                  |
| visit_occurrence     | 46,520                   | 58,976            | 1.27                  |
| observation          | 46,520                   | 6,721,040         | 144.48                |
| condition_occurrence | 46,520                   | 716,595           | 15.40                 |
| measurement          | 46,518                   | 365,181,104       | 7,850.32              |
| procedure_occurrence | 45,354                   | 1,063,525         | 23.45                 |
| drug_exposure        | 44,050                   | 24,934,751        | 566.06                |
| death                | 14,849                   | 14,849            | 1.00                  |

## Ranking: Average Rows Per Patient

| table_name           | avg_rows_per_person   | median_rows_per_person   | p75_rows_per_person   | max_rows_per_person   |
|:---------------------|:----------------------|:-------------------------|:----------------------|:----------------------|
| measurement          | 7,850.32              | 3,177.50                 | 7,640.50              | 778,195               |
| drug_exposure        | 566.06                | 200.00                   | 497.00                | 42,224                |
| observation          | 144.48                | 50.00                    | 148.00                | 7,309                 |
| procedure_occurrence | 23.45                 | 12.00                    | 27.00                 | 877                   |
| condition_occurrence | 15.40                 | 11.00                    | 18.00                 | 574                   |
| visit_occurrence     | 1.27                  | 1.00                     | 1.00                  | 42                    |
| person               | 1.00                  | 1.00                     | 1.00                  | 1                     |
| death                | 1.00                  | 1.00                     | 1.00                  | 1                     |

## Visualizations

- `docs/eda_01_row_count_by_table.png`
- `docs/eda_01_unique_patients_by_table.png`
- `docs/eda_01_avg_rows_per_patient_by_table.png`

## Interpretation Of Findings

- Cohort size is `46,520` people in `person`.
- `visit_occurrence` covers `46,520` people, matching the person table and indicating visit-level coverage for the whole cohort.
- The largest table is `measurement` with `365,181,104` rows.
- The densest table by average rows per patient is `measurement` with `7,850.32` rows per covered patient on average.
- `death` covers `14,849` people and should be interpreted as an outcome/label table rather than a longitudinal event stream.
- Measurements dominate event volume, followed by drug exposures and observations/procedures/conditions depending on modeling scope.
- Median and upper-quartile rows per patient are much lower than maxima in dense event tables, indicating substantial skew in longitudinal depth.

## Possible Transformer Modeling Implications

- BEHRT/Med-BERT style token streams will be measurement-heavy unless event sampling, domain balancing, or vocabulary caps are applied.
- High measurement density can improve temporal granularity, but it may also crowd out diagnoses, medications, and procedures in fixed-length sequences.
- `visit_occurrence` gives complete cohort anchoring and can support visit-window segmentation.
- `condition_occurrence`, `drug_exposure`, and `procedure_occurrence` provide clinically interpretable tokens that may be useful for early prototypes.
- `death` can support outcome labeling, censoring logic, or survival-style prediction tasks, but it should not be treated as ordinary repeated longitudinal context.

## Warnings And Limitations

- The local sandbox may emit fontconfig cache and PyArrow CPU feature detection warnings; these do not affect the read-only EDA outputs.
- This step summarizes table populations only; it does not inspect concept distributions, date ranges, visit alignment, or temporal gaps.
- Person-level statistics are calculated among people represented in each table, not over all cohort members with zero-filled counts.
- Export files are read-only inputs; no source Parquet files or PostgreSQL data were modified.

## Files Created

- `notebooks/eda_01_table_summary.ipynb`
- `scripts/eda_01_table_summary.py`
- `docs/eda_01_table_summary.csv`
- `docs/eda_01_table_summary.md`
- `docs/eda_01_row_count_by_table.png`
- `docs/eda_01_unique_patients_by_table.png`
- `docs/eda_01_avg_rows_per_patient_by_table.png`

Execution time: 3.86 seconds
