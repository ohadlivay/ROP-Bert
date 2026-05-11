-- Run all OMOP validation reports.
--
-- Usage from the repository root:
--   psql -d mimic -v omop_schema=omop -f sql/validation/run_validation_reports.sql
--
-- This script is read-only with respect to OMOP data. It creates temporary
-- tables only and writes CSV files under docs/validation/.

\set ON_ERROR_STOP true

\if :{?omop_schema}
\else
\set omop_schema omop
\endif

\i sql/validation/duplicate_checks.sql
\i sql/validation/null_distribution.sql
