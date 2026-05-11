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


class TestMeasurementTokenizerSmoke(unittest.TestCase):
    def test_fit_transform_smoke(self):
        train_rows = []
        train_rows += [
            {
                "person_id": 1,
                "visit_occurrence_id": 11,
                "measurement_concept_id": 100,
                "unit_concept_id": 0,
                "value_as_number": v,
                "measurement_datetime": "2020-01-01T00:00:00",
                "measurement_date": "2020-01-01",
            }
            for v in [92, 95, 97, 99, 100, 101, 103, 105, 108, 110]
        ]
        train_rows += [
            {
                "person_id": 1,
                "visit_occurrence_id": 11,
                "measurement_concept_id": 200,
                "unit_concept_id": 0,
                "value_as_number": 5.0,
                "measurement_datetime": "2020-01-02T00:00:00",
                "measurement_date": "2020-01-02",
            }
            for _ in range(10)
        ]
        train_rows += [
            {
                "person_id": 1,
                "visit_occurrence_id": 11,
                "measurement_concept_id": 300,
                "unit_concept_id": 0,
                "value_as_number": 1.0,
                "measurement_datetime": "2020-01-03T00:00:00",
                "measurement_date": "2020-01-03",
            }
            for _ in range(2)
        ]

        train_df = make_df(train_rows)

        cfg = OMOPMeasurementTokenizerConfig(
            num_bins=5,
            std_threshold=2.0,
            min_samples_per_concept=5,
            selection_strategy="min_count_only",
            handle_unselected="skip",
            unit_aware=False,
        )
        tok = OMOPMeasurementTokenizer(cfg).fit(train_df)

        selected = tok.get_selected_concepts()
        self.assertIn(100, selected)
        self.assertIn(200, selected)
        self.assertNotIn(300, selected)

        eval_df = make_df(
            [
                {
                    "person_id": 1,
                    "visit_occurrence_id": 11,
                    "measurement_concept_id": 100,
                    "unit_concept_id": 0,
                    "value_as_number": 100.0,
                    "measurement_datetime": "2020-01-04T00:00:00",
                    "measurement_date": "2020-01-04",
                },
                {
                    "person_id": 1,
                    "visit_occurrence_id": 11,
                    "measurement_concept_id": 100,
                    "unit_concept_id": 0,
                    "value_as_number": -9999.0,
                    "measurement_datetime": "2020-01-04T00:00:00",
                    "measurement_date": "2020-01-04",
                },
                {
                    "person_id": 1,
                    "visit_occurrence_id": 11,
                    "measurement_concept_id": 100,
                    "unit_concept_id": 0,
                    "value_as_number": 9999.0,
                    "measurement_datetime": "2020-01-04T00:00:00",
                    "measurement_date": "2020-01-04",
                },
                {
                    "person_id": 1,
                    "visit_occurrence_id": 11,
                    "measurement_concept_id": 100,
                    "unit_concept_id": 0,
                    "value_as_number": None,
                    "measurement_datetime": "2020-01-04T00:00:00",
                    "measurement_date": "2020-01-04",
                },
                {
                    "person_id": 1,
                    "visit_occurrence_id": 11,
                    "measurement_concept_id": 200,
                    "unit_concept_id": 0,
                    "value_as_number": 5.0,
                    "measurement_datetime": "2020-01-04T00:00:00",
                    "measurement_date": "2020-01-04",
                },
                {
                    "person_id": 1,
                    "visit_occurrence_id": 11,
                    "measurement_concept_id": 300,
                    "unit_concept_id": 0,
                    "value_as_number": 123.0,
                    "measurement_datetime": "2020-01-04T00:00:00",
                    "measurement_date": "2020-01-04",
                },
            ]
        )

        out = tok.transform(eval_df)
        self.assertGreaterEqual(out.shape[0], 5)
        self.assertNotIn(300, out["measurement_concept_id"].tolist())

        tokens = out["token"].tolist()
        self.assertTrue(any(t.startswith("MEAS_100_BIN_") for t in tokens))
        self.assertTrue(any(t == "MEAS_100_LOW_OUTLIER" for t in tokens))
        self.assertTrue(any(t == "MEAS_100_HIGH_OUTLIER" for t in tokens))
        self.assertTrue(any(t == "MEAS_100_MISSING" for t in tokens))
        self.assertTrue(any(t == "MEAS_200_BIN_0" for t in tokens))

        vocab = tok.get_vocab()
        self.assertEqual(vocab["[PAD]"], 0)
        self.assertEqual(vocab["[UNK]"], 1)
        self.assertEqual(vocab["[CLS]"], 2)
        self.assertEqual(vocab["[SEP]"], 3)
        self.assertEqual(vocab["[MASK]"], 4)

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "tok.json"
            tok.save(p)
            tok2 = OMOPMeasurementTokenizer.load(p)
            out2 = tok2.transform(eval_df)
            self.assertEqual(out["token"].tolist(), out2["token"].tolist())
            self.assertEqual(out["token_id"].tolist(), out2["token_id"].tolist())


if __name__ == "__main__":
    unittest.main()

