# MIMIC-OMOP Interim Run Report - 2026-05-10

## Scope

Goal: load MIMIC-III into PostgreSQL with `CHARTEVENTS.csv` absent, keep `mimiciii.chartevents` empty, and proceed toward the official MIT-LCP `mimic-omop` ETL as far as local prerequisites allow.

## Destructive Commands Executed

Dropped/recreated only the `mimiciii` schema in database `mimic`:

```bash
psql "dbname=mimic options=--search_path=mimiciii" -v ON_ERROR_STOP=1 -c "DROP SCHEMA IF EXISTS mimiciii CASCADE; CREATE SCHEMA mimiciii;"
```

Result: succeeded. PostgreSQL reported the drop cascaded to the prior manual sanity-check `patients` table.

Dropped/recreated only the `omop` schema in database `mimic`:

```bash
psql "dbname=mimic options=--search_path=omop" -v ON_ERROR_STOP=1 -c "DROP SCHEMA IF EXISTS omop CASCADE; CREATE SCHEMA omop;"
```

Result: succeeded. `omop` had 0 tables before this reset.

No database was dropped. No local CSV files were deleted.

## Commands Executed

Create official MIMIC tables:

```bash
psql "dbname=mimic options=--search_path=mimiciii" -v ON_ERROR_STOP=1 -f mimic/build-mimic/postgres_create_tables.sql
```

Load available MIMIC CSVs except `CHARTEVENTS`:

```bash
psql "dbname=mimic options=--search_path=mimiciii" -v ON_ERROR_STOP=1 -v mimic_data_dir="/Users/razimreeh/Documents/ROP-Bert/dataset/raw" -f mimic/build-mimic/postgres_load_data_no_chartevents.sql
```

This stopped at `NOTEEVENTS.csv` because that file is also absent locally.

Resume after `NOTEEVENTS`, loading the remaining available tables:

```bash
psql "dbname=mimic options=--search_path=mimiciii" -v ON_ERROR_STOP=1 -v mimic_data_dir="/Users/razimreeh/Documents/ROP-Bert/dataset/raw" -f mimic/build-mimic/postgres_load_data_remaining_no_chartevents_no_noteevents.sql
```

Fetch official OHDSI CommonDataModel DDL using the pinned upstream commit:

```bash
git clone --filter=blob:none --sparse https://github.com/OHDSI/CommonDataModel.git /private/tmp/CommonDataModel-omop-ddl
git checkout 0ac0f4bd56c7372dcd3417461a91f17a6b118901
git sparse-checkout set PostgreSQL
cp /private/tmp/CommonDataModel-omop-ddl/PostgreSQL/*.txt omop/build-omop/postgresql/
sed -i '' 's/^CREATE TABLE \([a-z_]*\)/CREATE UNLOGGED TABLE \1/' "omop/build-omop/postgresql/OMOP CDM postgresql ddl.txt"
```

Build OMOP tables and apply `mimic-omop` adjustments/comments:

```bash
psql "dbname=mimic options=--search_path=omop" -v ON_ERROR_STOP=1 -f "omop/build-omop/postgresql/OMOP CDM postgresql ddl.txt"
psql "dbname=mimic options=--search_path=omop" -v ON_ERROR_STOP=1 -f "omop/build-omop/postgresql/mimic-omop-alter.sql"
psql "dbname=mimic options=--search_path=omop" -v ON_ERROR_STOP=1 -f "omop/build-omop/postgresql/omop_cdm_comments.sql"
```

Add official local MIMIC IDs:

```bash
psql "dbname=mimic options=--search_path=mimiciii" -v ON_ERROR_STOP=1 -f mimic/build-mimic/postgres_create_mimic_id.sql
```

## MIMIC Tables Loaded

All listed counts are exact row counts after loading.

| table | rows |
|---|---:|
| admissions | 58,976 |
| callout | 34,499 |
| caregivers | 7,567 |
| cptevents | 573,146 |
| d_cpt | 134 |
| d_icd_diagnoses | 14,567 |
| d_icd_procedures | 3,882 |
| d_items | 12,487 |
| d_labitems | 753 |
| datetimeevents | 4,485,937 |
| diagnoses_icd | 651,047 |
| drgcodes | 125,557 |
| icustays | 61,532 |
| inputevents_cv | 17,527,935 |
| inputevents_mv | 3,618,991 |
| labevents | 27,854,055 |
| microbiologyevents | 631,726 |
| outputevents | 4,349,218 |
| patients | 46,520 |
| prescriptions | 4,156,450 |
| procedureevents_mv | 258,066 |
| procedures_icd | 240,095 |
| services | 73,343 |
| transfers | 261,897 |

## Skipped Or Empty MIMIC Tables

| table | rows | reason |
|---|---:|---|
| chartevents | 0 | `CHARTEVENTS.csv` is still downloading and was intentionally skipped. |
| noteevents | 0 | `NOTEEVENTS.csv` was not present in `dataset/raw/` during load. |

