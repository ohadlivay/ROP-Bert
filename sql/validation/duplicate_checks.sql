-- Duplicate ID and natural-key checks for the major OMOP clinical tables.
--
-- Usage from the repository root:
--   psql -d mimic -v omop_schema=omop -f sql/validation/duplicate_checks.sql
--
-- Output:
--   docs/validation/duplicate_checks.csv
--
-- The script only reads OMOP tables. Results are staged in temporary tables
-- and exported as CSV. "duplicate_count" is the number of rows beyond the
-- first row in each duplicate group; "duplicate_group_count" is the number of
-- duplicate key groups. Samples are JSON arrays of up to five duplicate groups.

\set ON_ERROR_STOP true

\if :{?omop_schema}
\else
\set omop_schema omop
\endif

SELECT set_config('validation.omop_schema', :'omop_schema', false);

DROP TABLE IF EXISTS pg_temp.validation_duplicate_specs;
CREATE TEMP TABLE validation_duplicate_specs (
    table_name text NOT NULL,
    check_name text NOT NULL,
    checked_columns text[] NOT NULL,
    check_type text NOT NULL,
    notes text NOT NULL DEFAULT ''
);

-- Primary identifier checks. For death, OMOP CDM uses person_id as the row key.
INSERT INTO validation_duplicate_specs VALUES
('person', 'primary_id', ARRAY['person_id'], 'primary_id', 'OMOP row identifier'),
('visit_occurrence', 'primary_id', ARRAY['visit_occurrence_id'], 'primary_id', 'OMOP row identifier'),
('visit_detail', 'primary_id', ARRAY['visit_detail_id'], 'primary_id', 'OMOP row identifier'),
('condition_occurrence', 'primary_id', ARRAY['condition_occurrence_id'], 'primary_id', 'OMOP row identifier'),
('procedure_occurrence', 'primary_id', ARRAY['procedure_occurrence_id'], 'primary_id', 'OMOP row identifier'),
('drug_exposure', 'primary_id', ARRAY['drug_exposure_id'], 'primary_id', 'OMOP row identifier'),
('measurement', 'primary_id', ARRAY['measurement_id'], 'primary_id', 'OMOP row identifier'),
('observation', 'primary_id', ARRAY['observation_id'], 'primary_id', 'OMOP row identifier'),
('specimen', 'primary_id', ARRAY['specimen_id'], 'primary_id', 'OMOP row identifier'),
('death', 'primary_id', ARRAY['person_id'], 'primary_id', 'OMOP death is keyed by person_id'),
('note', 'primary_id', ARRAY['note_id'], 'primary_id', 'OMOP row identifier'),
('note_nlp', 'primary_id', ARRAY['note_nlp_id'], 'primary_id', 'OMOP row identifier');

-- Source identifier checks where the table has an identifier-like source field.
-- Source value fields that represent vocab/source codes rather than row IDs are
-- intentionally excluded; those can be duplicated legitimately.
INSERT INTO validation_duplicate_specs VALUES
('person', 'source_id', ARRAY['person_source_value'], 'source_id', 'Expected to map one source subject to one OMOP person'),
('specimen', 'source_id', ARRAY['specimen_source_id'], 'source_id', 'Source specimen identifier, when populated');

-- Natural keys are heuristic QA checks, not primary-key constraints. They are
-- chosen to catch repeated clinical facts with the same person, event time,
-- concept/source value, and visit context. Rows where every checked column is
-- NULL are ignored.
INSERT INTO validation_duplicate_specs VALUES
('person', 'natural_key', ARRAY['person_source_value', 'gender_source_value', 'year_of_birth'], 'natural_key', 'Source person plus stable demographics'),
('visit_occurrence', 'natural_key', ARRAY['person_id', 'visit_start_datetime', 'visit_end_datetime', 'visit_source_value'], 'natural_key', 'Person, visit interval, and source visit value'),
('visit_detail', 'natural_key', ARRAY['person_id', 'visit_occurrence_id', 'visit_start_datetime', 'visit_end_datetime', 'visit_detail_source_value', 'care_site_id'], 'natural_key', 'Person, parent visit, interval, source detail, and care site'),
('condition_occurrence', 'natural_key', ARRAY['person_id', 'condition_concept_id', 'condition_start_datetime', 'visit_occurrence_id', 'condition_source_value'], 'natural_key', 'Person, condition, time, visit, and source value'),
('procedure_occurrence', 'natural_key', ARRAY['person_id', 'procedure_concept_id', 'procedure_datetime', 'visit_occurrence_id', 'procedure_source_value'], 'natural_key', 'Person, procedure, time, visit, and source value'),
('drug_exposure', 'natural_key', ARRAY['person_id', 'drug_concept_id', 'drug_exposure_start_datetime', 'drug_exposure_end_datetime', 'visit_occurrence_id', 'drug_source_value'], 'natural_key', 'Person, drug, interval, visit, and source value'),
('measurement', 'natural_key', ARRAY['person_id', 'measurement_concept_id', 'measurement_datetime', 'visit_occurrence_id', 'measurement_source_value', 'value_source_value', 'unit_source_value'], 'natural_key', 'Person, measurement, time, visit, source value, result, and unit'),
('observation', 'natural_key', ARRAY['person_id', 'observation_concept_id', 'observation_datetime', 'visit_occurrence_id', 'observation_source_value', 'value_as_string', 'value_as_number'], 'natural_key', 'Person, observation, time, visit, source value, and result'),
('specimen', 'natural_key', ARRAY['person_id', 'specimen_concept_id', 'specimen_datetime', 'specimen_source_id', 'specimen_source_value'], 'natural_key', 'Person, specimen, time, source ID, and source value'),
('death', 'natural_key', ARRAY['person_id', 'death_date', 'death_type_concept_id'], 'natural_key', 'Person, death date, and type'),
('note', 'natural_key', ARRAY['person_id', 'note_datetime', 'note_source_value', 'visit_occurrence_id'], 'natural_key', 'Person, note time, source value, and visit'),
('note_nlp', 'natural_key', ARRAY['note_id', 'offset_begin', 'offset_end', 'lexical_variant', 'note_nlp_concept_id'], 'natural_key', 'Note span and extracted concept');

