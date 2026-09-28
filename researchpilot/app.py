"""Streamlit User Interface for ResearchPilot.

Provides interactive goal entry, intent inspection, deliberate failure simulation toggle,
live planning and execution traces, and structured final report presentation.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
from agent.graph import run_agent
from agent.planner import validate_goal, classify_intent

st.set_page_config(
    page_title="ResearchPilot — Autonomous Research Agent",
    page_icon="🧭",
    layout="wide",
)

st.title("🧭 ResearchPilot")
st.caption("Autonomous Research & Analysis Agent with Intent-Aware Planning, Relevance Validation & Self-Healing Recovery")

# Sidebar Configuration
with st.sidebar:
    st.header("⚙️ Agent Controls")
    simulate_failure = st.checkbox(
        "Simulate Failure (Demo Recovery)",
        value=False,
        help="Deliberately triggers an initial tool failure to demonstrate autonomous detection, retry, and recovery routing.",
    )

    st.markdown("---")
    st.subheader("🛠️ Available Tools")
    st.markdown("""
    - **`web_search`**: Live discovery via query decomposition and URL extraction.
    - **`read_url`**: Content extraction, HTML cleansing, and source verification.
    - **`synthesize`**: Aggregation and insight synthesis.
    """)

    st.markdown("---")
    st.subheader("💡 Sample Goals")
    sample_queries = [
        "Research the latest global news",
        "Research the latest developments in AI agents and identify three important trends.",
        "Research recent AI agent frameworks and compare LangGraph vs AutoGen.",
        "hello",  # Edge case
    ]
    selected_sample = st.selectbox("Load sample goal:", ["Custom..."] + sample_queries)

# Main Goal Input Area
default_goal = (
    selected_sample
    if selected_sample != "Custom..."
    else "Research the latest global news"
)

user_goal = st.text_area(
    "Research Goal:",
    value=default_goal,
    height=90,
    placeholder="Enter a natural-language research question or topic...",
)

col_run, col_clear = st.columns([1, 5])
with col_run:
    run_clicked = st.button("🚀 Run Research", type="primary", use_container_width=True)

if run_clicked:
    if not user_goal.strip():
        st.warning("Please provide a valid research goal.")
    else:
        # Pre-validate goal
        val = validate_goal(user_goal)
        if not val.is_valid:
            st.error(f"Goal Validation Error: {val.reason}")
        else:
            with st.spinner("ResearchPilot agent is running..."):
                final_state = run_agent(user_goal, simulate_failure=simulate_failure)

            report = final_state.final_report or {}
            stats = report.get("execution_stats", {})
            intent = report.get("intent") or {}
            goal_completion = report.get("goal_completion") or {}

            # Status banner
            status_val = report.get("status", "COMPLETED")
            if status_val == "COMPLETED":
                st.success(f"Execution COMPLETED — Research goal fully satisfied!")
            elif status_val == "PARTIAL":
                st.warning(f"Execution PARTIAL — Tasks executed, but goal requirements were partially satisfied.")
            else:
                st.error(f"Execution FAILED — Goal requirements could not be satisfied.")

            # 1. Executive Metrics Bar
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Status", status_val)
            m2.metric("Intent", intent.get("category", "GENERAL"))
            m3.metric("Tasks Completed", f"{stats.get('tasks_completed', 0)} / {stats.get('tasks', 0)}")
            m4.metric("Failures Detected", stats.get("failures", 0))
            m5.metric("Recovery Actions", len(report.get("recovery_actions", [])))

            # Tabs for Plan, Trace, Report, and Raw Output
            tab_report, tab_trace, tab_plan, tab_raw = st.tabs(
                ["📑 Final Report", "⚡ Execution Trace", "📋 Structured Plan", "📦 Raw JSON"]
            )

            with tab_report:
                # Intent & Goal Header
                st.subheader("Research Goal & Intent")
                st.info(f"**Goal:** {report.get('goal', user_goal)}\n\n"
                        f"**Intent Category:** `{intent.get('category', 'N/A')}` | "
                        f"**Freshness Required:** `{intent.get('freshness_required', False)}` | "
                        f"**Scope:** `{intent.get('geographic_scope', 'General')}`")

                # Goal Completion Check Callout
                if goal_completion:
                    if goal_completion.get("completed"):
                        st.success(f"✓ **Goal Verification:** {goal_completion.get('reason')}")
                    else:
                        st.warning(f"⚠ **Goal Completion Alert:** {goal_completion.get('reason')}\n\n"
                                   f"Missing requirements: {', '.join(goal_completion.get('missing_requirements', []))}")

                st.subheader("Executive Summary")
                st.write(report.get("summary", "No summary generated."))

                st.subheader("Key Findings")
                findings = report.get("findings", [])
                if findings:
                    for i, finding in enumerate(findings, 1):
                        st.markdown(f"**{i}.** {finding}")
                else:
                    st.write("No findings recorded.")

                st.subheader("Verified Sources")
                sources = report.get("sources", [])
                if sources:
                    for s in sources:
                        title = s.get("title") or "Source Link"
                        url = s.get("url")
                        snippet = s.get("snippet", "")
                        st.markdown(f"- **[{title}]({url})**")
                        if snippet:
                            st.caption(snippet[:200] + "...")
                else:
                    st.write("No sources collected.")

                recovery_actions = report.get("recovery_actions", [])
                if recovery_actions:
                    st.subheader("🛠️ Autonomous Recovery Actions")
                    for act in recovery_actions:
                        st.warning(f"• {act}")

            with tab_trace:
                st.subheader("Agent Execution Audit Trace")
                trace_lines = final_state.execution_trace or []
                for line in trace_lines:
                    if "✖" in line:
                        st.error(line)
                    elif "⚠" in line:
                        st.warning(line)
                    elif "↻" in line:
                        st.info(line)
                    elif "✓" in line:
                        st.success(line)
                    else:
                        st.text(line)

            with tab_plan:
                st.subheader("Intent-Aware Plan Decomposition")
                plan_items = final_state.plan or []
                for item in plan_items:
                    st.markdown(
                        f"**Step {item.get('id')}:** `{item.get('tool')}` — {item.get('description')}"
                    )
                    st.caption(f"Input: `{item.get('input')}` | Status: `{item.get('status')}`")

            with tab_raw:
                st.subheader("State & Report JSON")
                st.json(report)
                st.download_button(
                    label="Download Report JSON",
                    data=json.dumps(report, indent=2),
                    file_name="researchpilot_report.json",
                    mime="application/json",
                )
