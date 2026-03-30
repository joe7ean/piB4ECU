#!/usr/bin/env python3
"""
Telemetry log visualizer for piB4ECU.

Reads engine telemetry JSONL/JSONL.GZ logs and creates interactive HTML charts
for single-run and multi-run comparisons.
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
from typing import Iterable


def _import_optional_deps():
    try:
        import pandas as pd  # type: ignore
        import plotly.express as px  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "Missing optional dependencies. Install with:\n"
            "  pip install -r requirements-analysis.txt"
        ) from exc
    return pd, px


def _iter_log_lines(path: Path) -> Iterable[str]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            yield from f
        return
    with path.open("r", encoding="utf-8") as f:
        yield from f


def _load_rows(log_files: list[Path]) -> list[dict]:
    rows: list[dict] = []
    for log_path in log_files:
        run_id = log_path.name.replace(".jsonl.gz", "").replace(".jsonl", "")
        for line in _iter_log_lines(log_path):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            row = {
                "run_id": run_id,
                "ts_utc": raw.get("ts_utc"),
                "tick": raw.get("tick"),
                "engine_connected": raw.get("engine", {}).get("connected"),
            }
            for key, value in (raw.get("engine", {}).get("data", {}) or {}).items():
                col_name = f"metric::{key}"
                if isinstance(value, dict):
                    row[col_name] = value.get("value")
                    unit = value.get("unit")
                    if unit is not None:
                        row[f"unit::{key}"] = unit
                else:
                    row[col_name] = value
            rows.append(row)
    return rows


def _discover_logs(log_dir: Path) -> list[Path]:
    patterns = ("engine-telemetry-*.jsonl", "engine-telemetry-*.jsonl.gz")
    files: list[Path] = []
    for pattern in patterns:
        files.extend(log_dir.glob(pattern))
    return sorted(files)


def _validate_metric(df, metric: str):
    col = f"metric::{metric}"
    if col in df.columns:
        return col
    metric_columns = sorted(c for c in df.columns if c.startswith("metric::"))
    available = "\n".join(f"  - {c.removeprefix('metric::')}" for c in metric_columns[:40])
    if len(metric_columns) > 40:
        available += f"\n  ... ({len(metric_columns) - 40} more)"
    raise SystemExit(
        f"Metric '{metric}' not found.\nAvailable metrics:\n{available if available else '  (none)'}"
    )


def _write_plot(fig, out_file: Path):
    out_file.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(out_file), include_plotlyjs="cdn")
    print(f"Wrote chart: {out_file}")


def cmd_list_metrics(df):
    metric_columns = sorted(c for c in df.columns if c.startswith("metric::"))
    if not metric_columns:
        print("No metrics found in logs.")
        return
    for c in metric_columns:
        print(c.removeprefix("metric::"))


def cmd_plot_metric(df, px, metric: str, out_file: Path):
    metric_col = _validate_metric(df, metric)
    plot_df = df[["run_id", "ts", metric_col]].dropna()
    if plot_df.empty:
        raise SystemExit(f"No values available for metric '{metric}'.")
    fig = px.line(
        plot_df,
        x="ts",
        y=metric_col,
        color="run_id",
        title=f"Telemetry metric comparison: {metric}",
        labels={metric_col: metric},
    )
    fig.update_layout(legend_title_text="run_id")
    _write_plot(fig, out_file)


def cmd_plot_pair(df, px, x_metric: str, y_metric: str, out_file: Path):
    x_col = _validate_metric(df, x_metric)
    y_col = _validate_metric(df, y_metric)
    plot_df = df[["run_id", x_col, y_col]].dropna()
    if plot_df.empty:
        raise SystemExit(f"No overlapping values for pair '{x_metric}' and '{y_metric}'.")
    fig = px.scatter(
        plot_df,
        x=x_col,
        y=y_col,
        color="run_id",
        title=f"Telemetry scatter: {y_metric} vs {x_metric}",
        labels={x_col: x_metric, y_col: y_metric},
    )
    fig.update_layout(legend_title_text="run_id")
    _write_plot(fig, out_file)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Visualize piB4ECU telemetry logs.")
    parser.add_argument(
        "--log-dir",
        default="logs",
        help="Directory with engine-telemetry-*.jsonl(.gz) files (default: logs)",
    )
    parser.add_argument(
        "--run-filter",
        default="",
        help="Substring filter applied to run_id/file names before plotting",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-metrics", help="List all discovered telemetry metric names")

    p_metric = sub.add_parser("plot-metric", help="Plot one metric over time (all runs)")
    p_metric.add_argument("--metric", required=True, help="Metric name as shown by list-metrics")
    p_metric.add_argument("--out", default="analysis/out/metric.html", help="Output HTML path")

    p_pair = sub.add_parser("plot-pair", help="Scatter plot comparing two metrics")
    p_pair.add_argument("--x", required=True, help="X axis metric")
    p_pair.add_argument("--y", required=True, help="Y axis metric")
    p_pair.add_argument("--out", default="analysis/out/pair.html", help="Output HTML path")

    return parser.parse_args()


def main():
    args = parse_args()
    pd, px = _import_optional_deps()

    log_dir = Path(args.log_dir)
    log_files = _discover_logs(log_dir)
    if args.run_filter:
        log_files = [p for p in log_files if args.run_filter in p.name]
    if not log_files:
        raise SystemExit(f"No telemetry log files found in: {log_dir}")

    rows = _load_rows(log_files)
    if not rows:
        raise SystemExit("No parsable telemetry rows found.")

    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts_utc"], utc=True, errors="coerce")
    df = df.sort_values(["run_id", "ts", "tick"], na_position="last")

    if args.cmd == "list-metrics":
        cmd_list_metrics(df)
    elif args.cmd == "plot-metric":
        cmd_plot_metric(df, px, args.metric, Path(args.out))
    elif args.cmd == "plot-pair":
        cmd_plot_pair(df, px, args.x, args.y, Path(args.out))
    else:
        raise SystemExit(f"Unknown command: {args.cmd}")


if __name__ == "__main__":
    main()
