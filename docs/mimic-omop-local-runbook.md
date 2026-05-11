# Local MIMIC-OMOP Runbook

This is the project-specific wrapper around the upstream `mimic-omop` instructions. Run commands from the paths shown; many scripts use relative paths.

## Current Verified State

- PostgreSQL is installed and `psql` is available.
- Database `mimic` exists.
- Schemas `mimiciii` and `omop` exist.
- The manual sanity-check table `mimiciii.patients` currently has 46,520 rows.
- `Rscript` is not currently available, but the official concept mapping loader requires R plus `RPostgres`.
- `mimic-omop/extras/athena` is not present yet.
- OMOP CommonDataModel DDL files are not present yet in `mimic-omop/omop/build-omop/postgresql/`.
- `dataset/raw/` currently has only 17 of the 26 MIMIC-III CSVs required by the official full load script.

Missing local CSVs before a full load can succeed:

```text
CAREGIVERS.csv
CHARTEVENTS.csv
CPTEVENTS.csv
D_CPT.csv
D_ICD_PROCEDURES.csv
D_ITEMS.csv
INPUTEVENTS_CV.csv
INPUTEVENTS_MV.csv
NOTEEVENTS.csv
```

## Official Script Map

- MIMIC table DDL: `mimic-omop/mimic/build-mimic/postgres_create_tables.sql`
- MIMIC plain CSV load: `mimic-omop/mimic/build-mimic/postgres_load_data.sql`
- MIMIC gzip CSV load: `mimic-omop/mimic/build-mimic/postgres_load_data_gz.sql`
- MIMIC row-count checks: `mimic-omop/mimic/build-mimic/postgres_checks.sql`
- MIMIC local ID creation: `mimic-omop/mimic/build-mimic/postgres_create_mimic_id.sql`
- OMOP PostgreSQL build docs: `mimic-omop/omop/build-omop/postgresql/README.md`
- Athena vocabulary load: `mimic-omop/omop/build-omop/postgresql/omop_vocab_load.sql`
- Manual concept mapping load: `mimic-omop/etl/ConceptTables/loadTables.R`
- Main ETL: `mimic-omop/etl/etl.sql`

The ETL expects MIMIC-III to already be loaded in PostgreSQL. The upstream README assumes MIMIC-III v1.4 is available in database `mimic`, schema `mimiciii`, before running the OMOP ETL.

## 0. Define Local Parameters

From the repository root:

```bash
cd /Users/razimreeh/Documents/ROP-Bert

export ROP_BERT_ROOT="$PWD"
export MIMIC_DATA_DIR="$ROP_BERT_ROOT/dataset/raw"

cd "$ROP_BERT_ROOT/mimic-omop"

export MIMIC_SCHEMA="mimiciii"
export OMOP_SCHEMA="omop"
export MIMIC="dbname=mimic options=--search_path=$MIMIC_SCHEMA"
export OMOP="dbname=mimic options=--search_path=$OMOP_SCHEMA"
```

Verify database connectivity:

```bash
psql mimic -Atc "select nspname from pg_namespace where nspname in ('mimiciii','omop') order by 1;"
```

## 1. Verify Raw MIMIC Files

Run this before loading. It should print nothing when all required plain CSVs are present.

```bash
cd "$ROP_BERT_ROOT"

for table in ADMISSIONS CALLOUT CAREGIVERS CHARTEVENTS CPTEVENTS DATETIMEEVENTS DIAGNOSES_ICD DRGCODES D_CPT D_ICD_DIAGNOSES D_ICD_PROCEDURES D_ITEMS D_LABITEMS ICUSTAYS INPUTEVENTS_CV INPUTEVENTS_MV LABEVENTS MICROBIOLOGYEVENTS NOTEEVENTS OUTPUTEVENTS PATIENTS PRESCRIPTIONS PROCEDUREEVENTS_MV PROCEDURES_ICD SERVICES TRANSFERS
do
  test -f "$MIMIC_DATA_DIR/$table.csv" || echo "missing $table.csv"
done
```

## 2. Create and Load MIMIC-III Tables

This replaces the manual `patients` sanity-check table by dropping and recreating the whole `mimiciii` schema. Use the plain CSV loader because local files are currently `.csv`, not `.csv.gz`.

```bash
cd "$ROP_BERT_ROOT/mimic-omop"

psql "$MIMIC" -v ON_ERROR_STOP=1 -c "DROP SCHEMA IF EXISTS $MIMIC_SCHEMA CASCADE; CREATE SCHEMA $MIMIC_SCHEMA;"
psql "$MIMIC" -v ON_ERROR_STOP=1 -f mimic/build-mimic/postgres_create_tables.sql
psql "$MIMIC" -v ON_ERROR_STOP=1 -v mimic_data_dir="$MIMIC_DATA_DIR" -f mimic/build-mimic/postgres_load_data.sql
psql "$MIMIC" -v ON_ERROR_STOP=1 -f mimic/build-mimic/postgres_checks.sql
```

