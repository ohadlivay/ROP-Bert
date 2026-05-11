# OMOP Measurement Tokenizer

This repo includes `OMOPMeasurementTokenizer` (`tokenizer/omop_measurement_tokenizer.py`) to convert numeric rows from the OMOP `MEASUREMENT` table into discrete Med-BERT-style tokens/IDs.

## Expected input

Pandas `DataFrame` with columns:

- `person_id`
- `measurement_concept_id`
- `value_as_number`
- `unit_concept_id`
- `measurement_datetime`
- `measurement_date`
- `visit_occurrence_id`

## Train/val/test (no leakage)

Fit and concept-selection must be done on *training* data only:

```python
from tokenizer.omop_measurement_tokenizer import OMOPMeasurementTokenizer, OMOPMeasurementTokenizerConfig

# train_df / val_df / test_df: OMOP measurement rows
cfg = OMOPMeasurementTokenizerConfig(
    num_bins=10,
    std_threshold=2.0,
    min_samples_per_concept=30,
    selection_strategy="min_count_only",  # or "top_k_frequency"/"allowlist"
    unit_aware=False,
)

tok = OMOPMeasurementTokenizer(cfg).fit(train_df)
tok.save("artifacts/measurement_tokenizer.json")

tok = OMOPMeasurementTokenizer.load("artifacts/measurement_tokenizer.json")
train_tokens = tok.transform(train_df)
val_tokens = tok.transform(val_df)
test_tokens = tok.transform(test_df)
```

## Output format

`transform()` returns a `DataFrame` including:

- input metadata columns
- `token` (string)
- `token_id` (int; deterministic given the saved tokenizer)

## Token formats

Concept-only mode (`unit_aware=False`):

- `MEAS_<concept_id>_BIN_<i>`
- `MEAS_<concept_id>_LOW_OUTLIER`
- `MEAS_<concept_id>_HIGH_OUTLIER`
- `MEAS_<concept_id>_MISSING`
- `MEAS_<concept_id>_UNK_VALUE`

Unit-aware mode (`unit_aware=True`) includes `UNIT_<unit_id>` in the token.

