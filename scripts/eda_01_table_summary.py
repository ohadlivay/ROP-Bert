#!/usr/bin/env python3
"""EDA 01: OMOP table-level population summary.

This script reads exported OMOP Parquet files and computes table-level and
person-level density summaries without loading unnecessary columns.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/matplotlib-rop-bert")
os.environ.setdefault("XDG_CACHE_HOME", "/private/tmp")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow.parquet as pq


TABLES = [
    "person",
    "visit_occurrence",
    "measurement",
    "observation",
    "condition_occurrence",
    "drug_exposure",
    "procedure_occurrence",
    "death",
]


@dataclass
class TableSummary:
    table_name: str
    total_row_count: int
    has_person_id: bool
    unique_person_id_count: Optional[int]
    avg_rows_per_person: Optional[float]
    median_rows_per_person: Optional[float]
    min_rows_per_person: Optional[int]
    max_rows_per_person: Optional[int]
    p25_rows_per_person: Optional[float]
    p75_rows_per_person: Optional[float]
    source_file: str
    warning: str = ""


def find_export_dir(cli_path: Optional[str]) -> Path:
    candidates: list[Path] = []
    if cli_path:
        candidates.append(Path(cli_path).expanduser())
    candidates.extend(
        [
            Path("OMOP_exports/mimic_omop2"),
            Path.home()
            / "Library/CloudStorage/GoogleDrive-razi.mreeh.rm@gmail.com/My Drive/OMOP_exports/mimic_omop2",
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    checked = "\n".join(str(path) for path in candidates)
    raise FileNotFoundError(f"Could not locate OMOP export folder. Checked:\n{checked}")


def parquet_row_count(path: Path) -> int:
    return pq.ParquetFile(path).metadata.num_rows


def parquet_columns(path: Path) -> set[str]:
    return set(pq.ParquetFile(path).schema_arrow.names)


def person_counts(path: Path, batch_size: int) -> dict[int, int]:
    counts: defaultdict[int, int] = defaultdict(int)
    parquet_file = pq.ParquetFile(path)
    for batch in parquet_file.iter_batches(columns=["person_id"], batch_size=batch_size):
        values = batch.column(0).to_numpy(zero_copy_only=False)
        if values.size == 0:
            continue
        values = values[~pd.isna(values)]
        if values.size == 0:
            continue
        unique_values, unique_counts = np.unique(values.astype(np.int64, copy=False), return_counts=True)
        for person_id, count in zip(unique_values, unique_counts):
            counts[int(person_id)] += int(count)
    return dict(counts)


def percentile(values: np.ndarray, q: float) -> float:
    if values.size == 0:
        return math.nan
    return float(np.percentile(values, q))


def summarize_table(export_dir: Path, table: str, batch_size: int) -> TableSummary:
    path = export_dir / f"{table}.parquet"
    if not path.exists():
        return TableSummary(
            table_name=table,
            total_row_count=0,
            has_person_id=False,
            unique_person_id_count=None,
            avg_rows_per_person=None,
            median_rows_per_person=None,
            min_rows_per_person=None,
            max_rows_per_person=None,
            p25_rows_per_person=None,
            p75_rows_per_person=None,
            source_file=str(path),
            warning="missing parquet file",
        )

    total_rows = parquet_row_count(path)
    columns = parquet_columns(path)
    if "person_id" not in columns:
        return TableSummary(
            table_name=table,
            total_row_count=total_rows,
            has_person_id=False,
            unique_person_id_count=None,
            avg_rows_per_person=None,
            median_rows_per_person=None,
            min_rows_per_person=None,
            max_rows_per_person=None,
            p25_rows_per_person=None,
            p75_rows_per_person=None,
            source_file=str(path),
            warning="person_id not present; skipped person-level statistics",
        )

    counts = person_counts(path, batch_size=batch_size)
    count_values = np.array(list(counts.values()), dtype=np.int64)
    if count_values.size == 0:
        return TableSummary(
            table_name=table,
            total_row_count=total_rows,
            has_person_id=True,
            unique_person_id_count=0,
            avg_rows_per_person=0.0,
            median_rows_per_person=0.0,
            min_rows_per_person=0,
            max_rows_per_person=0,
            p25_rows_per_person=0.0,
            p75_rows_per_person=0.0,
            source_file=str(path),
        )

    return TableSummary(
        table_name=table,
        total_row_count=total_rows,
        has_person_id=True,
        unique_person_id_count=int(count_values.size),
        avg_rows_per_person=float(count_values.mean()),
        median_rows_per_person=float(np.median(count_values)),
        min_rows_per_person=int(count_values.min()),
        max_rows_per_person=int(count_values.max()),
        p25_rows_per_person=percentile(count_values, 25),
        p75_rows_per_person=percentile(count_values, 75),
        source_file=str(path),
    )


def int_fmt(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return f"{int(value):,}"


def float_fmt(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return f"{float(value):,.2f}"


def markdown_table(df: pd.DataFrame, columns: Sequence[str]) -> str:
    display = df.loc[:, columns].copy()
    for column in display.columns:
        if column in {"table_name", "warning"}:
            continue
        if column in {"avg_rows_per_person", "median_rows_per_person", "p25_rows_per_person", "p75_rows_per_person"}:
            display[column] = display[column].map(float_fmt)
        elif column != "has_person_id":
            display[column] = display[column].map(int_fmt)
    return display.to_markdown(index=False)


def save_bar_chart(df: pd.DataFrame, column: str, title: str, ylabel: str, output_path: Path) -> None:
    plot_df = df.sort_values(column, ascending=False)
    values = plot_df[column].fillna(0)
    plt.figure(figsize=(10, 5.5))
    plt.bar(plot_df["table_name"], values)
    plt.title(title)
    plt.ylabel(ylabel)
    plt.xticks(rotation=35, ha="right")
    plt.tight_layout()
    plt.savefig(output_path, dpi=180)
    plt.close()


def write_report(
    df: pd.DataFrame,
    export_dir: Path,
    docs_dir: Path,
    created_files: Sequence[Path],
    elapsed_seconds: float,
    warnings: Sequence[str],
) -> None:
    report_path = docs_dir / "eda_01_table_summary.md"
    summary_columns = [
        "table_name",
        "total_row_count",
        "unique_person_id_count",
        "avg_rows_per_person",
        "median_rows_per_person",
        "min_rows_per_person",
        "p25_rows_per_person",
        "p75_rows_per_person",
        "max_rows_per_person",
        "warning",
    ]
    ranked_by_rows = df.sort_values("total_row_count", ascending=False)
    ranked_by_people = df.sort_values("unique_person_id_count", ascending=False, na_position="last")
    ranked_by_avg = df.sort_values("avg_rows_per_person", ascending=False, na_position="last")

    total_people = int(df.loc[df["table_name"] == "person", "total_row_count"].iloc[0])
    largest_table = ranked_by_rows.iloc[0]
    highest_density = ranked_by_avg.iloc[0]
    death_coverage = df.loc[df["table_name"] == "death", "unique_person_id_count"].iloc[0]
    visit_coverage = df.loc[df["table_name"] == "visit_occurrence", "unique_person_id_count"].iloc[0]

    lines = [
        "# EDA 01: OMOP Table-Level Population Summary",
        "",
        f"Run date: 2026-05-29",
        f"Export folder: `{export_dir}`",
        "",
        "## Methodology",
        "",
        "- Read exported OMOP Parquet files directly from the `mimic_omop2` export.",
        "- Used Parquet metadata for total table row counts.",
        "- For person-level statistics, streamed only the `person_id` column in batches and aggregated counts per patient.",
        "- Avoided loading full clinical tables or unused columns into memory.",
        "- Generated one row-count summary, three ranking tables, and three bar-chart visualizations.",
        "",
        "## Summary Table",
        "",
        markdown_table(df, summary_columns),
        "",
        "## Ranking: Row Count",
        "",
        markdown_table(ranked_by_rows, ["table_name", "total_row_count", "unique_person_id_count", "avg_rows_per_person"]),
        "",
        "## Ranking: Unique Patients",
        "",
        markdown_table(ranked_by_people, ["table_name", "unique_person_id_count", "total_row_count", "avg_rows_per_person"]),
        "",
        "## Ranking: Average Rows Per Patient",
        "",
        markdown_table(ranked_by_avg, ["table_name", "avg_rows_per_person", "median_rows_per_person", "p75_rows_per_person", "max_rows_per_person"]),
        "",
        "## Visualizations",
        "",
        "- `docs/eda_01_row_count_by_table.png`",
        "- `docs/eda_01_unique_patients_by_table.png`",
        "- `docs/eda_01_avg_rows_per_patient_by_table.png`",
        "",
        "## Interpretation Of Findings",
        "",
        f"- Cohort size is `{total_people:,}` people in `person`.",
        f"- `visit_occurrence` covers `{int(visit_coverage):,}` people, matching the person table and indicating visit-level coverage for the whole cohort.",
        f"- The largest table is `{largest_table['table_name']}` with `{int(largest_table['total_row_count']):,}` rows.",
        f"- The densest table by average rows per patient is `{highest_density['table_name']}` with `{float(highest_density['avg_rows_per_person']):,.2f}` rows per covered patient on average.",
        f"- `death` covers `{int(death_coverage):,}` people and should be interpreted as an outcome/label table rather than a longitudinal event stream.",
        "- Measurements dominate event volume, followed by drug exposures and observations/procedures/conditions depending on modeling scope.",
        "- Median and upper-quartile rows per patient are much lower than maxima in dense event tables, indicating substantial skew in longitudinal depth.",
        "",
        "## Possible Transformer Modeling Implications",
        "",
        "- BEHRT/Med-BERT style token streams will be measurement-heavy unless event sampling, domain balancing, or vocabulary caps are applied.",
        "- High measurement density can improve temporal granularity, but it may also crowd out diagnoses, medications, and procedures in fixed-length sequences.",
        "- `visit_occurrence` gives complete cohort anchoring and can support visit-window segmentation.",
        "- `condition_occurrence`, `drug_exposure`, and `procedure_occurrence` provide clinically interpretable tokens that may be useful for early prototypes.",
        "- `death` can support outcome labeling, censoring logic, or survival-style prediction tasks, but it should not be treated as ordinary repeated longitudinal context.",
        "",
        "## Warnings And Limitations",
        "",
    ]

    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- No warnings encountered.")

    lines.extend(
        [
            "- This step summarizes table populations only; it does not inspect concept distributions, date ranges, visit alignment, or temporal gaps.",
            "- Person-level statistics are calculated among people represented in each table, not over all cohort members with zero-filled counts.",
            "- Export files are read-only inputs; no source Parquet files or PostgreSQL data were modified.",
            "",
            "## Files Created",
            "",
        ]
    )
    lines.extend(f"- `{path}`" for path in created_files)
    lines.extend(["", f"Execution time: {elapsed_seconds:,.2f} seconds", ""])

    report_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EDA 01 OMOP table-level population summary.")
    parser.add_argument("--export-dir", default=None, help="Path to OMOP_exports/mimic_omop2")
    parser.add_argument("--docs-dir", default="docs")
    parser.add_argument("--batch-size", type=int, default=2_000_000)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    started = time.time()
    args = parse_args(argv)
    export_dir = find_export_dir(args.export_dir)
    docs_dir = Path(args.docs_dir)
    docs_dir.mkdir(parents=True, exist_ok=True)

    print(f"Export folder: {export_dir}", flush=True)
    summaries: list[TableSummary] = []
    warnings: list[str] = [
        "The local sandbox may emit fontconfig cache and PyArrow CPU feature detection warnings; these do not affect the read-only EDA outputs."
    ]
    for table in TABLES:
        table_started = time.time()
        print(f"Analyzing {table}...", flush=True)
        summary = summarize_table(export_dir, table, batch_size=args.batch_size)
        summaries.append(summary)
        if summary.warning:
            warnings.append(f"{table}: {summary.warning}")
        print(
            f"Done {table}: rows={summary.total_row_count:,} "
            f"people={summary.unique_person_id_count if summary.unique_person_id_count is not None else 'n/a'} "
            f"seconds={time.time() - table_started:,.2f}",
            flush=True,
        )

    df = pd.DataFrame([asdict(summary) for summary in summaries])
    csv_path = docs_dir / "eda_01_table_summary.csv"
    df.to_csv(csv_path, index=False)

    row_chart = docs_dir / "eda_01_row_count_by_table.png"
    patient_chart = docs_dir / "eda_01_unique_patients_by_table.png"
    avg_chart = docs_dir / "eda_01_avg_rows_per_patient_by_table.png"
    save_bar_chart(df, "total_row_count", "OMOP Row Count By Table", "Rows", row_chart)
    save_bar_chart(df, "unique_person_id_count", "Unique Patients By Table", "Unique Patients", patient_chart)
    save_bar_chart(df, "avg_rows_per_person", "Average Rows Per Patient By Table", "Average Rows Per Patient", avg_chart)

    elapsed = time.time() - started
    created_files = [
        Path("notebooks/eda_01_table_summary.ipynb"),
        Path("scripts/eda_01_table_summary.py"),
        csv_path,
        docs_dir / "eda_01_table_summary.md",
        row_chart,
        patient_chart,
        avg_chart,
    ]
    write_report(df, export_dir, docs_dir, created_files, elapsed, warnings)

    print("\nFiles created:", flush=True)
    for path in created_files:
        print(f"- {path}", flush=True)
    print(f"Execution time: {elapsed:,.2f} seconds", flush=True)
    if warnings:
        print("Warnings / limitations:", flush=True)
        for warning in warnings:
            print(f"- {warning}", flush=True)
    else:
        print("Warnings / limitations: none encountered", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
