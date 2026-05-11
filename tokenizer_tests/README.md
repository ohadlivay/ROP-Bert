# Tokenizer Tests (Isolated)

These tests validate `OMOPMeasurementTokenizer` using small synthetic OMOP-like measurement tables.

They are intentionally isolated from the main `tests/` area so they can be run explicitly and won’t affect other project behaviors.

## Run

From the repo root:

```bash
python -m unittest discover -s tokenizer_tests -p "test_*.py"
```

## Manual large-data check (real OMOP `measurement`)

This script is intentionally **not** named `test_*.py`, so it does not run under unittest discovery.

Example (Windows PowerShell line continuations):

```powershell
python tokenizer_tests/run_large_measurement_tokenizer_check.py `
  --measurement-path C:\path\to\measurement.csv `
  --nrows 500000 `
  --selection-strategy top_k_frequency `
  --max-measurement-concepts 500 `
  --min-samples-per-concept 30 `
  --num-bins 10 `
  --std-threshold 2.0 `
  --person-split `
  --output-dir tokenizer_tests/large_check_outputs
```

Notes:
- Supports `--file-format auto|csv|parquet|pickle` (auto uses the file suffix).
- `--chunksize` is supported for CSV reading but still concatenates in memory for fitting; it does not stream-fit.
- Outputs: tokenizer JSON, summary JSON, selected concepts CSV, and optional transformed *samples* (not full datasets).

## Scope

- No database access
- No MIMIC/OMOP files required
- No GPU / training
- Uses only temporary files for save/load tests
