from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tokenizer.omop_measurement_tokenizer import OMOPMeasurementTokenizer, OMOPMeasurementTokenizerConfig


REQUIRED_CORE_COLS = ["person_id", "measurement_concept_id", "value_as_number"]
OPTIONAL_COLS = ["unit_concept_id", "measurement_datetime", "measurement_date", "visit_occurrence_id"]
ALL_COLS = REQUIRED_CORE_COLS + OPTIONAL_COLS


def _maybe_import_psutil():
    try:
        import psutil  # type: ignore

        return psutil
    except Exception:
        return None


def _maybe_torch_cuda_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {"torch_installed": False}
    try:
        import torch  # type: ignore

        info["torch_installed"] = True
        info["cuda_available"] = bool(torch.cuda.is_available())
        if info["cuda_available"]:
            try:
                info["cuda_device_name"] = torch.cuda.get_device_name(0)
            except Exception:
                info["cuda_device_name"] = None
        return info
    except Exception:
        return info


def _detect_format(path: Path, file_format: str) -> str:
    if file_format != "auto":
        return file_format
    suffixes = "".join(path.suffixes).lower()
    if suffixes.endswith(".csv.gz"):
        return "csv"
    if suffixes.endswith(".csv"):
        return "csv"
    if suffixes.endswith(".parquet"):
        return "parquet"
    if suffixes.endswith(".pkl") or suffixes.endswith(".pickle"):
        return "pickle"
    raise ValueError(f"Cannot auto-detect file format from suffix: {path.name}")


def _read_measurements(
    measurement_path: Path,
    file_format: str,
    nrows: Optional[int],
    chunksize: Optional[int],
) -> pd.DataFrame:
    fmt = _detect_format(measurement_path, file_format)
    if fmt == "parquet":
        if chunksize is not None:
            print("WARNING: --chunksize is not supported for parquet; loading in-memory.", file=sys.stderr)
        cols = None
        try:
            cols = ALL_COLS
            df = pd.read_parquet(measurement_path, columns=cols)
        except Exception:
            df = pd.read_parquet(measurement_path)
        if nrows is not None:
            df = df.head(int(nrows))
        return df

    if fmt == "pickle":
        if chunksize is not None:
            print("WARNING: --chunksize is not supported for pickle; loading in-memory.", file=sys.stderr)
        df = pd.read_pickle(measurement_path)
        if nrows is not None:
            df = df.head(int(nrows))
        return df

    if fmt != "csv":
        raise ValueError(f"Unsupported file format: {fmt}")

    csv_kwargs: Dict[str, Any] = {"low_memory": False}
    if str(measurement_path).lower().endswith(".gz"):
        csv_kwargs["compression"] = "gzip"

    usecols = None
    try:
        usecols = ALL_COLS
        if chunksize is None:
            return pd.read_csv(measurement_path, usecols=usecols, nrows=nrows, **csv_kwargs)
        frames: List[pd.DataFrame] = []
        loaded = 0
        for chunk in pd.read_csv(measurement_path, usecols=usecols, chunksize=chunksize, **csv_kwargs):
            frames.append(chunk)
            loaded += len(chunk)
            if nrows is not None and loaded >= int(nrows):
                break
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        if nrows is not None:
            df = df.head(int(nrows))
        return df
    except ValueError:
        # Missing optional columns; fall back to reading all columns and normalize.
        if chunksize is None:
            return pd.read_csv(measurement_path, nrows=nrows, **csv_kwargs)
        frames = []
        loaded = 0
        for chunk in pd.read_csv(measurement_path, chunksize=chunksize, **csv_kwargs):
            frames.append(chunk)
            loaded += len(chunk)
            if nrows is not None and loaded >= int(nrows):
                break
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        if nrows is not None:
            df = df.head(int(nrows))
        return df


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    missing_core = [c for c in REQUIRED_CORE_COLS if c not in df.columns]
    if missing_core:
        raise ValueError(f"Input is missing critical OMOP measurement columns: {missing_core}")

    df = df.copy()
    if "measurement_datetime" not in df.columns and "measurement_date" in df.columns:
        df["measurement_datetime"] = df["measurement_date"]
    if "measurement_date" not in df.columns and "measurement_datetime" in df.columns:
        df["measurement_date"] = df["measurement_datetime"]

    if "visit_occurrence_id" not in df.columns:
        df["visit_occurrence_id"] = None
    if "unit_concept_id" not in df.columns:
        df["unit_concept_id"] = None

    for c in OPTIONAL_COLS:
        if c not in df.columns:
            df[c] = None

    return df[ALL_COLS]


