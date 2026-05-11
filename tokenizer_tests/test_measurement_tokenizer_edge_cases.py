import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from tokenizer.omop_measurement_tokenizer import OMOPMeasurementTokenizer, OMOPMeasurementTokenizerConfig


REQUIRED_COLS = [
    "person_id",
    "measurement_concept_id",
    "value_as_number",
    "unit_concept_id",
    "measurement_datetime",
    "measurement_date",
    "visit_occurrence_id",
]


def make_df(rows):
    df = pd.DataFrame(rows)
    for col in REQUIRED_COLS:
        if col not in df.columns:
            df[col] = None
    return df[REQUIRED_COLS]


class TestMeasurementTokenizerEdgeCases(unittest.TestCase):
    def test_boundary_behavior_and_clamping(self):
        train_df = make_df(
            [
                {
                    "person_id": 1,
                    "visit_occurrence_id": 1,
                    "measurement_concept_id": 100,
                    "unit_concept_id": 0,
                    "value_as_number": v,
                    "measurement_datetime": "2020-01-01T00:00:00",
                    "measurement_date": "2020-01-01",
                }
                for v in [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] * 2
            ]
        )
        tok = OMOPMeasurementTokenizer(
            OMOPMeasurementTokenizerConfig(num_bins=5, min_samples_per_concept=5, std_threshold=2.0)
        ).fit(train_df)

        spec = tok._bins[(100, None)]
        t_low = tok.tokenize_single(100, spec.lower, unit_concept_id=0)
        t_up = tok.tokenize_single(100, spec.upper, unit_concept_id=0)
        self.assertTrue(t_low.startswith("MEAS_100_BIN_"))
        self.assertTrue(t_up.startswith("MEAS_100_BIN_"))

        t_at_upper = tok.tokenize_single(100, spec.upper, unit_concept_id=0)
        self.assertFalse(t_at_upper.endswith("BIN_5"))

    def test_no_leakage_selection_stays_from_train_only(self):
        train_df = make_df(
            [
                {
                    "person_id": 1,
                    "visit_occurrence_id": 1,
                    "measurement_concept_id": 100,
                    "unit_concept_id": 0,
                    "value_as_number": v,
                    "measurement_datetime": "2020-01-01T00:00:00",
                    "measurement_date": "2020-01-01",
                }
                for v in range(10)
            ]
            + [
                {
                    "person_id": 1,
                    "visit_occurrence_id": 1,
                    "measurement_concept_id": 300,
                    "unit_concept_id": 0,
                    "value_as_number": 1.0,
                    "measurement_datetime": "2020-01-01T00:00:00",
                    "measurement_date": "2020-01-01",
                }
                for _ in range(2)
            ]
        )
        tok = OMOPMeasurementTokenizer(
            OMOPMeasurementTokenizerConfig(
                min_samples_per_concept=5,
                selection_strategy="min_count_only",
                handle_unselected="skip",
            )
        ).fit(train_df)
        self.assertNotIn(300, tok.get_selected_concepts())

        val_df = make_df(
            [
                {
                    "person_id": 2,
                    "visit_occurrence_id": 2,
                    "measurement_concept_id": 300,
                    "unit_concept_id": 0,
                    "value_as_number": float(v),
                    "measurement_datetime": "2020-01-02T00:00:00",
                    "measurement_date": "2020-01-02",
                }
                for v in range(100)
            ]
        )
        out = tok.transform(val_df)
        self.assertEqual(out.shape[0], 0)

    def test_handle_unselected_as_unk_or_meas_unselected(self):
        train_df = make_df(
            [
                {
                    "person_id": 1,
                    "visit_occurrence_id": 1,
                    "measurement_concept_id": 100,
                    "unit_concept_id": 0,
                    "value_as_number": float(v),
                    "measurement_datetime": "2020-01-01T00:00:00",
                    "measurement_date": "2020-01-01",
                }
                for v in range(10)
            ]
        )

        tok_unk = OMOPMeasurementTokenizer(
            OMOPMeasurementTokenizerConfig(min_samples_per_concept=5, handle_unselected="unk")
        ).fit(train_df)
        self.assertEqual(tok_unk.tokenize_single(999, 1.0, unit_concept_id=0), "[UNK]")

        tok_meas = OMOPMeasurementTokenizer(
            OMOPMeasurementTokenizerConfig(min_samples_per_concept=5, handle_unselected="meas_unselected")
        ).fit(train_df)
        self.assertEqual(tok_meas.tokenize_single(999, 1.0, unit_concept_id=0), "MEAS_UNSELECTED")
        self.assertIn("MEAS_UNSELECTED", tok_meas.get_vocab())

    def test_unit_aware_separates_stats_and_tokens(self):
        train_df = make_df(
            [
                {
                    "person_id": 1,
                    "visit_occurrence_id": 1,
                    "measurement_concept_id": 100,
                    "unit_concept_id": 1,
                    "value_as_number": float(v),
                    "measurement_datetime": "2020-01-01T00:00:00",
                    "measurement_date": "2020-01-01",
                }
                for v in range(10)
            ]
            + [
                {
                    "person_id": 1,
                    "visit_occurrence_id": 1,
                    "measurement_concept_id": 100,
                    "unit_concept_id": 2,
                    "value_as_number": float(v) + 100.0,
                    "measurement_datetime": "2020-01-01T00:00:00",
                    "measurement_date": "2020-01-01",
                }
                for v in range(10)
            ]
        )
        tok = OMOPMeasurementTokenizer(
            OMOPMeasurementTokenizerConfig(unit_aware=True, min_samples_per_concept=5, num_bins=5)
        ).fit(train_df)

        t1 = tok.tokenize_single(100, 1.0, unit_concept_id=1)
        t2 = tok.tokenize_single(100, 101.0, unit_concept_id=2)
        self.assertIn("UNIT_1", t1)
        self.assertIn("UNIT_2", t2)

    def test_save_load_state_is_identical(self):
        train_df = make_df(
            [
                {
                    "person_id": 1,
                    "visit_occurrence_id": 1,
                    "measurement_concept_id": 100,
                    "unit_concept_id": 0,
                    "value_as_number": float(v),
                    "measurement_datetime": "2020-01-01T00:00:00",
                    "measurement_date": "2020-01-01",
                }
                for v in range(10)
            ]
        )
        tok = OMOPMeasurementTokenizer(OMOPMeasurementTokenizerConfig(min_samples_per_concept=5, num_bins=5)).fit(
            train_df
        )

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "tok.json"
            tok.save(p)
            tok2 = OMOPMeasurementTokenizer.load(p)

            self.assertEqual(tok2.get_vocab(), tok.get_vocab())
            self.assertEqual(tok2.get_selected_concepts(), tok.get_selected_concepts())
            self.assertEqual(json.dumps(tok2._to_state_dict(), sort_keys=True), json.dumps(tok._to_state_dict(), sort_keys=True))


if __name__ == "__main__":
    unittest.main()

