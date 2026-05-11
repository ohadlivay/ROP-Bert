from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd


SelectionStrategy = Literal["allowlist", "top_k_frequency", "min_count_only"]
HandleUnselected = Literal["skip", "unk", "meas_unselected"]
HandleMissingNumeric = Literal["missing_token", "skip", "unk"]


SPECIAL_TOKENS: Tuple[str, ...] = ("[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]")


@dataclass(frozen=True)
class OMOPMeasurementTokenizerConfig:
    num_bins: int = 10
    std_threshold: float = 2.0
    min_samples_per_concept: int = 30

    include_outlier_tokens: bool = True
    include_missing_tokens: bool = True
    unit_aware: bool = False
    token_prefix: str = "MEAS"

    selected_measurement_concept_ids: Optional[List[int]] = None
    excluded_measurement_concept_ids: List[int] = field(default_factory=list)
    max_measurement_concepts: Optional[int] = None
    selection_strategy: SelectionStrategy = "min_count_only"

    handle_unselected: HandleUnselected = "skip"
    handle_missing_numeric: HandleMissingNumeric = "missing_token"

    # Column names (override if upstream renames columns)
    person_id_col: str = "person_id"
    measurement_concept_id_col: str = "measurement_concept_id"
    value_as_number_col: str = "value_as_number"
    unit_concept_id_col: str = "unit_concept_id"
    measurement_datetime_col: str = "measurement_datetime"
    measurement_date_col: str = "measurement_date"
    visit_occurrence_id_col: str = "visit_occurrence_id"


def _stable_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_numeric(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series.dtype):
        return series.astype("float64")
    return pd.to_numeric(series, errors="coerce").astype("float64")


@dataclass
class _BinSpec:
    count: int
    mean: float
    std: float
    lower: float
    upper: float
    num_bins: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "_BinSpec":
        return cls(
            count=int(payload["count"]),
            mean=float(payload["mean"]),
            std=float(payload["std"]),
            lower=float(payload["lower"]),
            upper=float(payload["upper"]),
            num_bins=int(payload["num_bins"]),
        )


