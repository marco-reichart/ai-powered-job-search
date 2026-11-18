"""Data access and aggregation for the dashboard page."""

from collections import defaultdict
from typing import Any

from src.job_search.database import get_db_connection
from src.job_search.statuses import (
    APPLICATION_STARTED_STATUSES,
    APPLICATION_STATUS_LABELS,
)

STATUS_ORDER = {
    "ai_filtered": -1,
    "new": 0,
    "interested": 1,
    "to_apply": 2,
    "applied": 3,
    "interview": 4,
    "offer": 5,
    "not_interested": 6,
    "rejected": 6,
    "withdrawn": 6,
    "hired": 6,
}

DASHBOARD_LABELS = [
    "Passed initial filters",
    "Kept by LLM",
    "Filtered by AI",
    "Needs review",
    "Interested",
    "To apply",
    "Applied",
    "Interview",
    "Offer received",
    "Not interested",
    "Rejected",
    "Withdrawn",
    "Hired",
    "Filtered by location",
    "Filtered by score",
    "Awaiting evaluation",
    "Evaluation failed",
    "Evaluation incomplete",
]


def get_dashboard_data(search_id: int, minimum_score: float) -> dict[str, Any]:
    """Aggregate dashboard metrics and Sankey edges.

    Args:
        search_id (int): Search ID.
        minimum_score (float): Minimum accepted match score.

    Returns:
        Dashboard metrics, flow edges, and recent runs.
    """
    with get_db_connection() as connection:
        processing_rows = connection.execute(
            """
            WITH latest_job_processing AS (
                SELECT
                    srj.job_id,
                    srj.processing_status,
                    ROW_NUMBER() OVER (
                        PARTITION BY srj.job_id
                        ORDER BY srj.id DESC
                    ) AS row_number
                FROM search_run_jobs srj
                JOIN search_runs sr ON sr.id = srj.search_run_id
                WHERE sr.search_id = ?
            )
            SELECT job_id, processing_status
            FROM latest_job_processing
            WHERE row_number = 1
        """,
            (search_id,),
        ).fetchall()

        total_evaluations = connection.execute(
            """
            SELECT COUNT(DISTINCT je.job_id)
            FROM job_evaluations je
            JOIN evaluation_runs er ON er.id = je.evaluation_run_id
            WHERE er.search_id = ?
        """,
            (search_id,),
        ).fetchone()[0]

        evaluation_rows = connection.execute(
            """
            WITH latest_evaluations AS (
                SELECT
                    je.job_id,
                    je.overall_score,
                    je.location_matches,
                    ROW_NUMBER() OVER (
                        PARTITION BY je.job_id
                        ORDER BY je.id DESC
                    ) AS row_number
                FROM job_evaluations je
                JOIN evaluation_runs er ON er.id = je.evaluation_run_id
                WHERE er.search_id = ?
            )
            SELECT job_id, overall_score, location_matches
            FROM latest_evaluations
            WHERE row_number = 1
        """,
            (search_id,),
        ).fetchall()

        application_rows = connection.execute(
            """
            WITH selected_jobs AS (
                SELECT DISTINCT srj.job_id
                FROM search_run_jobs srj
                JOIN search_runs sr ON sr.id = srj.search_run_id
                WHERE sr.search_id = ?
            )
            SELECT sj.job_id, jas.status AS status
            FROM selected_jobs sj
            LEFT JOIN job_application_statuses jas ON jas.job_id = sj.job_id
        """,
            (search_id,),
        ).fetchall()

        history_rows = connection.execute(
            """
            WITH selected_jobs AS (
                SELECT DISTINCT srj.job_id
                FROM search_run_jobs srj
                JOIN search_runs sr ON sr.id = srj.search_run_id
                WHERE sr.search_id = ?
            )
            SELECT h.id, h.job_id, h.old_status, h.new_status, h.changed_at
            FROM job_status_history h
            JOIN selected_jobs sj ON sj.job_id = h.job_id
            ORDER BY h.job_id, h.id
        """,
            (search_id,),
        ).fetchall()

        recent_runs = connection.execute(
            """
            SELECT started_at, status, jobs_found
            FROM search_runs
            WHERE search_id = ?
            ORDER BY id DESC
            LIMIT 10
        """,
            (search_id,),
        ).fetchall()

    processing_counts = defaultdict(int)
    processing_status_by_job = {}
    for row in processing_rows:
        processing_counts[row["processing_status"]] += 1
        processing_status_by_job[row["job_id"]] = row["processing_status"]

    initially_filtered = processing_counts["filtered_out"] + processing_counts["location_mismatch"]
    initially_passed_job_ids = {
        job_id
        for job_id, status in processing_status_by_job.items()
        if status
        in {
            "ready_for_evaluation",
            "evaluated",
            "evaluation_failed",
        }
    }

    evaluation_by_job = {row["job_id"]: row for row in evaluation_rows}
    kept_job_ids = set()
    filtered_location_job_ids = set()
    filtered_score_job_ids = set()
    incomplete_evaluation_job_ids = set()

    for job_id in initially_passed_job_ids:
        evaluation = evaluation_by_job.get(job_id)
        if evaluation is None:
            continue

        location_matches = evaluation["location_matches"]
        overall_score = evaluation["overall_score"]
        if location_matches is not None and int(location_matches) == 0:
            filtered_location_job_ids.add(job_id)
        elif overall_score is None:
            incomplete_evaluation_job_ids.add(job_id)
        elif float(overall_score) < minimum_score:
            filtered_score_job_ids.add(job_id)
        else:
            kept_job_ids.add(job_id)

    evaluation_failed_job_ids = {
        job_id
        for job_id in initially_passed_job_ids
        if processing_status_by_job.get(job_id) == "evaluation_failed" and job_id not in evaluation_by_job
    }
    awaiting_evaluation_job_ids = {
        job_id
        for job_id in initially_passed_job_ids
        if job_id not in evaluation_by_job and job_id not in evaluation_failed_job_ids
    }

    application_status_by_job = {row["job_id"]: row["status"] for row in application_rows}
    total_applications = sum(status in APPLICATION_STARTED_STATUSES for status in application_status_by_job.values())

    history_by_job = defaultdict(list)
    for row in history_rows:
        history_by_job[row["job_id"]].append(dict(row))

    first_status_by_job = {job_id: entries[0]["new_status"] for job_id, entries in history_by_job.items() if entries}
    for job_id, status in application_status_by_job.items():
        if status is not None:
            first_status_by_job.setdefault(job_id, status)

    flow_jobs = defaultdict(set)

    def add_flow(source: str, target: str, job_id: int) -> None:
        """Add a job to one Sankey edge.

        Args:
            source (str): Source node label.
            target (str): Destination node label.
            job_id (int): Job represented by the flow.
        """
        if source != target:
            flow_jobs[(source, target)].add(job_id)

    for job_id in kept_job_ids:
        add_flow("Passed initial filters", "Kept by LLM", job_id)
    ai_filtered_job_ids = filtered_location_job_ids | filtered_score_job_ids
    for job_id in ai_filtered_job_ids:
        add_flow("Passed initial filters", "Filtered by AI", job_id)
    for job_id in filtered_location_job_ids:
        add_flow("Filtered by AI", "Filtered by location", job_id)
    for job_id in filtered_score_job_ids:
        add_flow("Filtered by AI", "Filtered by score", job_id)
    for job_id in awaiting_evaluation_job_ids:
        add_flow("Passed initial filters", "Awaiting evaluation", job_id)
    for job_id in evaluation_failed_job_ids:
        add_flow("Passed initial filters", "Evaluation failed", job_id)
    for job_id in incomplete_evaluation_job_ids:
        add_flow("Passed initial filters", "Evaluation incomplete", job_id)

    for job_id in kept_job_ids:
        status = first_status_by_job.get(job_id, "new")
        if status in APPLICATION_STATUS_LABELS:
            add_flow("Kept by LLM", APPLICATION_STATUS_LABELS[status], job_id)

    for job_id, history in history_by_job.items():
        if job_id not in kept_job_ids:
            continue
        for entry in history[1:]:
            old_status = entry["old_status"]
            new_status = entry["new_status"]
            if old_status not in STATUS_ORDER or new_status not in STATUS_ORDER:
                continue
            if STATUS_ORDER[new_status] <= STATUS_ORDER[old_status]:
                continue
            add_flow(
                APPLICATION_STATUS_LABELS[old_status],
                APPLICATION_STATUS_LABELS[new_status],
                job_id,
            )

    return {
        "total_jobs": len(processing_rows),
        "initially_filtered": initially_filtered,
        "passed_initial_filters": len(initially_passed_job_ids),
        "total_evaluations": total_evaluations,
        "awaiting_evaluation": len(awaiting_evaluation_job_ids),
        "total_applications": total_applications,
        "labels": DASHBOARD_LABELS,
        "flow_edges": [
            {"source": source, "target": target, "value": len(job_ids)}
            for (source, target), job_ids in sorted(
                flow_jobs.items(),
                key=lambda item: (
                    DASHBOARD_LABELS.index(item[0][0]),
                    DASHBOARD_LABELS.index(item[0][1]),
                ),
            )
            if job_ids
        ],
        "recent_runs": [dict(row) for row in recent_runs],
    }
