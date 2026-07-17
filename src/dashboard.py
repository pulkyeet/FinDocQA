"""Streamlit comparison view for eval results (Plan §13, W3).

Usage (from repo root):
    streamlit run src/dashboard.py

Shows config x metric x question-type matrix from results.csv.
"""

import os
import sys

import pandas as pd
import streamlit as st

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
from config import EVAL_DIR

RESULTS_PATH = os.path.join(_SCRIPT_DIR, EVAL_DIR, "results.csv")


@st.cache_data
def load_results():
    return pd.read_csv(RESULTS_PATH)


def main():
    st.set_page_config(page_title="FinDocQA Eval Dashboard", layout="wide")
    st.title("FinDocQA — Eval Harness Results")

    try:
        df = load_results()
    except FileNotFoundError:
        st.error(f"Results file not found: {RESULTS_PATH}\n\nRun `make eval` first.")
        return

    st.sidebar.header("Filters")
    configs = sorted(df["config"].unique())
    sel_configs = st.sidebar.multiselect("Configs", configs, default=configs)
    types = sorted(df["question_type"].unique())
    sel_types = st.sidebar.multiselect("Question types", types, default=types)
    filtered = df[df["config"].isin(sel_configs) & df["question_type"].isin(sel_types)]

    tab1, tab2, tab3, tab4 = st.tabs(
        ["Overview", "Per-type breakdown", "Failure taxonomy", "Question explorer"]
    )

    # ---------- Tab 1: Overview ----------
    with tab1:
        st.subheader("Summary by config")
        summary = (
            filtered.groupby("config")
            .agg(
                total=("joint_correct", "count"),
                joint_ok=("joint_correct", "sum"),
                rec_hit=("retrieval_hit", "sum"),
                route_ok=("route_result", lambda x: (x == "correct").sum()),
                num_ok=("numeric_match", lambda x: (x == True).sum()),
                num_total=("numeric_match", "count"),
            )
            .reset_index()
        )
        summary["num_match"] = summary.apply(
            lambda r: f"{int(r['num_ok'])}/{int(r['num_total'])}" if r["num_total"] > 0 else "-",
            axis=1,
        )
        summary["joint_pct"] = (summary["joint_ok"] / summary["total"] * 100).round(1)
        st.dataframe(
            summary[["config", "total", "joint_ok", "joint_pct", "rec_hit", "route_ok", "num_match"]],
            hide_index=True,
            use_container_width=True,
        )

        best_config = summary.loc[summary["joint_ok"].idxmax(), "config"]
        st.metric("Best config", best_config, f"{summary['joint_pct'].max()}% joint")

    # ---------- Tab 2: Per-type breakdown ----------
    with tab2:
        st.subheader("Joint correct by config × question type")
        pt = filtered.pivot_table(
            index="config",
            columns="question_type",
            values="joint_correct",
            aggfunc="sum",
            margins=True,
            margins_name="Total",
        )
        st.dataframe(pt, use_container_width=True)

        st.subheader("Retrieval hit by config × question type")
        pt2 = filtered.pivot_table(
            index="config",
            columns="question_type",
            values="retrieval_hit",
            aggfunc="sum",
            margins=True,
            margins_name="Total",
        )
        st.dataframe(pt2, use_container_width=True)

    # ---------- Tab 3: Failure taxonomy ----------
    with tab3:
        st.subheader("Failure buckets by config (Plan §9)")
        bucket_order = [
            "retrieval_miss", "table_mangle", "wrong_abstention",
            "false_positive", "web_search_miss", "wrong_routing", "generation_error",
        ]
        bucket_cols = [b for b in bucket_order if b in filtered.columns]
        if "failure_bucket" in filtered.columns:
            fb = (
                filtered[filtered["failure_bucket"] != ""]
                .pivot_table(
                    index="config",
                    columns="failure_bucket",
                    aggfunc="size",
                    fill_value=0,
                )
            )
            for b in bucket_order:
                if b not in fb.columns:
                    fb[b] = 0
            fb = fb[bucket_order]
            total = filtered.groupby("config").size()
            fb["joint_ok"] = filtered[filtered["joint_correct"]].groupby("config").size()
            fb["total"] = total
            st.dataframe(fb, use_container_width=True)

            # Bar chart of failures
            if not fb.empty:
                st.bar_chart(fb[bucket_order])
        else:
            st.info("Run `make eval` to populate failure_bucket column.")

    # ---------- Tab 4: Question explorer ----------
    with tab4:
        st.subheader("Explore individual questions")
        qids = sorted(filtered["question_id"].unique())
        sel_qid = st.selectbox("Question ID", qids)
        sel_config = st.selectbox("Config", sel_configs)

        row = filtered[(filtered["question_id"] == sel_qid) & (filtered["config"] == sel_config)]
        if not row.empty:
            r = row.iloc[0]
            cols = st.columns(3)
            cols[0].metric("Joint", "✅" if r["joint_correct"] else "❌")
            cols[1].metric("Retrieval hit", "✅" if r["retrieval_hit"] else "❌")
            cols[2].metric("Route", r["route_result"])
            st.text_area("Answer preview", r["answer_preview"], height=150)
            if "failure_bucket" in r and r["failure_bucket"]:
                st.caption(f"Failure bucket: {r['failure_bucket']}")
        else:
            st.info("No data for this combination.")


if __name__ == "__main__":
    main()
