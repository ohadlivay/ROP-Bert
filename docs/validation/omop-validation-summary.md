# OMOP Validation Summary

Generated for PostgreSQL database `mimic`, schema `omop`.

Context: MIMIC-III to OMOP ETL completed successfully, but source `CHARTEVENTS` and `NOTEEVENTS` are currently not loaded. This makes `omop.note` and `omop.note_nlp` empty, and removes CHARTEVENTS-derived contribution to measurements/observations.

## Scripts

Run all reports from the repository root:

```bash
psql -d mimic -v omop_schema=omop -f sql/validation/run_validation_reports.sql
```

Individual reports:

```bash
psql -d mimic -v omop_schema=omop -f sql/validation/duplicate_checks.sql
psql -d mimic -v omop_schema=omop -f sql/validation/null_distribution.sql
```

Incremental smoke-test filter, which writes the same report paths with only the filtered tables:

```bash
psql -d mimic -v omop_schema=omop -v validation_tables=death,note,note_nlp -f sql/validation/null_distribution.sql
```

## Generated Reports

- `docs/validation/duplicate_checks.csv`
- `docs/validation/null_distribution.csv`
- `docs/validation/null_distribution_columns.csv`

## Duplicate Checks

Definitions:

- `duplicate_count`: rows beyond the first row in duplicate groups.
- `duplicate_group_count`: number of duplicate key groups.
- `sample_duplicate_values`: up to five duplicate groups as JSON.

Result:

- Primary ID duplicates: none found in all requested major OMOP tables.
- Source ID duplicates: none found for `person.person_source_value` or `specimen.specimen_source_id`.
- Natural-key duplicates were found in derived/event-heavy tables:

| table_name | natural-key duplicate_count | duplicate_group_count |
|---|---:|---:|
| condition_occurrence | 104 | 103 |
| drug_exposure | 2597191 | 1732844 |
| measurement | 1884686 | 1094895 |
| observation | 3902189 | 388691 |
| procedure_occurrence | 380415 | 82538 |
| specimen | 25806655 | 1840947 |

Interpretation: the large natural-key duplicate counts do not indicate duplicated primary IDs. They indicate repeated clinical facts under the heuristic keys defined in `sql/validation/duplicate_checks.sql`, often with concept ID `0` or sparse source/result fields. The CSV contains sample groups for follow-up.

## NULL Distribution

The NULL distribution excludes each table's primary row identifier and counts NULLs across the remaining clinical/source columns. The counted columns are listed in `null_distribution_columns.csv`.

| table_name | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15+ | all_null |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| condition_occurrence | 0 | 0 | 0 | 0 | 0 | 651000 | 65570 | 25 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| death | 0 | 0 | 0 | 14849 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| drug_exposure | 0 | 0 | 0 | 0 | 0 | 3250366 | 0 | 0 | 63005 | 9751962 | 10868873 | 102948 | 890592 | 5258 | 577 | 1170 | 0 |
| measurement | 0 | 0 | 0 | 0 | 0 | 4219723 | 19378342 | 5182356 | 4705149 | 2097787 | 854030 | 15732 | 1 | 0 | 0 | 0 | 0 |
| note | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| note_nlp | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| observation | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4431357 | 6941 | 397769 | 33794 | 0 | 0 | 0 | 0 | 0 | 0 |
| person | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 46520 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| procedure_occurrence | 0 | 0 | 250284 | 0 | 0 | 240095 | 573125 | 21 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| specimen | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 342466 | 27875090 | 5 | 0 | 0 | 0 | 0 | 0 | 0 |
| visit_detail | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 139514 | 58950 | 0 | 0 | 0 | 73343 | 0 | 0 | 0 |
| visit_occurrence | 0 | 12456 | 46520 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

No rows had every counted non-primary column NULL.