Optional after a successful load: constraints can be applied directly. The upstream index script references `chartevents_1` through `chartevents_14`, but the default table DDL leaves those partitions commented out, so do not run `postgres_add_indexes.sql` unchanged unless you also create the partition tables or edit that script for the unpartitioned `chartevents` table.

```bash
psql "$MIMIC" -v ON_ERROR_STOP=1 -f mimic/build-mimic/postgres_add_constraints.sql
```

## 3. Build Empty OMOP Tables

The upstream OMOP README expects OHDSI CommonDataModel DDL files copied into `omop/build-omop/postgresql/`.

```bash
cd "$ROP_BERT_ROOT/mimic-omop"

git clone https://github.com/OHDSI/CommonDataModel.git
cd CommonDataModel
git reset --hard 0ac0f4bd56c7372dcd3417461a91f17a6b118901
cd ..
cp CommonDataModel/PostgreSQL/*.txt omop/build-omop/postgresql/
```

On macOS, use BSD `sed` syntax for the upstream DDL tweak:

```bash
sed -i '' 's/^CREATE TABLE \([a-z_]*\)/CREATE UNLOGGED TABLE \1/' "omop/build-omop/postgresql/OMOP CDM postgresql ddl.txt"
```

Then build schema `omop`:

```bash
psql "$OMOP" -v ON_ERROR_STOP=1 -c "DROP SCHEMA IF EXISTS $OMOP_SCHEMA CASCADE; CREATE SCHEMA $OMOP_SCHEMA;"
psql "$OMOP" -v ON_ERROR_STOP=1 -f "omop/build-omop/postgresql/OMOP CDM postgresql ddl.txt"
psql "$OMOP" -v ON_ERROR_STOP=1 -f "omop/build-omop/postgresql/mimic-omop-alter.sql"
psql "$OMOP" -v ON_ERROR_STOP=1 -f "omop/build-omop/postgresql/omop_cdm_comments.sql"
```

## 4. Place Athena Vocabulary Files

Download OMOP vocabularies from Athena and run the CPT4 Java step from the Athena download if included. The loader expects tab-delimited CSV files under `mimic-omop/extras/athena/`.

Required by `omop_vocab_load.sql`:

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

Symlink the downloaded vocabulary folder:

```bash
cd "$ROP_BERT_ROOT/mimic-omop"
ln -s /absolute/path/to/athena_vocab_folder extras/athena
```

Then load vocabularies from the `mimic-omop` root:

```bash
psql "$OMOP" -v ON_ERROR_STOP=1 -f omop/build-omop/postgresql/omop_vocab_load.sql
```

## 5. Add Local MIMIC Concept IDs

The ETL relies on a `mimic_id` column on MIMIC tables and local concept ID sequences.

```bash
cd "$ROP_BERT_ROOT/mimic-omop"
psql "$MIMIC" -v ON_ERROR_STOP=1 -f mimic/build-mimic/postgres_create_mimic_id.sql
```

## 6. Load Manual Concept Mapping Tables

Install R first if needed:

```bash
brew install r
Rscript -e 'install.packages("remotes", repos="https://cloud.r-project.org"); remotes::install_github("r-dbi/RPostgres")'
```

Create `mimic-omop/mimic-omop.cfg` locally. It is gitignored because it can contain credentials.

```text
dbname=mimic
host=localhost
port=5432
user=YOUR_LOCAL_POSTGRES_USER
password=
```

Load the mapping CSVs from `extras/concept/` into schema `mimiciii`:

```bash
cd "$ROP_BERT_ROOT/mimic-omop"
Rscript etl/ConceptTables/loadTables.R mimiciii
```

## 7. Run the ETL

Run from `mimic-omop` root because `etl/etl.sql` includes other SQL files by relative path.

```bash
cd "$ROP_BERT_ROOT/mimic-omop"
psql "$MIMIC" --set=OMOP_SCHEMA="$OMOP_SCHEMA" -v ON_ERROR_STOP=1 -f etl/etl.sql
```

Basic verification:

```bash
psql "$OMOP" -c "select 'person' as table_name, count(*) from person union all select 'visit_occurrence', count(*) from visit_occurrence union all select 'condition_occurrence', count(*) from condition_occurrence union all select 'drug_exposure', count(*) from drug_exposure union all select 'measurement', count(*) from measurement;"
```

The upstream check script is also available, but its README notes that pgTap is required:

```bash
psql "$MIMIC" --set=OMOP_SCHEMA="$OMOP_SCHEMA" -v ON_ERROR_STOP=1 -f etl/check_etl.sql
```
