import time
from typing import Any

import streamlit as st

from src.job_search.manual_jobs import add_manual_job
from src.job_search.pipeline import (
    get_latest_search_run_summary,
    get_search_evaluation_queue_summary,
    run_job_discovery,
    run_job_evaluation,
)
from src.job_search.profiles import get_active_search_profile
from src.job_search.sidebar import require_selected_search

st.set_page_config(
    page_title="Run Job Search",
    page_icon="🔎",
    layout="wide",
)

search_id = require_selected_search()
profile = get_active_search_profile(search_id)

st.title("Run Job Search")
st.caption("Run Freehire discovery or add an external posting, then evaluate eligible jobs with your LLM.")

if profile is None:
    st.warning("This search has no active profile yet.")
    st.page_link(
        "pages/search_configuration.py",
        label="Configure this search",
        icon="⚙️",
    )
else:
    st.write(
        f"Active profile: **Version {profile['version']}** · "
        f"Evaluation model: **{profile['evaluation_config']['model']}**"
    )

st.header("1. Freehire job discovery")
st.write(
    "Search Freehire using the active discovery settings, save the listings, "
    "and apply your local filters. This step does not call the LLM."
)

discovery_key = f"latest_discovery_result_{search_id}"
if st.button(
    "Run Freehire discovery",
    type="primary",
    disabled=profile is None,
    key="run_freehire_discovery",
):
    try:
        with st.spinner("Searching Freehire and filtering discovered listings..."):
            st.session_state[discovery_key] = run_job_discovery(search_id)
    except Exception as error:
        st.error(f"Job discovery could not be completed: {error}")

summary = get_latest_search_run_summary(search_id)
queue_summary = get_search_evaluation_queue_summary(search_id)
discovery_col1, discovery_col2, discovery_col3 = st.columns(3)
discovery_col1.metric(
    "Latest search run completed",
    summary["completed_at"] or "Not run",
)
discovery_col2.metric(
    "Unique unevaluated jobs",
    queue_summary["unevaluated_jobs"],
)
discovery_col3.metric("Search run status", summary["status"] or "Not run")

if summary["started_at"]:
    st.caption(f"Latest search run started: {summary['started_at']}")

last_discovery = st.session_state.get(discovery_key)
if last_discovery and last_discovery["search_run_id"] == summary["search_run_id"]:
    st.success(
        f"Discovery finished: {last_discovery['discovery']['unique_jobs']} "
        f"unique jobs found; {last_discovery['filtering']['passed']} passed filtering."
    )

if summary["status"] == "failed":
    st.warning("The latest search run failed. Start another run to retry it.")

st.divider()
manual_result_key = f"manual_job_result_{search_id}"
with st.expander("2. Add a job manually", expanded=False):
    st.write(
        "Add a posting from another source to this search. Title, company, source "
        "URL, and job description are required; the remaining fields are optional."
    )

    with st.form("add_manual_job_form", clear_on_submit=True):
        manual_title = st.text_input("Job title *")
        manual_company = st.text_input("Company *")
        manual_url = st.text_input(
            "Source URL *",
            help="Use the original job posting URL, beginning with http:// or https://.",
        )
        manual_description = st.text_area("Job description *", height=220)

        optional_col1, optional_col2, optional_col3 = st.columns(3)
        with optional_col1:
            manual_location = st.text_input("Location (optional)")
        with optional_col2:
            manual_work_mode = st.selectbox(
                "Work setup (optional)",
                options=["Not specified", "Remote", "Hybrid", "On-site"],
            )
        with optional_col3:
            manual_employment_type = st.selectbox(
                "Employment type (optional)",
                options=["Not specified", "Full-time", "Contract", "Part-time"],
            )

        manual_submitted = st.form_submit_button(
            "Add job to this search",
            type="primary",
            disabled=profile is None,
        )

if manual_submitted:
    work_mode_value = {
        "Not specified": None,
        "Remote": "remote",
        "Hybrid": "hybrid",
        "On-site": "onsite",
    }[manual_work_mode]
    employment_type_value = {
        "Not specified": None,
        "Full-time": "full_time",
        "Contract": "contract",
        "Part-time": "part_time",
    }[manual_employment_type]
    try:
        with st.spinner("Adding the job and applying your local filters..."):
            st.session_state[manual_result_key] = add_manual_job(
                search_id,
                {
                    "title": manual_title,
                    "company": manual_company,
                    "url": manual_url,
                    "description": manual_description,
                    "location": manual_location,
                    "work_mode": work_mode_value,
                    "employment_type": employment_type_value,
                },
            )
        st.rerun()
    except Exception as error:
        st.error(f"Could not add the job: {error}")

manual_result = st.session_state.get(manual_result_key)
if manual_result:
    if manual_result["already_evaluated"]:
        st.info("This canonical job already has an evaluation and will not be evaluated again.")
    elif manual_result["ready_for_evaluation"]:
        st.success("Job added and passed filtering. It is ready for LLM evaluation below.")
    if not manual_result["ready_for_evaluation"]:
        st.warning(f"Job added, but it did not pass the active local filters: {manual_result['processing_reason']}")

