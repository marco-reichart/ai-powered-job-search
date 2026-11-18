"""Data access and classification for the Job Results page."""

from typing import Any

from src.job_search.database import get_db_connection
from src.job_search.job_management import get_application_statuses

ACTIVE_STATUSES = frozenset(
    {
        "interested",
        "to_apply",
        "applied",
        "interview",
        "offer",
        "hired",
    }
)
REJECTED_STATUSES = frozenset({"not_interested", "rejected", "withdrawn"})


def load_evaluated_jobs(search_id: int) -> list[dict[str, Any]]:
    """Load each job's latest evaluation and application status.

    Args:
        search_id (int): Search ID.

    Returns:
        Evaluated job records.
    """
    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                j.id AS job_id, j.title, j.company, j.location,
                je.overall_score, je.technical_skills_score,
                je.experience_score, je.role_relevance_score, je.work_setup,
                je.job_location, je.location_matches, je.matching_skills_json,
                je.missing_skills_json, je.matching_responsibilities_json,
                je.explanation, je.location_explanation,
                (SELECT l.url FROM job_listings l WHERE l.job_id = j.id
                 ORDER BY l.last_seen_at DESC, l.id DESC LIMIT 1) AS application_url,
                (SELECT l.description FROM job_listings l WHERE l.job_id = j.id
                 ORDER BY l.last_seen_at DESC, l.id DESC LIMIT 1) AS job_description,
                (SELECT l.employment_type FROM job_listings l WHERE l.job_id = j.id
                 ORDER BY l.last_seen_at DESC, l.id DESC LIMIT 1) AS employment_type
            FROM jobs j
            JOIN job_evaluations je ON je.id = (
                SELECT je2.id
                FROM job_evaluations je2
                JOIN evaluation_runs er2 ON er2.id = je2.evaluation_run_id
                WHERE je2.job_id = j.id AND er2.search_id = ?
                ORDER BY je2.created_at DESC, je2.id DESC LIMIT 1
            )
            WHERE EXISTS (
                SELECT 1 FROM search_run_jobs srj
                JOIN search_runs sr ON sr.id = srj.search_run_id
                WHERE srj.job_id = j.id AND sr.search_id = ?
            )
            ORDER BY je.overall_score DESC
        """,
            (search_id, search_id),
        ).fetchall()

    jobs = [dict(row) for row in rows]
    statuses = get_application_statuses(
        [job["job_id"] for job in jobs],
        default_status=None,
    )
    for job in jobs:
        saved_status = statuses.get(job["job_id"])
        job["application_status"] = saved_status or "new"
    return jobs


def classify_jobs(jobs: list[dict[str, Any]], minimum_score: float) -> dict[str, list[dict[str, Any]]]:
    """Group jobs by application status and AI filter results.

    Args:
        jobs (list[dict[str, Any]]): Evaluated job records.
        minimum_score (float): Minimum accepted match score.

    Returns:
        Jobs grouped into review, active, filtered, and rejected sections.
    """
    result: dict[str, list[dict[str, Any]]] = {
        "review": [], "active": [], "filtered": [], "rejected": []
    }
    for job in jobs:
        status = job["application_status"]
        location_matches = job["location_matches"]
        location_mismatch = location_matches is not None and int(location_matches) == 0
        score = job["overall_score"]
        score_mismatch = score is not None and float(score) < minimum_score

        if status == "new" and (location_mismatch or score_mismatch):
            status = "ai_filtered"
            job["application_status"] = status

        if status in ACTIVE_STATUSES:
            result["active"].append(job)
            continue
        if status in REJECTED_STATUSES:
            result["rejected"].append(job)
            continue

        if location_mismatch or score_mismatch:
            job["filter_reason"] = []
            if location_mismatch:
                job["filter_reason"].append("Location mismatch")
            if score_mismatch:
                job["filter_reason"].append(f"Score below {minimum_score:.0f}")
            result["filtered"].append(job)
        else:
            result["review"].append(job)
    return result


def filter_by_work_mode(jobs: list[dict[str, Any]], selected_modes: list[str]) -> list[dict[str, Any]]:
    """Keep jobs matching the selected work modes.

    Args:
        jobs (list[dict[str, Any]]): Job records.
        selected_modes (list[str]): Work modes to keep; empty means all modes.

    Returns:
        Filtered job records.
    """
    if not selected_modes:
        return jobs
    selected = set(selected_modes)
    return [job for job in jobs if job["work_setup"] in selected]