-- Optional comma-separated table filter for incremental testing, e.g.:
--   -v validation_tables=death,note,note_nlp
\if :{?validation_tables}
DELETE FROM validation_duplicate_specs
WHERE table_name NOT IN (
    SELECT btrim(value)
    FROM regexp_split_to_table(:'validation_tables', ',') AS value
);
\endif

DROP TABLE IF EXISTS pg_temp.validation_duplicate_results;
CREATE TEMP TABLE validation_duplicate_results (
    table_name text NOT NULL,
    check_name text NOT NULL,
    check_type text NOT NULL,
    checked_columns text NOT NULL,
    duplicate_count bigint NOT NULL,
    duplicate_group_count bigint NOT NULL,
    sample_duplicate_values jsonb NOT NULL,
    notes text NOT NULL
);

DO $$
DECLARE
    spec record;
    schema_name text := current_setting('validation.omop_schema');
    relation_exists boolean;
    missing_columns text[];
    group_expr text;
    non_null_filter text;
    duplicate_count bigint;
    duplicate_group_count bigint;
    sample_values jsonb;
BEGIN
    FOR spec IN
        SELECT *
        FROM validation_duplicate_specs
        ORDER BY table_name, check_type, check_name
    LOOP
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = schema_name
              AND table_name = spec.table_name
        )
        INTO relation_exists;

        IF NOT relation_exists THEN
            INSERT INTO validation_duplicate_results
            VALUES (
                spec.table_name,
                spec.check_name,
                spec.check_type,
                array_to_string(spec.checked_columns, ', '),
                0,
                0,
                '[]'::jsonb,
                spec.notes || ' | skipped: table not found'
            );
            CONTINUE;
        END IF;

        SELECT array_agg(col)
        FROM unnest(spec.checked_columns) AS col
        WHERE NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = schema_name
              AND table_name = spec.table_name
              AND column_name = col
        )
        INTO missing_columns;

        IF missing_columns IS NOT NULL THEN
            INSERT INTO validation_duplicate_results
            VALUES (
                spec.table_name,
                spec.check_name,
                spec.check_type,
                array_to_string(spec.checked_columns, ', '),
                0,
                0,
                '[]'::jsonb,
                spec.notes || ' | skipped: missing columns ' || array_to_string(missing_columns, ', ')
            );
            CONTINUE;
        END IF;

        SELECT string_agg(format('%I', col), ', ')
        FROM unnest(spec.checked_columns) AS col
        INTO group_expr;

        SELECT string_agg(format('%I IS NOT NULL', col), ' OR ')
        FROM unnest(spec.checked_columns) AS col
        INTO non_null_filter;

        EXECUTE format(
            'SELECT count(*)::bigint, coalesce(sum(row_count - 1), 0)::bigint
             FROM (
                 SELECT count(*)::bigint AS row_count
                 FROM %I.%I
                 WHERE %s
                 GROUP BY %s
                 HAVING count(*) > 1
             ) dup_groups',
            schema_name,
            spec.table_name,
            non_null_filter,
            group_expr
        )
        INTO duplicate_group_count, duplicate_count;

        EXECUTE format(
            'SELECT coalesce(jsonb_agg(to_jsonb(samples)), ''[]''::jsonb)
             FROM (
                 SELECT %s, count(*)::bigint AS duplicate_rows_in_group
                 FROM %I.%I
                 WHERE %s
                 GROUP BY %s
                 HAVING count(*) > 1
                 ORDER BY count(*) DESC
                 LIMIT 5
             ) samples',
            group_expr,
            schema_name,
            spec.table_name,
            non_null_filter,
            group_expr
        )
        INTO sample_values;

        INSERT INTO validation_duplicate_results
        VALUES (
            spec.table_name,
            spec.check_name,
            spec.check_type,
            array_to_string(spec.checked_columns, ', '),
            duplicate_count,
            duplicate_group_count,
            sample_values,
            spec.notes
        );
    END LOOP;
END $$;

\copy (SELECT table_name, check_name, check_type, checked_columns, duplicate_count, duplicate_group_count, sample_duplicate_values, notes FROM validation_duplicate_results ORDER BY table_name, check_type, check_name) TO 'docs/validation/duplicate_checks.csv' WITH CSV HEADER

SELECT *
FROM validation_duplicate_results
ORDER BY table_name, check_type, check_name;