st.divider()
st.header("3. LLM evaluation")
st.write(
    "Evaluate only jobs marked ready above. Evaluation can run in bounded batches; "
    "you can return to this section to continue the queue later."
)
st.caption(
    "The queue covers all discovery runs for the selected search. Canonical jobs "
    "with an existing evaluation are skipped, including evaluations from other searches."
)

settings_col, batches_col = st.columns(2)
with settings_col:
    batch_size = st.number_input(
        "Jobs per evaluation batch",
        min_value=1,
        value=10,
        step=1,
        help="Maximum jobs sent to the LLM in each batch.",
    )
with batches_col:
    max_batches = st.number_input(
        "Batches per evaluation click",
        min_value=1,
        value=1,
        step=1,
        help="After this many batches, any remaining jobs stay ready for a later continuation.",
    )

can_evaluate = profile is not None and queue_summary["unevaluated_jobs"] > 0

if not can_evaluate:
    if profile is None:
        st.info("Save an active profile before evaluating jobs.")
    elif queue_summary["unevaluated_jobs"] == 0:
        st.info("No jobs are currently ready for evaluation.")

evaluation_key = (
    f"evaluation_result_{search_id}_{summary['search_run_id']}" if summary["search_run_id"] is not None else None
)
if st.button(
    "Start / continue LLM evaluation",
    disabled=not can_evaluate,
    key="run_llm_evaluation",
):
    try:
        progress_total = min(
            queue_summary["unevaluated_jobs"], int(batch_size) * int(max_batches)
        )
        progress_bar = st.progress(0, text=f"Evaluating jobs: 0/{progress_total}")
        started_at = time.perf_counter()
        progress_state = {"completed": 0}

        def update_evaluation_progress(result: dict[str, Any]) -> None:
            """Update the progress bar after one job finishes.

            Args:
                result (dict[str, Any]): Completed job result.
            """
            now = time.perf_counter()
            progress_state["completed"] += 1
            count = progress_state["completed"]
            elapsed = now - started_at
            average_per_job = elapsed / count
            title = result.get("title") or result.get("job_id") or "job"
            elapsed_minutes, elapsed_seconds = divmod(int(elapsed), 60)
            progress_bar.progress(
                min(count / progress_total, 1.0),
                text=(
                    f"Evaluating jobs: {count}/{progress_total} · {title} · "
                    f"{elapsed_minutes}m {elapsed_seconds:02d}s elapsed · "
                    f"{average_per_job:.1f}s/job average"
                ),
            )

        latest_evaluation = run_job_evaluation(
            search_id=search_id,
            batch_size=int(batch_size),
            max_batches=int(max_batches),
            progress_callback=update_evaluation_progress,
        )
        latest_evaluation["elapsed_seconds"] = time.perf_counter() - started_at

        previous = st.session_state.get(evaluation_key)
        if previous:
            combined = dict(previous)
            for field in ("batches_processed", "total_processed", "evaluated", "failed"):
                combined[field] += latest_evaluation[field]
            combined["elapsed_seconds"] = (
                previous.get("elapsed_seconds", 0) + latest_evaluation["elapsed_seconds"]
            )
            combined["remaining"] = latest_evaluation["remaining"]
            combined["run_status"] = latest_evaluation["run_status"]
            combined["batch_results"] = previous["batch_results"] + latest_evaluation["batch_results"]
            latest_evaluation = combined

        st.session_state[evaluation_key] = latest_evaluation
        st.rerun()
    except Exception as error:
        st.error(f"LLM evaluation could not be completed: {error}")

summary = get_latest_search_run_summary(search_id)
queue_summary = get_search_evaluation_queue_summary(search_id)
evaluation_result = st.session_state.get(evaluation_key) if evaluation_key is not None else None

if summary["search_run_id"] is not None:
    eval_col1, eval_col2, eval_col3 = st.columns(3)
    eval_col1.metric("Evaluated", queue_summary["evaluated"])
    eval_col2.metric("Evaluation failures", queue_summary["evaluation_failed"])
    eval_col3.metric("Unevaluated jobs remaining", queue_summary["unevaluated_jobs"])

if evaluation_result:
    st.caption(f"Evaluation run {evaluation_result['evaluation_run_id']} · Status: {evaluation_result['run_status']}")
    elapsed_seconds = evaluation_result.get("elapsed_seconds")
    if elapsed_seconds is not None:
        elapsed_minutes, elapsed_seconds_remainder = divmod(int(elapsed_seconds), 60)
        processed = evaluation_result.get("total_processed", 0)
        average_per_job = elapsed_seconds / processed if processed else 0
        st.caption(
            f"Elapsed: {elapsed_minutes}m {elapsed_seconds_remainder:02d}s · "
            f"Average: {average_per_job:.1f}s per job · Jobs processed: {processed}"
        )
    with st.expander("Evaluation batch details"):
        st.json(evaluation_result["batch_results"])

    failed_jobs = [
        job_result
        for batch in evaluation_result["batch_results"]
        for job_result in batch["results"]
        if job_result["status"] == "evaluation_failed"
    ]
    if failed_jobs:
        st.subheader("Failed evaluations")
        st.dataframe(failed_jobs, hide_index=True, use_container_width=True)
