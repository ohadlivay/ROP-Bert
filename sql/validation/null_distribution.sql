-- NULL distribution report for the major OMOP clinical tables.
--
-- Usage from the repository root:
--   psql -d mimic -v omop_schema=omop -f sql/validation/null_distribution.sql
--
-- Outputs:
--   docs/validation/null_distribution.csv
--   docs/validation/null_distribution_columns.csv
--
-- The NULL-count buckets are computed over explicitly selected columns. Row
-- identity columns are excluded because a populated primary ID says little
-- about the completeness of the clinical content. Foreign keys and source
-- values are kept because their NULLness is analytically meaningful.
--
-- "all_null" means every counted non-primary/non-system column is NULL.
-- Tables with no rows still appear with zero counts in every bucket.

\set ON_ERROR_STOP true

\if :{?omop_schema}
\else
\set omop_schema omop
\endif

SELECT set_config('validation.omop_schema', :'omop_schema', false);

DROP TABLE IF EXISTS pg_temp.validation_target_tables;
CREATE TEMP TABLE validation_target_tables (
    table_name text PRIMARY KEY,
    primary_id_columns text[] NOT NULL,
    notes text NOT NULL DEFAULT ''
);

-- The requested major OMOP tables. For death, person_id is the table key.
INSERT INTO validation_target_tables VALUES
('person', ARRAY['person_id'], 'Exclude OMOP row identifier'),
('visit_occurrence', ARRAY['visit_occurrence_id'], 'Exclude OMOP row identifier'),
('visit_detail', ARRAY['visit_detail_id'], 'Exclude OMOP row identifier'),
('condition_occurrence', ARRAY['condition_occurrence_id'], 'Exclude OMOP row identifier'),
('procedure_occurrence', ARRAY['procedure_occurrence_id'], 'Exclude OMOP row identifier'),
('drug_exposure', ARRAY['drug_exposure_id'], 'Exclude OMOP row identifier'),
('measurement', ARRAY['measurement_id'], 'Exclude OMOP row identifier'),
('observation', ARRAY['observation_id'], 'Exclude OMOP row identifier'),
('specimen', ARRAY['specimen_id'], 'Exclude OMOP row identifier'),
('death', ARRAY['person_id'], 'Death is keyed by person_id'),
('note', ARRAY['note_id'], 'Exclude OMOP row identifier'),
('note_nlp', ARRAY['note_nlp_id'], 'Exclude OMOP row identifier');

-- Optional comma-separated table filter for incremental testing, e.g.:
--   -v validation_tables=death,note,note_nlp
\if :{?validation_tables}
DELETE FROM validation_target_tables
WHERE table_name NOT IN (
    SELECT btrim(value)
    FROM regexp_split_to_table(:'validation_tables', ',') AS value
);
\endif

DROP TABLE IF EXISTS pg_temp.validation_counted_columns;
CREATE TEMP TABLE validation_counted_columns AS
SELECT
    t.table_name,
    c.column_name,
    c.ordinal_position,
    t.notes
FROM validation_target_tables t
JOIN information_schema.columns c
  ON c.table_schema = :'omop_schema'
 AND c.table_name = t.table_name
WHERE NOT c.column_name = ANY (t.primary_id_columns)
ORDER BY t.table_name, c.ordinal_position;