def _split_by_person(
    df: pd.DataFrame, seed: int, train_frac: float, val_frac: float, test_frac: float
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    persons = df["person_id"].dropna().unique()
    persons = persons.astype("int64", copy=False) if np.issubdtype(persons.dtype, np.number) else persons
    rng = np.random.default_rng(seed)
    rng.shuffle(persons)

    n = len(persons)
    n_train = int(round(n * train_frac))
    n_val = int(round(n * val_frac))
    n_train = min(n_train, n)
    n_val = min(n_val, max(n - n_train, 0))
    n_test = max(n - n_train - n_val, 0)

    train_ids = set(persons[:n_train].tolist())
    val_ids = set(persons[n_train : n_train + n_val].tolist())
    test_ids = set(persons[n_train + n_val :].tolist())

    train_df = df[df["person_id"].isin(train_ids)]
    val_df = df[df["person_id"].isin(val_ids)]
    test_df = df[df["person_id"].isin(test_ids)]

    meta = {
        "person_split": True,
        "n_persons_total": n,
        "n_persons_train": len(train_ids),
        "n_persons_val": len(val_ids),
        "n_persons_test": len(test_ids),
        "n_rows_train": int(train_df.shape[0]),
        "n_rows_val": int(val_df.shape[0]),
        "n_rows_test": int(test_df.shape[0]),
    }
    return train_df, val_df, test_df, meta


def _split_by_row(
    df: pd.DataFrame, seed: int, train_frac: float, val_frac: float, test_frac: float
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    n = df.shape[0]
    idx = np.arange(n)
    rng = np.random.default_rng(seed)
    rng.shuffle(idx)

    n_train = int(round(n * train_frac))
    n_val = int(round(n * val_frac))
    n_train = min(n_train, n)
    n_val = min(n_val, max(n - n_train, 0))

    train_idx = idx[:n_train]
    val_idx = idx[n_train : n_train + n_val]
    test_idx = idx[n_train + n_val :]

    meta = {
        "person_split": False,
        "n_rows_total": int(n),
        "n_rows_train": int(len(train_idx)),
        "n_rows_val": int(len(val_idx)),
        "n_rows_test": int(len(test_idx)),
    }
    return df.iloc[train_idx], df.iloc[val_idx], df.iloc[test_idx], meta


def _count_valid_numeric(series: pd.Series) -> Dict[str, Any]:
    vals = pd.to_numeric(series, errors="coerce")
    valid = vals.notna()
    return {"valid_numeric_rows": int(valid.sum()), "numeric_coverage": float(valid.mean()) if len(vals) else 0.0}


def _concept_counts(df: pd.DataFrame) -> pd.Series:
    vals = pd.to_numeric(df["value_as_number"], errors="coerce")
    valid = df.loc[vals.notna(), "measurement_concept_id"]
    return valid.value_counts(dropna=True)


def _token_diagnostics(transformed: pd.DataFrame) -> Dict[str, Any]:
    if transformed.empty:
        return {
            "n_rows": 0,
            "missing_count": 0,
            "low_outlier_count": 0,
            "high_outlier_count": 0,
            "unk_count": 0,
            "top_tokens": [],
        }
    tokens = transformed["token"].astype(str)
    diag = {
        "n_rows": int(transformed.shape[0]),
        "missing_count": int(tokens.str.endswith("_MISSING").sum()),
        "low_outlier_count": int(tokens.str.endswith("_LOW_OUTLIER").sum()),
        "high_outlier_count": int(tokens.str.endswith("_HIGH_OUTLIER").sum()),
        "unk_count": int((tokens == "[UNK]").sum()),
        "top_tokens": tokens.value_counts().head(20).to_dict(),
    }
    return diag


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Manual large-data check for OMOPMeasurementTokenizer (fits on TRAIN only; transforms VAL/TEST)."
    )
    p.add_argument("--measurement-path", required=True, help="Path to OMOP measurement table (CSV/CSV.GZ/Parquet/Pickle).")
    p.add_argument("--output-dir", default=str(Path("tokenizer_tests") / "large_check_outputs"))
    p.add_argument("--file-format", default="auto", choices=["auto", "csv", "parquet", "pickle"])
    p.add_argument("--nrows", type=int, default=None, help="Optional row limit for quicker runs.")
    p.add_argument("--chunksize", type=int, default=None, help="Optional CSV chunksize (still concatenates in memory).")

    p.add_argument("--num-bins", type=int, default=10)
    p.add_argument("--std-threshold", type=float, default=2.0)
    p.add_argument("--min-samples-per-concept", type=int, default=30)
    p.add_argument("--selection-strategy", default="top_k_frequency", choices=["allowlist", "top_k_frequency", "min_count_only"])
    p.add_argument("--max-measurement-concepts", type=int, default=500)
    p.add_argument("--unit-aware", action="store_true", default=False)
    p.add_argument("--handle-unselected", default="skip", choices=["skip", "unk", "meas_unselected"])

    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--train-frac", type=float, default=0.70)
    p.add_argument("--val-frac", type=float, default=0.15)
    p.add_argument("--test-frac", type=float, default=0.15)
    p.add_argument("--person-split", action=argparse.BooleanOptionalAction, default=True)

    p.add_argument("--save-transformed-sample", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--sample-output-rows", type=int, default=10000)

    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)

    t0 = time.perf_counter()
    measurement_path = Path(args.measurement_path)
    out_dir = Path(args.output_dir)
    _ensure_dir(out_dir)

    psutil = _maybe_import_psutil()
    proc = psutil.Process(os.getpid()) if psutil is not None else None

    def mem_mb() -> Optional[float]:
        if proc is None:
            return None
        try:
            return float(proc.memory_info().rss) / (1024.0 * 1024.0)
        except Exception:
            return None

    print("=== Large Measurement Tokenizer Check ===")
    print(f"Measurement path: {measurement_path}")
    print(f"Output dir: {out_dir}")
    print(f"Python: {sys.version.split()[0]}")
    cuda_info = _maybe_torch_cuda_info()
    if cuda_info.get("torch_installed"):
        print(f"Torch installed: True | CUDA available: {cuda_info.get('cuda_available')} | GPU: {cuda_info.get('cuda_device_name')}")
    else:
        print("Torch installed: False")
    print("Note: this tokenizer check is CPU/pandas based; CUDA is not required.")

    if not measurement_path.exists():
        print(f"ERROR: measurement path does not exist: {measurement_path}", file=sys.stderr)
        return 2

    timings: Dict[str, float] = {}
    mem: Dict[str, Optional[float]] = {"start_mb": mem_mb()}

    # Load
    t_load0 = time.perf_counter()
    df_raw = _read_measurements(measurement_path, args.file_format, args.nrows, args.chunksize)
    df = _normalize_columns(df_raw)
    timings["load_s"] = time.perf_counter() - t_load0
    mem["after_load_mb"] = mem_mb()

    numeric_stats = _count_valid_numeric(df["value_as_number"])
    n_persons = int(df["person_id"].nunique(dropna=True))
    n_concepts = int(df["measurement_concept_id"].nunique(dropna=True))

    fmt = _detect_format(measurement_path, args.file_format)
    print("\n**Dataset**")
    print(f"- format: {fmt}")
    print(f"- loaded rows: {df.shape[0]} | columns: {len(df.columns)}")
    print(f"- columns: {list(df.columns)}")
    print(f"- unique persons: {n_persons}")
    print(f"- unique measurement_concept_id: {n_concepts}")
    print(f"- valid numeric rows: {numeric_stats['valid_numeric_rows']} ({numeric_stats['numeric_coverage']:.3f} coverage)")

    # Split
    t_split0 = time.perf_counter()
    total_frac = float(args.train_frac) + float(args.val_frac) + float(args.test_frac)
    if abs(total_frac - 1.0) > 1e-6:
        print("ERROR: train/val/test fracs must sum to 1.0", file=sys.stderr)
        return 2

    if args.person_split:
        train_df, val_df, test_df, split_meta = _split_by_person(df, args.seed, args.train_frac, args.val_frac, args.test_frac)
    else:
        train_df, val_df, test_df, split_meta = _split_by_row(df, args.seed, args.train_frac, args.val_frac, args.test_frac)
    timings["split_s"] = time.perf_counter() - t_split0
    mem["after_split_mb"] = mem_mb()

    print("\n**Split**")
    if split_meta.get("person_split"):
        print(
            f"- person split: True | persons train/val/test: {split_meta['n_persons_train']}/{split_meta['n_persons_val']}/{split_meta['n_persons_test']}"
        )
    else:
        print("- person split: False (row-level split)")
    print(f"- rows train/val/test: {split_meta['n_rows_train']}/{split_meta['n_rows_val']}/{split_meta['n_rows_test']}")

    # Tokenizer config
    cfg = OMOPMeasurementTokenizerConfig(
        num_bins=int(args.num_bins),
        std_threshold=float(args.std_threshold),
        min_samples_per_concept=int(args.min_samples_per_concept),
        selection_strategy=str(args.selection_strategy),
        max_measurement_concepts=int(args.max_measurement_concepts) if args.selection_strategy == "top_k_frequency" else None,
        unit_aware=bool(args.unit_aware),
        handle_unselected=str(args.handle_unselected),
    )

    print("\n**Tokenizer config**")
    print(f"- num_bins: {cfg.num_bins}")
    print(f"- std_threshold: {cfg.std_threshold}")
    print(f"- min_samples_per_concept: {cfg.min_samples_per_concept}")
    print(f"- selection_strategy: {cfg.selection_strategy}")
    print(f"- max_measurement_concepts: {cfg.max_measurement_concepts}")
    print(f"- unit_aware: {cfg.unit_aware}")
    print(f"- handle_unselected: {cfg.handle_unselected}")

    # Fit (TRAIN only)
    print("\nFitting tokenizer on TRAIN only")
    t_fit0 = time.perf_counter()
    tok = OMOPMeasurementTokenizer(cfg).fit(train_df)
    timings["fit_s"] = time.perf_counter() - t_fit0
    mem["after_fit_mb"] = mem_mb()

    # Validation checks (post-fit)
    if not tok.is_fitted():
        print("ERROR: tokenizer not fitted after fit()", file=sys.stderr)
        return 3
    vocab = tok.get_vocab()
    for st in ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]"]:
        if st not in vocab:
            print(f"ERROR: vocab missing special token: {st}", file=sys.stderr)
            return 3

    selected = tok.get_selected_concepts()
    if len(selected) <= 0:
        print("ERROR: selected concept count is 0; check selection parameters or data quality", file=sys.stderr)
        return 3

    train_counts = _concept_counts(train_df)
    top_train_concepts = train_counts.head(25).to_dict()

    print("\n**Fit result**")
    print(f"- selected concept count: {len(selected)}")
    print(f"- vocab size: {len(vocab)}")
    print(f"- first 20 selected concepts: {selected[:20]}")
    print(f"- top concepts by train numeric frequency (up to 25): {list(top_train_concepts.items())[:10]}")

    # Transform (VAL/TEST using fitted tokenizer only)
    print("\nTransforming TRAIN/VAL/TEST using fitted tokenizer only")
    t_tr0 = time.perf_counter()
    train_tok = tok.transform(train_df)
    val_tok = tok.transform(val_df)
    test_tok = tok.transform(test_df)
    timings["transform_s"] = time.perf_counter() - t_tr0
    mem["after_transform_mb"] = mem_mb()

    for name, frame in [("train", train_tok), ("val", val_tok), ("test", test_tok)]:
        if not frame.empty:
            if "token" not in frame.columns or "token_id" not in frame.columns:
                print(f"ERROR: transform output for {name} missing token/token_id columns", file=sys.stderr)
                return 3
            if frame["token_id"].isna().any():
                print(f"ERROR: transform output for {name} contains null token_id values", file=sys.stderr)
                return 3

    diag_train = _token_diagnostics(train_tok.sample(n=min(len(train_tok), args.sample_output_rows), random_state=args.seed)) if not train_tok.empty else _token_diagnostics(train_tok)
    diag_val = _token_diagnostics(val_tok.sample(n=min(len(val_tok), args.sample_output_rows), random_state=args.seed)) if not val_tok.empty else _token_diagnostics(val_tok)
    diag_test = _token_diagnostics(test_tok.sample(n=min(len(test_tok), args.sample_output_rows), random_state=args.seed)) if not test_tok.empty else _token_diagnostics(test_tok)

    print("\n**Token diagnostics (sampled)**")
    print(f"- train: rows={diag_train['n_rows']} missing={diag_train['missing_count']} low_out={diag_train['low_outlier_count']} high_out={diag_train['high_outlier_count']} unk={diag_train['unk_count']}")
    print(f"- val:   rows={diag_val['n_rows']} missing={diag_val['missing_count']} low_out={diag_val['low_outlier_count']} high_out={diag_val['high_outlier_count']} unk={diag_val['unk_count']}")
    print(f"- test:  rows={diag_test['n_rows']} missing={diag_test['missing_count']} low_out={diag_test['low_outlier_count']} high_out={diag_test['high_outlier_count']} unk={diag_test['unk_count']}")
    print(f"- top tokens (train sample): {list(diag_train['top_tokens'].items())[:10]}")

    # Save artifacts
    t_save0 = time.perf_counter()
    tok_path = out_dir / "measurement_tokenizer_large_check.json"
    tok.save(tok_path)

    tok_roundtrip = OMOPMeasurementTokenizer.load(tok_path)
    if tok_roundtrip.get_vocab() != tok.get_vocab():
        print("ERROR: save/load vocab mismatch", file=sys.stderr)
        return 3
    if tok_roundtrip.get_selected_concepts() != tok.get_selected_concepts():
        print("ERROR: save/load selected concepts mismatch", file=sys.stderr)
        return 3

    # Save selected concepts
    concepts_path = out_dir / "selected_measurement_concepts.csv"
    pd.DataFrame({"selected": selected}).to_csv(concepts_path, index=False)

    # Save transformed samples (not full output)
    if args.save_transformed_sample:
        n_sample = int(args.sample_output_rows)
        (train_tok.head(n_sample)).to_csv(out_dir / "transformed_train_sample.csv", index=False)
        (val_tok.head(n_sample)).to_csv(out_dir / "transformed_val_sample.csv", index=False)
        (test_tok.head(n_sample)).to_csv(out_dir / "transformed_test_sample.csv", index=False)

    summary = {
        "dataset": {
            "path": str(measurement_path),
            "format": fmt,
            "rows_loaded": int(df.shape[0]),
            "columns": list(df.columns),
            "unique_persons": n_persons,
            "unique_measurement_concept_id": n_concepts,
            **numeric_stats,
        },
        "split": split_meta,
        "tokenizer_config": asdict(cfg),
        "fit_result": {
            "selected_concept_count": int(len(selected)),
            "vocab_size": int(len(vocab)),
            "first_20_selected_concepts": selected[:20],
            "top_train_concepts_by_numeric_frequency": top_train_concepts,
        },
        "diagnostics": {"train_sample": diag_train, "val_sample": diag_val, "test_sample": diag_test},
        "timings_s": timings,
        "memory_mb": mem,
        "cuda_info": cuda_info,
        "artifacts": {
            "tokenizer_json": str(tok_path),
            "summary_json": str(out_dir / "large_check_summary.json"),
            "selected_concepts_csv": str(concepts_path),
        },
    }

    (out_dir / "large_check_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    timings["save_s"] = time.perf_counter() - t_save0

    timings["total_s"] = time.perf_counter() - t0
    mem["end_mb"] = mem_mb()

    print("\n**Runtime**")
    print(f"- load_s: {timings['load_s']:.3f}")
    print(f"- split_s: {timings['split_s']:.3f}")
    print(f"- fit_s: {timings['fit_s']:.3f}")
    print(f"- transform_s: {timings['transform_s']:.3f}")
    print(f"- save_s: {timings['save_s']:.3f}")
    print(f"- total_s: {timings['total_s']:.3f}")

    if mem_mb() is not None:
        print("\n**Memory (RSS MB)**")
        for k, v in mem.items():
            if v is not None:
                print(f"- {k}: {v:.1f}")

    print("\nArtifacts written:")
    print(f"- {tok_path}")
    print(f"- {out_dir / 'large_check_summary.json'}")
    print(f"- {concepts_path}")
    if args.save_transformed_sample:
        print(f"- {out_dir / 'transformed_train_sample.csv'}")
        print(f"- {out_dir / 'transformed_val_sample.csv'}")
        print(f"- {out_dir / 'transformed_test_sample.csv'}")

    print("\nOK: large-data tokenizer check completed (fit on TRAIN only; transformed VAL/TEST).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
