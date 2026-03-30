#!/usr/bin/env python3
"""
Streamlit UI for piB4ECU telemetry logs.

Run:
  streamlit run tools/telemetry_app.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from telemetry_viewer import _discover_logs, _load_rows


st.set_page_config(page_title="piB4ECU Telemetry Viewer", layout="wide")
st.title("piB4ECU Telemetry Viewer")
st.caption("Interactive comparison of engine telemetry runs")

repo_root = Path(__file__).resolve().parents[1]
default_log_dir = os.environ.get("ECU_LOG_DIR", str(repo_root / "logs"))
log_dir_str = st.sidebar.text_input("Log directory", value=default_log_dir)
run_filter = st.sidebar.text_input("Run filter (substring)", value="")

log_dir = Path(log_dir_str)
log_files = _discover_logs(log_dir)
if run_filter:
    log_files = [p for p in log_files if run_filter in p.name]

if not log_files:
    st.error(f"No telemetry log files found in '{log_dir}'.")
    st.info(
        "Tip: default is ECU_LOG_DIR if set, otherwise <repo-root>/logs. "
        "You can paste an absolute path here."
    )
    st.stop()

rows = _load_rows(log_files)
if not rows:
    st.error("No parsable telemetry rows found.")
    st.stop()

df = pd.DataFrame(rows)
df["ts"] = pd.to_datetime(df["ts_utc"], utc=True, errors="coerce")
df = df.sort_values(["run_id", "ts", "tick"], na_position="last")

metric_cols = sorted(c for c in df.columns if c.startswith("metric::"))
metrics = [c.removeprefix("metric::") for c in metric_cols]
run_ids = sorted(df["run_id"].dropna().unique().tolist())

st.sidebar.markdown("---")
selected_runs = st.sidebar.multiselect("Runs", options=run_ids, default=run_ids[-5:] if len(run_ids) > 5 else run_ids)
show_scatter = st.sidebar.checkbox("Show scatter plot", value=True)

if selected_runs:
    df = df[df["run_id"].isin(selected_runs)]

if df.empty:
    st.warning("No data left after run selection/filter.")
    st.stop()

col1, col2 = st.columns(2)
with col1:
    metric_main = st.selectbox("Main metric (timeseries)", options=metrics, index=0 if metrics else None)
with col2:
    metric_second = st.selectbox(
        "Second metric (for scatter)",
        options=metrics,
        index=1 if len(metrics) > 1 else 0 if metrics else None,
    )

if not metric_main:
    st.error("No telemetry metrics found.")
    st.stop()

main_col = f"metric::{metric_main}"
plot_df = df[["run_id", "ts", main_col]].dropna()
if plot_df.empty:
    st.warning(f"No values for metric '{metric_main}'.")
else:
    fig = px.line(
        plot_df,
        x="ts",
        y=main_col,
        color="run_id",
        title=f"{metric_main} over time",
        labels={main_col: metric_main},
    )
    fig.update_layout(legend_title_text="run_id")
    st.plotly_chart(fig, use_container_width=True)

if show_scatter and metric_second:
    x_col = f"metric::{metric_main}"
    y_col = f"metric::{metric_second}"
    pair_df = df[["run_id", x_col, y_col]].dropna()
    if pair_df.empty:
        st.info(f"No overlapping values for '{metric_main}' and '{metric_second}'.")
    else:
        fig2 = px.scatter(
            pair_df,
            x=x_col,
            y=y_col,
            color="run_id",
            title=f"{metric_second} vs {metric_main}",
            labels={x_col: metric_main, y_col: metric_second},
        )
        fig2.update_layout(legend_title_text="run_id")
        st.plotly_chart(fig2, use_container_width=True)

with st.expander("Data preview"):
    st.dataframe(df.head(200), use_container_width=True)
