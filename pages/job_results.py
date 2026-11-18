
import json
from typing import Any

import streamlit as st

from src.job_search.job_management import (
    get_application_status_history,
    update_application_status,
)
from src.job_search.job_results import (
    classify_jobs,
    filter_by_work_mode,
    load_evaluated_jobs,
)
from src.job_search.profiles import get_active_search_profile
from src.job_search.sidebar import require_selected_search
from src.job_search.statuses import APPLICATION_STATUS_LABELS

st.set_page_config(layout="wide")

search_id = require_selected_search()

st.title("Job Results")
st.caption("Review AI-evaluated jobs and manage your applications")


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

active_profile = get_active_search_profile(search_id) or {}
evaluation_config = active_profile.get("evaluation_config", {})

minimum_score = evaluation_config.get("minimum_score", 50)

try:
    minimum_score = float(minimum_score)
except (TypeError, ValueError):
    minimum_score = 50.0


# --------------------------------------------------
# STATUS CONFIGURATION
# --------------------------------------------------

STATUS_LABELS = {
    **APPLICATION_STATUS_LABELS,
    "offer": "Offer",
}

STATUS_OPTIONS_BY_SECTION = {
    "review": [
        "new",
        "interested",
        "to_apply",
        "not_interested",
    ],

    "active": [
        "interested",
        "to_apply",
        "applied",
        "interview",
        "offer",
        "hired",
        "rejected",
        "withdrawn",
    ],

    "filtered": [
        "interested",
        "to_apply",
        "not_interested",
    ],

    "rejected": [
        "not_interested",
        "rejected",
        "withdrawn",
        "new",
        "interested",
        "to_apply",
    ],
}


def format_status(status: str) -> str:
    """Format an application status for display.

    Args:
        status (str): Internal status value.

    Returns:
        Human-readable status label.
    """
    return STATUS_LABELS.get(
        status,
        status.replace("_", " ").title()
    )


jobs = load_evaluated_jobs(search_id)


if not jobs:
    st.info("No evaluated jobs available for this job search yet.")
    st.stop()


classified = classify_jobs(jobs, minimum_score)
review_jobs = classified["review"]
active_jobs = classified["active"]
ai_filtered_jobs = classified["filtered"]
rejected_jobs = classified["rejected"]


# --------------------------------------------------
# FILTERS
# --------------------------------------------------

st.subheader("Filters")

work_modes = sorted({
    job["work_setup"]
    for job in jobs
    if job["work_setup"]
})


def format_work_mode(mode: str) -> str:
    """Format a work mode for display.

    Args:
        mode (str): Internal work mode.

    Returns:
        Human-readable work mode.
    """
    return {
        "hybrid": "Hybrid",
        "onsite": "On-site",
        "on_site": "On-site",
        "remote": "Remote",
    }.get(mode.lower(), mode.replace("_", " ").title())


default_modes = [
    mode
    for mode in work_modes
    if mode.lower().replace("_", "").replace("-", "").replace(" ", "")
    in {"hybrid", "onsite"}
]

selected_modes = st.multiselect(
    "Work setup",
    options=work_modes,
    default=default_modes,
    format_func=format_work_mode,
)


review_jobs = filter_by_work_mode(review_jobs, selected_modes)
active_jobs = filter_by_work_mode(active_jobs, selected_modes)
ai_filtered_jobs = filter_by_work_mode(ai_filtered_jobs, selected_modes)
rejected_jobs = filter_by_work_mode(rejected_jobs, selected_modes)


# --------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------