DROP TABLE IF EXISTS pg_temp.validation_null_distribution;
CREATE TEMP TABLE validation_null_distribution (
    table_name text PRIMARY KEY,
    counted_column_count integer NOT NULL,
    counted_columns text NOT NULL,
    "0" bigint NOT NULL DEFAULT 0,
    "1" bigint NOT NULL DEFAULT 0,
    "2" bigint NOT NULL DEFAULT 0,
    "3" bigint NOT NULL DEFAULT 0,
    "4" bigint NOT NULL DEFAULT 0,
    "5" bigint NOT NULL DEFAULT 0,
    "6" bigint NOT NULL DEFAULT 0,
    "7" bigint NOT NULL DEFAULT 0,
    "8" bigint NOT NULL DEFAULT 0,
    "9" bigint NOT NULL DEFAULT 0,
    "10" bigint NOT NULL DEFAULT 0,
    "11" bigint NOT NULL DEFAULT 0,
    "12" bigint NOT NULL DEFAULT 0,
    "13" bigint NOT NULL DEFAULT 0,
    "14" bigint NOT NULL DEFAULT 0,
    "15+" bigint NOT NULL DEFAULT 0,
    all_null bigint NOT NULL DEFAULT 0
);

DO $$
DECLARE
    tbl record;
    schema_name text := current_setting('validation.omop_schema');
    null_expr text;
    counted_columns_label text;
    counted_column_count integer;
BEGIN
    FOR tbl IN
        SELECT *
        FROM validation_target_tables
        ORDER BY table_name
    LOOP
        SELECT
            count(*)::integer,
            string_agg(format('(%I IS NULL)::integer', column_name), ' + ' ORDER BY ordinal_position),
            string_agg(column_name, ', ' ORDER BY ordinal_position)
        INTO counted_column_count, null_expr, counted_columns_label
        FROM validation_counted_columns
        WHERE table_name = tbl.table_name;

        IF counted_column_count IS NULL OR counted_column_count = 0 THEN
            INSERT INTO validation_null_distribution (table_name, counted_column_count, counted_columns)
            VALUES (tbl.table_name, 0, '');
            CONTINUE;
        END IF;

        EXECUTE format(
            'INSERT INTO validation_null_distribution
             SELECT
                 %L AS table_name,
                 %s AS counted_column_count,
                 %L AS counted_columns,
                 count(*) FILTER (WHERE null_count = 0)::bigint AS "0",
                 count(*) FILTER (WHERE null_count = 1)::bigint AS "1",
                 count(*) FILTER (WHERE null_count = 2)::bigint AS "2",
                 count(*) FILTER (WHERE null_count = 3)::bigint AS "3",
                 count(*) FILTER (WHERE null_count = 4)::bigint AS "4",
                 count(*) FILTER (WHERE null_count = 5)::bigint AS "5",
                 count(*) FILTER (WHERE null_count = 6)::bigint AS "6",
                 count(*) FILTER (WHERE null_count = 7)::bigint AS "7",
                 count(*) FILTER (WHERE null_count = 8)::bigint AS "8",
                 count(*) FILTER (WHERE null_count = 9)::bigint AS "9",
                 count(*) FILTER (WHERE null_count = 10)::bigint AS "10",
                 count(*) FILTER (WHERE null_count = 11)::bigint AS "11",
                 count(*) FILTER (WHERE null_count = 12)::bigint AS "12",
                 count(*) FILTER (WHERE null_count = 13)::bigint AS "13",
                 count(*) FILTER (WHERE null_count = 14)::bigint AS "14",
                 count(*) FILTER (WHERE null_count >= 15)::bigint AS "15+",
                 count(*) FILTER (WHERE null_count = %s)::bigint AS all_null
             FROM (
                 SELECT %s AS null_count
                 FROM %I.%I
             ) row_nulls',
            tbl.table_name,
            counted_column_count,
            counted_columns_label,
            counted_column_count,
            null_expr,
            schema_name,
            tbl.table_name
        );
    END LOOP;
END $$;

\copy (SELECT table_name, counted_column_count, counted_columns FROM validation_null_distribution ORDER BY table_name) TO 'docs/validation/null_distribution_columns.csv' WITH CSV HEADER

\copy (SELECT table_name, "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15+", all_null FROM validation_null_distribution ORDER BY table_name) TO 'docs/validation/null_distribution.csv' WITH CSV HEADER

SELECT table_name, "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15+", all_null
FROM validation_null_distribution
ORDER BY table_name;