class OMOPMeasurementTokenizer:
    """Tokenizer for OMOP MEASUREMENT numeric values.

    Fits per-(concept[, unit]) bins on training data only, then transforms rows into
    deterministic BERT-style tokens and token IDs.
    """

    def __init__(self, config: Optional[OMOPMeasurementTokenizerConfig] = None):
        self.config = config or OMOPMeasurementTokenizerConfig()
        if self.config.num_bins <= 0:
            raise ValueError("num_bins must be > 0")
        if self.config.min_samples_per_concept <= 0:
            raise ValueError("min_samples_per_concept must be > 0")
        if self.config.std_threshold <= 0:
            raise ValueError("std_threshold must be > 0")

        self._is_fitted: bool = False
        self._selected_keys: List[Tuple[int, Optional[int]]] = []
        self._bins: Dict[Tuple[int, Optional[int]], _BinSpec] = {}

        self._token_to_id: Dict[str, int] = {}
        self._id_to_token: Dict[int, str] = {}

    def is_fitted(self) -> bool:
        return self._is_fitted

    def get_selected_concepts(self) -> List[Union[int, Tuple[int, int]]]:
        if not self._is_fitted:
            return []
        if not self.config.unit_aware:
            return [concept_id for concept_id, _unit in self._selected_keys]
        return [(concept_id, unit_id if unit_id is not None else -1) for concept_id, unit_id in self._selected_keys]

    def describe(self) -> Dict[str, Any]:
        return {
            "is_fitted": self._is_fitted,
            "unit_aware": self.config.unit_aware,
            "num_selected": len(self._selected_keys),
            "num_bins": self.config.num_bins,
            "std_threshold": self.config.std_threshold,
            "min_samples_per_concept": self.config.min_samples_per_concept,
            "selection_strategy": self.config.selection_strategy,
        }

    def get_vocab(self) -> Dict[str, int]:
        if not self._is_fitted:
            raise RuntimeError("Tokenizer is not fitted")
        return dict(self._token_to_id)

    def token_to_id(self, token: str) -> int:
        if not self._is_fitted:
            raise RuntimeError("Tokenizer is not fitted")
        return self._token_to_id.get(token, self._token_to_id["[UNK]"])

    def id_to_token(self, token_id: int) -> str:
        if not self._is_fitted:
            raise RuntimeError("Tokenizer is not fitted")
        token = self._id_to_token.get(int(token_id))
        if token is None:
            return "[UNK]"
        return token

    def fit(self, measurements_df: pd.DataFrame) -> "OMOPMeasurementTokenizer":
        df = self._validate_and_prepare_df(measurements_df)
        if df.empty:
            raise ValueError("measurements_df is empty; cannot fit tokenizer")

        group_cols = [self.config.measurement_concept_id_col]
        if self.config.unit_aware:
            group_cols.append(self.config.unit_concept_id_col)

        values = _coerce_numeric(df[self.config.value_as_number_col])
        df = df.assign(**{self.config.value_as_number_col: values})

        valid_numeric_mask = df[self.config.value_as_number_col].notna()
        df_valid = df.loc[valid_numeric_mask, group_cols + [self.config.value_as_number_col]]

        if df_valid.empty:
            raise ValueError("No valid numeric value_as_number rows found in training data")

        counts = (
            df_valid.groupby(group_cols, dropna=False)[self.config.value_as_number_col]
            .size()
            .sort_values(ascending=False)
        )

        selected_keys = self._select_keys_from_counts(counts)
        if not selected_keys:
            raise ValueError("No measurement concepts selected; check selection config and min_samples_per_concept")

        self._selected_keys = selected_keys

        self._bins = {}
        for key in self._selected_keys:
            concept_id, unit_id = key
            if self.config.unit_aware:
                rows = df_valid[
                    (df_valid[self.config.measurement_concept_id_col] == concept_id)
                    & (df_valid[self.config.unit_concept_id_col] == unit_id)
                ]
            else:
                rows = df_valid[df_valid[self.config.measurement_concept_id_col] == concept_id]
            values_np = rows[self.config.value_as_number_col].to_numpy(dtype="float64", copy=False)
            values_np = values_np[np.isfinite(values_np)]
            if values_np.size < self.config.min_samples_per_concept:
                continue

            mean = float(np.mean(values_np))
            std = float(np.std(values_np, ddof=0))
            if not np.isfinite(mean) or not np.isfinite(std):
                continue

            lower = mean - (self.config.std_threshold * std)
            upper = mean + (self.config.std_threshold * std)
            if not np.isfinite(lower) or not np.isfinite(upper):
                continue

            if std == 0.0:
                lower = mean
                upper = mean

            self._bins[key] = _BinSpec(
                count=int(values_np.size),
                mean=mean,
                std=std,
                lower=float(lower),
                upper=float(upper),
                num_bins=int(self.config.num_bins),
            )

        self._selected_keys = [k for k in self._selected_keys if k in self._bins]
        if not self._selected_keys:
            raise ValueError("No measurement concepts had valid stats after fitting; check input data quality")

        self._build_vocab()
        self._is_fitted = True
        return self

    def transform(self, measurements_df: pd.DataFrame) -> pd.DataFrame:
        if not self._is_fitted:
            raise RuntimeError("Tokenizer is not fitted; call fit() or load() first")

        df = self._validate_and_prepare_df(measurements_df)
        if df.empty:
            return self._empty_transformed_df()

        values = _coerce_numeric(df[self.config.value_as_number_col])
        df = df.assign(**{self.config.value_as_number_col: values})

        out_rows: List[Dict[str, Any]] = []
        for row in df.itertuples(index=False):
            concept_id = _stable_int(getattr(row, self.config.measurement_concept_id_col))
            unit_id = _stable_int(getattr(row, self.config.unit_concept_id_col))
            value = getattr(row, self.config.value_as_number_col)

            token = self.tokenize_single(concept_id, value, unit_concept_id=unit_id)
            if token is None:
                continue

            out_rows.append(
                {
                    self.config.person_id_col: getattr(row, self.config.person_id_col),
                    self.config.visit_occurrence_id_col: getattr(row, self.config.visit_occurrence_id_col),
                    self.config.measurement_datetime_col: getattr(row, self.config.measurement_datetime_col),
                    self.config.measurement_date_col: getattr(row, self.config.measurement_date_col),
                    self.config.measurement_concept_id_col: concept_id,
                    self.config.unit_concept_id_col: unit_id,
                    self.config.value_as_number_col: value,
                    "token": token,
                    "token_id": self.token_to_id(token),
                }
            )

        if not out_rows:
            return self._empty_transformed_df()

        return pd.DataFrame(out_rows)

    def fit_transform(self, measurements_df: pd.DataFrame) -> pd.DataFrame:
        return self.fit(measurements_df).transform(measurements_df)

    def tokenize_single(
        self,
        measurement_concept_id: Optional[int],
        value_as_number: Any,
        unit_concept_id: Optional[int] = None,
    ) -> Optional[str]:
        if not self._is_fitted:
            raise RuntimeError("Tokenizer is not fitted; call fit() or load() first")

        concept_id = _stable_int(measurement_concept_id)
        unit_id = _stable_int(unit_concept_id)
        if concept_id is None:
            return self._handle_unselected_token()

        key = (concept_id, unit_id if self.config.unit_aware else None)
        if key not in self._bins:
            return self._handle_unselected_token()

        spec = self._bins[key]

        if value_as_number is None or (isinstance(value_as_number, float) and math.isnan(value_as_number)):
            return self._handle_missing_numeric_token(key)

        try:
            value = float(value_as_number)
        except (TypeError, ValueError):
            return self._token_unk_value(key)

        if not math.isfinite(value):
            return self._token_unk_value(key)

        if spec.std == 0.0 or spec.lower == spec.upper:
            return self._token_bin(key, 0)

        if value < spec.lower:
            return self._token_low_outlier(key)
        if value > spec.upper:
            return self._token_high_outlier(key)

        width = (spec.upper - spec.lower) / float(spec.num_bins)
        if width <= 0.0 or not math.isfinite(width):
            return self._token_bin(key, 0)

        bin_index = int(math.floor((value - spec.lower) / width))
        if bin_index >= spec.num_bins:
            bin_index = spec.num_bins - 1
        if bin_index < 0:
            bin_index = 0
        return self._token_bin(key, bin_index)

    def save(self, path: Union[str, Path]) -> None:
        if not self._is_fitted:
            raise RuntimeError("Tokenizer is not fitted; nothing to save")
        path = Path(path)
        payload = self._to_state_dict()
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    @classmethod
    def load(cls, path: Union[str, Path]) -> "OMOPMeasurementTokenizer":
        path = Path(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        config = OMOPMeasurementTokenizerConfig(**payload["config"])
        tok = cls(config=config)
        tok._from_state_dict(payload)
        tok._is_fitted = True
        return tok

    def _to_state_dict(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "class_name": self.__class__.__name__,
            "config": asdict(self.config),
            "selected_keys": [self._key_to_json(k) for k in self._selected_keys],
            "bins": {self._key_to_json(k): v.to_dict() for k, v in self._bins.items()},
            "token_to_id": dict(self._token_to_id),
            "id_to_token": {str(k): v for k, v in self._id_to_token.items()},
            "special_tokens": list(SPECIAL_TOKENS),
        }

    def _from_state_dict(self, payload: Mapping[str, Any]) -> None:
        self._selected_keys = [self._key_from_json(k) for k in payload["selected_keys"]]
        self._bins = {self._key_from_json(k): _BinSpec.from_dict(v) for k, v in payload["bins"].items()}
        self._token_to_id = {str(k): int(v) for k, v in payload["token_to_id"].items()}
        self._id_to_token = {int(k): str(v) for k, v in payload["id_to_token"].items()}

    def _build_vocab(self) -> None:
        token_to_id: Dict[str, int] = {}

        for i, tok in enumerate(SPECIAL_TOKENS):
            token_to_id[tok] = i

        if self.config.handle_unselected == "meas_unselected":
            token_to_id[f"{self.config.token_prefix}_UNSELECTED"] = len(token_to_id)

        for key in sorted(self._selected_keys, key=self._key_sort_key):
            if self.config.include_outlier_tokens:
                token_to_id[self._token_low_outlier(key)] = len(token_to_id)
            for bin_idx in range(self.config.num_bins):
                token_to_id[self._token_bin(key, bin_idx)] = len(token_to_id)
            if self.config.include_outlier_tokens:
                token_to_id[self._token_high_outlier(key)] = len(token_to_id)
            if self.config.include_missing_tokens:
                token_to_id[self._token_missing(key)] = len(token_to_id)
            token_to_id[self._token_unk_value(key)] = len(token_to_id)

        self._token_to_id = token_to_id
        self._id_to_token = {i: tok for tok, i in token_to_id.items()}

    def _select_keys_from_counts(self, counts: pd.Series) -> List[Tuple[int, Optional[int]]]:
        excluded = set(int(x) for x in (self.config.excluded_measurement_concept_ids or []))
        allowlist = self.config.selected_measurement_concept_ids

        def iter_keys() -> Iterable[Tuple[int, Optional[int], int]]:
            for idx, count in counts.items():
                if isinstance(idx, tuple):
                    concept_raw, unit_raw = idx
                else:
                    concept_raw, unit_raw = idx, None
                concept_id = _stable_int(concept_raw)
                unit_id = _stable_int(unit_raw) if self.config.unit_aware else None
                if concept_id is None:
                    continue
                if concept_id in excluded:
                    continue
                yield concept_id, unit_id, int(count)

        items = list(iter_keys())

        strategy: SelectionStrategy = self.config.selection_strategy
        if allowlist is not None:
            strategy = "allowlist"

        selected: List[Tuple[int, Optional[int]]] = []
        if strategy == "allowlist":
            if allowlist is None:
                raise ValueError("selection_strategy=allowlist but selected_measurement_concept_ids is None")
            allow = set(int(x) for x in allowlist)
            for concept_id, unit_id, count in items:
                if concept_id in allow and count >= self.config.min_samples_per_concept:
                    selected.append((concept_id, unit_id))
        elif strategy == "top_k_frequency":
            if self.config.max_measurement_concepts is None or self.config.max_measurement_concepts <= 0:
                raise ValueError("selection_strategy=top_k_frequency requires max_measurement_concepts > 0")
            for concept_id, unit_id, count in items:
                if count < self.config.min_samples_per_concept:
                    continue
                selected.append((concept_id, unit_id))
                if len(selected) >= self.config.max_measurement_concepts:
                    break
        elif strategy == "min_count_only":
            for concept_id, unit_id, count in items:
                if count >= self.config.min_samples_per_concept:
                    selected.append((concept_id, unit_id))
        else:
            raise ValueError(f"Unknown selection_strategy: {strategy}")

        if not self.config.unit_aware:
            # De-duplicate in case group keys collapse to concept-only.
            selected = sorted(set((c, None) for c, _u in selected), key=self._key_sort_key)
        else:
            selected = sorted(set(selected), key=self._key_sort_key)

        return selected

    def _handle_unselected_token(self) -> Optional[str]:
        if self.config.handle_unselected == "skip":
            return None
        if self.config.handle_unselected == "unk":
            return "[UNK]"
        if self.config.handle_unselected == "meas_unselected":
            return f"{self.config.token_prefix}_UNSELECTED"
        raise ValueError(f"Unknown handle_unselected: {self.config.handle_unselected}")

    def _handle_missing_numeric_token(self, key: Tuple[int, Optional[int]]) -> Optional[str]:
        if self.config.handle_missing_numeric == "skip":
            return None
        if self.config.handle_missing_numeric == "unk":
            return "[UNK]"
        if self.config.handle_missing_numeric == "missing_token":
            if not self.config.include_missing_tokens:
                return "[UNK]"
            return self._token_missing(key)
        raise ValueError(f"Unknown handle_missing_numeric: {self.config.handle_missing_numeric}")

    def _token_bin(self, key: Tuple[int, Optional[int]], bin_index: int) -> str:
        concept_id, unit_id = key
        if self.config.unit_aware:
            unit_part = f"UNIT_{unit_id if unit_id is not None else 'UNKNOWN'}"
            return f"{self.config.token_prefix}_{concept_id}_{unit_part}_BIN_{bin_index}"
        return f"{self.config.token_prefix}_{concept_id}_BIN_{bin_index}"

    def _token_low_outlier(self, key: Tuple[int, Optional[int]]) -> str:
        concept_id, unit_id = key
        if self.config.unit_aware:
            unit_part = f"UNIT_{unit_id if unit_id is not None else 'UNKNOWN'}"
            return f"{self.config.token_prefix}_{concept_id}_{unit_part}_LOW_OUTLIER"
        return f"{self.config.token_prefix}_{concept_id}_LOW_OUTLIER"

    def _token_high_outlier(self, key: Tuple[int, Optional[int]]) -> str:
        concept_id, unit_id = key
        if self.config.unit_aware:
            unit_part = f"UNIT_{unit_id if unit_id is not None else 'UNKNOWN'}"
            return f"{self.config.token_prefix}_{concept_id}_{unit_part}_HIGH_OUTLIER"
        return f"{self.config.token_prefix}_{concept_id}_HIGH_OUTLIER"

    def _token_missing(self, key: Tuple[int, Optional[int]]) -> str:
        concept_id, unit_id = key
        if self.config.unit_aware:
            unit_part = f"UNIT_{unit_id if unit_id is not None else 'UNKNOWN'}"
            return f"{self.config.token_prefix}_{concept_id}_{unit_part}_MISSING"
        return f"{self.config.token_prefix}_{concept_id}_MISSING"

    def _token_unk_value(self, key: Tuple[int, Optional[int]]) -> str:
        concept_id, unit_id = key
        if self.config.unit_aware:
            unit_part = f"UNIT_{unit_id if unit_id is not None else 'UNKNOWN'}"
            return f"{self.config.token_prefix}_{concept_id}_{unit_part}_UNK_VALUE"
        return f"{self.config.token_prefix}_{concept_id}_UNK_VALUE"

    def _key_sort_key(self, key: Tuple[int, Optional[int]]) -> Tuple[int, int]:
        concept_id, unit_id = key
        return int(concept_id), int(unit_id) if unit_id is not None else -1

    def _key_to_json(self, key: Tuple[int, Optional[int]]) -> str:
        concept_id, unit_id = key
        if self.config.unit_aware:
            return f"{int(concept_id)}:{int(unit_id) if unit_id is not None else -1}"
        return f"{int(concept_id)}"

    def _key_from_json(self, raw: str) -> Tuple[int, Optional[int]]:
        if ":" in raw:
            concept_s, unit_s = raw.split(":", 1)
            unit_id = int(unit_s)
            return int(concept_s), (None if unit_id == -1 else unit_id)
        return int(raw), None

    def _validate_and_prepare_df(self, measurements_df: pd.DataFrame) -> pd.DataFrame:
        required = [
            self.config.person_id_col,
            self.config.measurement_concept_id_col,
            self.config.value_as_number_col,
            self.config.unit_concept_id_col,
            self.config.measurement_datetime_col,
            self.config.measurement_date_col,
            self.config.visit_occurrence_id_col,
        ]
        missing = [c for c in required if c not in measurements_df.columns]
        if missing:
            raise ValueError(f"measurements_df is missing required columns: {missing}")

        df = measurements_df.copy()
        if self.config.unit_aware:
            unit_series = df[self.config.unit_concept_id_col].apply(_stable_int)
            df[self.config.unit_concept_id_col] = unit_series.where(unit_series.notna(), None)
        else:
            df[self.config.unit_concept_id_col] = None

        concept_series = df[self.config.measurement_concept_id_col].apply(_stable_int)
        df[self.config.measurement_concept_id_col] = concept_series
        return df

    def _empty_transformed_df(self) -> pd.DataFrame:
        cols = [
            self.config.person_id_col,
            self.config.visit_occurrence_id_col,
            self.config.measurement_datetime_col,
            self.config.measurement_date_col,
            self.config.measurement_concept_id_col,
            self.config.unit_concept_id_col,
            self.config.value_as_number_col,
            "token",
            "token_id",
        ]
        return pd.DataFrame({c: pd.Series(dtype="object") for c in cols})