def display_json_list(value: str | None) -> list[Any]:
    """Decode a JSON list, returning an empty list on invalid input.

    Args:
        value (str | None): JSON text.

    Returns:
        Decoded list.
    """
    try:
        result = json.loads(value or "[]")
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def render_job_card(job: dict[str, Any], section_key: str) -> None:
    """Render a job card with details and status controls.

    Args:
        job (dict[str, Any]): Evaluated job record.
        section_key (str): Results section identifier.
    """

    job_id = job["job_id"]
    current_status = job["application_status"]

    with st.container(border=True):

        # --------------------------------------------------
        # HEADER
        # --------------------------------------------------

        title_col, score_col = st.columns([5, 1])

        with title_col:

            st.markdown(
                f"### {job['title'] or 'Untitled position'}"
            )

            if job["company"]:
                st.write(job["company"])

        with score_col:

            if job["overall_score"] is not None:
                st.metric(
                    "Match score",
                    f"{float(job['overall_score']):.0f}/100"
                )
            else:
                st.metric("Match score", "N/A")

        # --------------------------------------------------
        # JOB INFORMATION AND APPLICATION STATUS
        # --------------------------------------------------

        info_col1, info_col2, info_col3, status_col = st.columns(
            [1, 1, 2, 2]
        )

        with info_col1:

            work_setup = job["work_setup"]

            if work_setup:
                st.markdown("**Work setup**")
                st.markdown(
                    f":blue-badge[{format_work_mode(work_setup)}]"
                )

        with info_col2:

            if job["employment_type"]:

                employment_type = (
                    job["employment_type"]
                    .replace("_", " ")
                    .title()
                )

                st.markdown("**Employment type**")
                st.markdown(f":gray-badge[{employment_type}]")

        with info_col3:

            location = job["job_location"] or job["location"]

            st.markdown("**Location**")
            st.write(f"📍 {location or 'Not specified'}")

        with status_col:

            st.markdown("**Application status**")

            # Get the allowed statuses for this section.
            allowed_statuses = STATUS_OPTIONS_BY_SECTION[section_key]

            # Always include the current status as a fallback.
            # This prevents errors if an existing job has a status
            # that is not normally available in its current section.
            if current_status not in allowed_statuses:
                allowed_statuses = [current_status] + allowed_statuses

            selected_status = st.selectbox(
                "Application status",
                options=allowed_statuses,
                index=allowed_statuses.index(current_status),
                format_func=format_status,
                key=f"status_{section_key}_{job_id}",
                label_visibility="collapsed",
            )

            if selected_status != current_status:

                update_application_status(
                    job_id=job_id,
                    new_status=selected_status,
                    default_status=current_status,
                )

                st.rerun()

        # --------------------------------------------------
        # AI FILTER REASON
        # --------------------------------------------------

        if job.get("filter_reason"):

            st.warning(
                "AI filter reason: "
                + ", ".join(job["filter_reason"])
            )

            st.caption(
                "You can still pursue this job by changing its "
                "application status to Interested or To apply."
            )

        # --------------------------------------------------
        # JOB DETAILS
        # --------------------------------------------------

        with st.expander("View job details"):

            # Job description
            st.markdown("#### Job description")

            if job["job_description"]:
                st.write(job["job_description"])
            else:
                st.info("No job description available.")

            st.divider()

            # Match assessment
            st.markdown("#### Match assessment")

            score_col1, score_col2, score_col3 = st.columns(3)

            score_col1.metric(
                "Technical skills",
                job["technical_skills_score"]
            )

            score_col2.metric(
                "Experience",
                job["experience_score"]
            )

            score_col3.metric(
                "Role relevance",
                job["role_relevance_score"]
            )

            # Evaluation explanation
            st.markdown("#### Evaluation explanation")

            st.write(
                job["explanation"]
                or "No explanation available."
            )

            # Matching skills
            st.markdown("#### Matching skills")

            matching_skills = display_json_list(
                job["matching_skills_json"]
            )

            if matching_skills:
                st.write(", ".join(matching_skills))
            else:
                st.write("No matching skills recorded.")

            # Missing skills
            st.markdown("#### Missing skills")

            missing_skills = display_json_list(
                job["missing_skills_json"]
            )

            if missing_skills:
                st.write(", ".join(missing_skills))
            else:
                st.write("No missing skills recorded.")

            # Matching responsibilities
            st.markdown("#### Matching responsibilities")

            responsibilities = display_json_list(
                job["matching_responsibilities_json"]
            )

            if responsibilities:
                for responsibility in responsibilities:
                    st.markdown(f"- {responsibility}")
            else:
                st.write("No matching responsibilities recorded.")

            # Location assessment
            st.markdown("#### Location assessment")

            st.write(
                job["location_explanation"]
                or "No location explanation available."
            )

            # Original listing
            if job["application_url"]:
                st.link_button(
                    "Open original job listing",
                    job["application_url"]
                )

            # Application history
            st.divider()
            st.markdown("#### Application status history")

            history = get_application_status_history(job_id)

            if history:

                for entry in history:

                    old_status = entry["old_status"]
                    new_status = entry["new_status"]

                    if old_status:
                        transition = (
                            f"{format_status(old_status)} → "
                            f"{format_status(new_status)}"
                        )
                    else:
                        transition = format_status(new_status)

                    st.markdown(
                        f"**{transition}**  \n"
                        f"{entry['changed_at']}"
                    )

                    if entry.get("notes"):
                        st.caption(entry["notes"])

            else:
                st.caption("No status changes recorded yet.")


