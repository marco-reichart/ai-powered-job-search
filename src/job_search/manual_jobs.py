"""Manual job imports into a saved search."""

from typing import Any
from urllib.parse import urlsplit

from src.job_search.database import get_db_connection
from src.job_search.discovery import (
    complete_search_run,
    create_discovery_task,
    create_search_run,
    update_discovery_task,
)
from src.job_search.filtering import filter_search_run_jobs
from src.job_search.job_management import (
    get_or_create_job,
    record_search_run_job,
    save_job_listing,
)
from src.job_search.profiles import get_active_search_profile


def _normalize_manual_job(fields: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a manually entered listing.

    Args:
        fields (dict[str, Any]): Form values for the listing.

    Returns:
        Normalized job record.
    """
    required_fields = ("title", "company", "url", "description")
    job = {key: (fields.get(key) or "").strip() for key in required_fields}
    missing_fields = [key for key, value in job.items() if not value]
    if missing_fields:
        raise ValueError("Please provide the required fields: " + ", ".join(missing_fields))

    url = urlsplit(job["url"])
    if url.scheme not in {"http", "https"} or not url.netloc:
        raise ValueError("Source URL must be a valid http or https URL.")

    location = (fields.get("location") or "").strip() or None
    work_mode = (fields.get("work_mode") or "").strip().lower() or None
    employment_type = (fields.get("employment_type") or "").strip().lower() or None
    if work_mode not in {None, "remote", "hybrid", "onsite"}:
        raise ValueError("Work setup must be remote, hybrid, or onsite.")
    if employment_type not in {None, "full_time", "contract", "part_time"}:
        raise ValueError("Employment type is not supported.")

    return {
        "source": "manual",
        "external_id": job["url"],
        "url": job["url"],
        "title": job["title"],
        "company": job["company"],
        "location": location,
        "work_mode": work_mode,
        "enrichment": {"employment_type": employment_type},
        "description": job["description"],
    }


def add_manual_job(search_id: int, fields: dict[str, Any]) -> dict[str, Any]:
    """Save a listing and apply local profile filters.

    Args:
        search_id (int): Search ID.
        fields (dict[str, Any]): Form values for the listing.

    Returns:
        Discovery and filtering summary.
    """
    profile = get_active_search_profile(search_id)
    if profile is None:
        raise ValueError(f"No active search profile found for search {search_id}.")

    job = _normalize_manual_job(fields)
    search_run_id = create_search_run(search_id, profile["id"])
    task_id = None

    try:
        task_id = create_discovery_task(
            search_run_id=search_run_id,
            search_type="manual",
            query_value=job["url"],
            api_params=job,
            source="manual",
        )
        update_discovery_task(task_id, "running")
        job_id, is_new_job = get_or_create_job(job)
        listing_id, is_new_listing = save_job_listing(job_id, job)
        record_search_run_job(search_run_id, task_id, job_id, listing_id)
        update_discovery_task(task_id, "completed", jobs_found=1)
        discovery_summary = complete_search_run(search_run_id)

        filter_search_run_jobs(search_run_id, profile["filtering_config"])
        with get_db_connection() as connection:
            association = connection.execute(
                """
                SELECT processing_status, processing_reason
                FROM search_run_jobs
                WHERE search_run_id = ? AND job_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (search_run_id, job_id),
            ).fetchone()
            already_evaluated = connection.execute(
                "SELECT EXISTS(SELECT 1 FROM job_evaluations WHERE job_id = ?)",
                (job_id,),
            ).fetchone()[0]

        return {
            "search_run_id": search_run_id,
            "discovery": discovery_summary,
            "job_id": job_id,
            "is_new_job": is_new_job,
            "is_new_listing": is_new_listing,
            "processing_status": association["processing_status"],
            "processing_reason": association["processing_reason"],
            "already_evaluated": bool(already_evaluated),
            "ready_for_evaluation": (association["processing_status"] == "ready_for_evaluation"),
        }
    except Exception as error:
        if task_id is not None:
            update_discovery_task(task_id, "failed", error_message=str(error))
        with get_db_connection() as connection:
            connection.execute(
                """
                UPDATE search_runs
                SET status = 'failed',
                    error_message = ?,
                    completed_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'running'
                """,
                (str(error), search_run_id),
            )
        raise