The official table DDL created both tables, and `postgres_create_mimic_id.sql` added `mimic_id` columns to both. They are empty placeholders for this interim run.

## OMOP Status

OMOP schema build:

- 39 OMOP tables were created in schema `omop`.
- `mimic-omop-alter.sql` and `omop_cdm_comments.sql` completed.
- Athena vocabulary loading did not run because `mimic-omop/extras/athena` is absent.
- Main ETL did not run because official prerequisites are not complete.

Current row counts:

| OMOP table | rows |
|---|---:|
| concept | 0 |
| measurement | 0 |
| note | 0 |
| observation | 0 |
| person | 0 |
| specimen | 0 |

No OMOP clinical tables are populated yet.

## Errors And Fixes

Error: official full clone of OHDSI CommonDataModel failed with an RPC disconnect.

Fix: used sparse clone into `/private/tmp/CommonDataModel-omop-ddl`, checked out the pinned commit, and copied only `PostgreSQL/*.txt`.

Error: `NOTEEVENTS.csv: No such file or directory`.

Fix: left `noteevents` empty, created a resume helper to load remaining available tables after `NOTEEVENTS`, and recorded `NOTE`/`NOTE_NLP` as future incomplete outputs.

Blocked: `Rscript` is not installed.

Impact: official `etl/ConceptTables/loadTables.R mimiciii` cannot run yet.

Blocked: `mimic-omop/extras/athena` is absent.

Impact: official `omop_vocab_load.sql` cannot run, so the main ETL should not be run yet.

## Expected Partial OMOP Areas After ETL

Once Athena and R prerequisites are satisfied and the main ETL is run with empty `chartevents`, these tables are expected to be incomplete:

- `measurement`: missing CHARTEVENTS-derived measurements.
- `observation`: missing CHARTEVENTS-derived textual observations.
- `specimen`: missing CHARTEVENTS-derived specimen records.

Because `NOTEEVENTS.csv` is also absent, these will also be incomplete or empty:

- `note`
- `note_nlp`

## Future Commands After Athena/R Are Ready

Create/symlink Athena vocabulary folder:

```bash
cd /Users/razimreeh/Documents/ROP-Bert/mimic-omop
ln -s /absolute/path/to/athena_vocab_folder extras/athena
```

Required files:

```text
CONCEPT.csv
CONCEPT_CLASS.csv
VOCABULARY.csv
DOMAIN.csv
RELATIONSHIP.csv
CONCEPT_SYNONYM.csv
CONCEPT_ANCESTOR.csv
CONCEPT_RELATIONSHIP.csv
DRUG_STRENGTH.csv
```

Install R/RPostgres if needed:

```bash
brew install r
Rscript -e 'install.packages("remotes", repos="https://cloud.r-project.org"); remotes::install_github("r-dbi/RPostgres")'
```

Create local `mimic-omop.cfg` in the `mimic-omop` root:

```text
dbname=mimic
host=localhost
port=5432
user=YOUR_LOCAL_POSTGRES_USER
password=
```

Then continue:

```bash
cd /Users/razimreeh/Documents/ROP-Bert/mimic-omop
psql "dbname=mimic options=--search_path=omop" -v ON_ERROR_STOP=1 -f omop/build-omop/postgresql/omop_vocab_load.sql
Rscript etl/ConceptTables/loadTables.R mimiciii
psql "dbname=mimic options=--search_path=mimiciii" --set=OMOP_SCHEMA="omop" -v ON_ERROR_STOP=1 -f etl/etl.sql
```

## Future Incremental Run After `CHARTEVENTS.csv`

Recommended safest path after `CHARTEVENTS.csv` arrives:

1. Load `CHARTEVENTS.csv` into the existing empty `mimiciii.chartevents`.
2. Add `mimic_id` to the newly loaded `chartevents` rows.
3. Re-run only CHARTEVENTS-dependent OMOP SQL blocks or rebuild the affected OMOP target tables if selective rerun proves fragile.

Initial source load:

```bash
cd /Users/razimreeh/Documents/ROP-Bert/mimic-omop
psql "dbname=mimic options=--search_path=mimiciii" -v ON_ERROR_STOP=1 -c "\copy CHARTEVENTS from '/Users/razimreeh/Documents/ROP-Bert/dataset/raw/CHARTEVENTS.csv' delimiter ',' csv header NULL ''"
```

Then assign IDs to just the newly loaded `chartevents` rows:

```sql
UPDATE mimiciii.chartevents
SET mimic_id = nextval('mimiciii.mimic_id_seq'::regclass)
WHERE mimic_id IS NULL;
```

Target OMOP areas to refresh:

- `measurement`
- `observation`
- `specimen`
- related `fact_relationship` rows created by those ETL sections