def render_job_section(
    title: str,
    description: str,
    job_list: list[dict[str, Any]],
    section_key: str,
) -> None:
    """Render a paginated results section.

    Args:
        title (str): Section heading.
        description (str): Section explanation.
        job_list (list[dict[str, Any]]): Jobs to display.
        section_key (str): Results section identifier.
    """

    st.subheader(f"{title} ({len(job_list)})")
    st.caption(description)

    if not job_list:
        st.info("No jobs in this section.")
        return

    job_list.sort(
        key=lambda job: (
            job["overall_score"] is not None,
            job["overall_score"] or 0
        ),
        reverse=True
    )

    page_size = 20
    page_count = (len(job_list) + page_size - 1) // page_size
    page_key = f"job_results_page_{section_key}"
    current_page = min(max(st.session_state.get(page_key, 0), 0), page_count - 1)

    if page_count > 1:
        previous_col, page_col, next_col = st.columns([1, 8, 1])
        with previous_col:
            if st.button(
                "← Previous",
                key=f"previous_{section_key}",
                disabled=current_page == 0,
            ):
                st.session_state[page_key] = current_page - 1
                st.rerun()
        with page_col:
            start = current_page * page_size + 1
            end = min((current_page + 1) * page_size, len(job_list))
            st.markdown(
                "<div style='text-align: center; padding-top: 0.45rem'>"
                f"Showing {start}–{end} of {len(job_list)} · Page {current_page + 1} of {page_count}"
                "</div>",
                unsafe_allow_html=True,
            )
        with next_col:
            with st.container(horizontal_alignment="right"):
                if st.button(
                    "Next →",
                    key=f"next_{section_key}",
                    disabled=current_page >= page_count - 1,
                ):
                    st.session_state[page_key] = current_page + 1
                    st.rerun()

    start_index = current_page * page_size
    for job in job_list[start_index : start_index + page_size]:
        render_job_card(job, section_key)


# --------------------------------------------------
# SECTION 1: NEEDS REVIEW
# --------------------------------------------------

render_job_section(
    title="1. Needs your review",
    description=(
        "Jobs that passed the AI filters and are waiting for your decision."
    ),
    job_list=review_jobs,
    section_key="review",
)

st.divider()


# --------------------------------------------------
# SECTION 2: INTERESTED AND APPLYING
# --------------------------------------------------

render_job_section(
    title="2. Interested & applying",
    description=(
        "Jobs you want to pursue, have applied to, or are interviewing for."
    ),
    job_list=active_jobs,
    section_key="active",
)

st.divider()


# --------------------------------------------------
# SECTION 3: FILTERED OUT BY AI
# --------------------------------------------------

render_job_section(
    title="3. Filtered out by AI",
    description=(
        "Jobs that did not meet the AI score threshold or had a location "
        "mismatch. You can still choose to pursue them."
    ),
    job_list=ai_filtered_jobs,
    section_key="filtered",
)

st.divider()


# --------------------------------------------------
# SECTION 4: REJECTED / NOT INTERESTED
# --------------------------------------------------

render_job_section(
    title="4. Rejected / not interested",
    description=(
        "Jobs you have decided not to pursue, or applications that were "
        "rejected or withdrawn."
    ),
    job_list=rejected_jobs,
    section_key="rejected",
)
