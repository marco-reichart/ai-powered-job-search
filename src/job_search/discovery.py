import json
import logging
import time
from typing import Any

import requests

from src.job_search.database import get_db_connection
from src.job_search.job_management import get_or_create_job, record_search_run_job, save_job_listing

API_URL = "https://freehire.me/api/v1/agent/jobs/search"
logger = logging.getLogger(__name__)


def create_search_run(search_id: int, profile_id: int) -> int:
    """Create a running discovery record.

    Args:
        search_id (int): Owning search ID.
        profile_id (int): Profile used for discovery.

    Returns:
        New search run ID.
    """
    with get_db_connection() as connection:
        # Verify that the profile belongs to this search
        profile = connection.execute(
            """
            SELECT id
            FROM search_profiles
            WHERE id = ?
              AND search_id = ?
        """,
            (profile_id, search_id),
        ).fetchone()

        if profile is None:
            raise ValueError("The selected profile does not belong to this search.")

        cursor = connection.execute(
            """
            INSERT INTO search_runs (
                search_id,
                profile_id,
                status
            )
            VALUES (?, ?, 'running')
        """,
            (search_id, profile_id),
        )

        run_id = cursor.lastrowid

    return run_id


def create_discovery_task(
    search_run_id: int,
    search_type: str,
    query_value: str,
    api_params: dict[str, Any],
    source: str = "freehire",
) -> int:
    """Create a pending discovery task.

    Args:
        search_run_id (int): Search run ID.
        search_type (str): Category, title, or manual task.
        query_value (str): Search term or manual listing URL.
        api_params (dict[str, Any]): Request parameters.
        source (str): Listing source.

    Returns:
        New task ID.
    """
    if search_type not in {"category", "title", "manual"}:
        raise ValueError("Invalid discovery task type.")

    with get_db_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO discovery_tasks (
                search_run_id,
                source,
                search_type,
                query_value,
                api_params_json,
                status
            )
            VALUES (?, ?, ?, ?, ?, 'pending')
        """,
            (
                search_run_id,
                source,
                search_type,
                query_value,
                json.dumps(api_params, ensure_ascii=False),
            ),
        )

        task_id = cursor.lastrowid

    return task_id


def prepare_discovery_tasks(search_run_id: int, discovery_config: dict[str, Any]) -> list[dict[str, Any]]:
    """Create tasks enabled by the discovery profile.

    Args:
        search_run_id (int): Search run ID.
        discovery_config (dict[str, Any]): Discovery settings.

    Returns:
        Prepared task records.
    """
    common_params = discovery_config["common_params"]
    tasks = []

    # Category searches
    category_config = discovery_config["category_search"]

    if category_config["enabled"]:
        for category in category_config["categories"]:
            api_params = {**common_params, "category": category}

            task_id = create_discovery_task(
                search_run_id=search_run_id, search_type="category", query_value=category, api_params=api_params
            )

            tasks.append(
                {"task_id": task_id, "search_type": "category", "query_value": category, "api_params": api_params}
            )

    # Title searches
    title_config = discovery_config["title_search"]

    if title_config["enabled"]:
        for title in title_config["queries"]:
            api_params = {**common_params, "q": f'title:"{title}"', "q_fields": "title"}

            task_id = create_discovery_task(
                search_run_id=search_run_id, search_type="title", query_value=title, api_params=api_params
            )

            tasks.append({"task_id": task_id, "search_type": "title", "query_value": title, "api_params": api_params})

    return tasks


def fetch_freehire_jobs(params: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Fetch all Freehire pages matching request parameters.

    Args:
        params (dict[str, Any]): Freehire search parameters.

    Returns:
        Listings and retrieval metadata.
    """
    all_jobs = []

    limit = int(params.get("limit", 100))
    offset = 0
    total_jobs = None

    while True:
        page_params = {**params, "limit": limit, "offset": offset}

        response = requests.get(API_URL, params=page_params, timeout=30)
        response.raise_for_status()

        result = response.json()

        meta = result.get("meta", {})
        ignored_params = meta.get("ignored_params", [])

        if ignored_params:
            raise ValueError(f"Freehire ignored these parameters: {ignored_params}")

        if total_jobs is None:
            total_jobs = meta["total"]

        page_jobs = result.get("data", [])

        if not page_jobs:
            break

        all_jobs.extend(page_jobs)

        logger.info("Retrieved %s / %s jobs", len(all_jobs), total_jobs)

        offset += len(page_jobs)

        if offset >= total_jobs:
            break

        time.sleep(0.2)

    return all_jobs, {"total_available": total_jobs, "total_retrieved": len(all_jobs)}


def update_discovery_task(
    task_id: int,
    status: str,
    jobs_found: int | None = None,
    error_message: str | None = None,
) -> None:
    """Update a task's status and completion details.

    Args:
        task_id (int): Discovery task ID.
        status (str): New task status.
        jobs_found (int | None): Optional number of listings found.
        error_message (str | None): Optional failure explanation.
    """
    allowed_statuses = {"pending", "running", "completed", "failed", "cancelled"}

    if status not in allowed_statuses:
        raise ValueError(f"Invalid task status: {status}")

    with get_db_connection() as connection:
        connection.execute(
            """
            UPDATE discovery_tasks
            SET status = ?,
                jobs_found = COALESCE(?, jobs_found),
                error_message = ?,
                started_at = CASE
                    WHEN ? = 'running'
                    THEN CURRENT_TIMESTAMP
                    ELSE started_at
                END,
                completed_at = CASE
                    WHEN ? IN ('completed', 'failed', 'cancelled')
                    THEN CURRENT_TIMESTAMP
                    ELSE completed_at
                END
            WHERE id = ?
        """,
            (status, jobs_found, error_message, status, status, task_id),
        )


def execute_discovery_task(search_run_id: int, task_id: int) -> dict[str, Any]:
    """Fetch and save listings for one discovery task.

    Args:
        search_run_id (int): Search run ID.
        task_id (int): Discovery task ID.

    Returns:
        Task summary and saved listing counts.
    """
    # Load task configuration
    with get_db_connection() as connection:
        task = connection.execute(
            """
            SELECT *
            FROM discovery_tasks
            WHERE id = ?
              AND search_run_id = ?
        """,
            (task_id, search_run_id),
        ).fetchone()

    if task is None:
        raise ValueError("Discovery task not found.")

    if task["status"] != "pending":
        raise ValueError(f"Task {task_id} is not pending: {task['status']}")

    api_params = json.loads(task["api_params_json"])

    update_discovery_task(task_id, "running")

    try:
        # Retrieve all matching jobs
        jobs, metadata = fetch_freehire_jobs(api_params)

        saved_count = 0
        new_job_count = 0
        new_listing_count = 0

        for job in jobs:
            job_id, is_new_job = get_or_create_job(job)

            listing_id, is_new_listing = save_job_listing(job_id, job)

            record_search_run_job(search_run_id, task_id, job_id, listing_id)

            saved_count += 1
            new_job_count += int(is_new_job)
            new_listing_count += int(is_new_listing)

        update_discovery_task(task_id, "completed", jobs_found=len(jobs))

        return {
            "task_id": task_id,
            "status": "completed",
            "total_retrieved": metadata["total_retrieved"],
            "total_available": metadata["total_available"],
            "saved_associations": saved_count,
            "new_canonical_jobs": new_job_count,
            "new_source_listings": new_listing_count,
        }

    except Exception as error:
        update_discovery_task(task_id, "failed", error_message=str(error))
        raise


def complete_search_run(search_run_id: int) -> dict[str, Any]:
    """Complete a search run after all tasks succeed.

    Args:
        search_run_id (int): Search run ID.

    Returns:
        Search run completion summary.
    """
    with get_db_connection() as connection:
        task_status = connection.execute(
            """
            SELECT
                COUNT(*) AS total_tasks,
                SUM(CASE WHEN status = 'completed'
                    THEN 1 ELSE 0 END) AS completed_tasks,
                SUM(CASE WHEN status = 'failed'
                    THEN 1 ELSE 0 END) AS failed_tasks
            FROM discovery_tasks
            WHERE search_run_id = ?
        """,
            (search_run_id,),
        ).fetchone()

        if task_status["completed_tasks"] != task_status["total_tasks"]:
            raise ValueError("Not all discovery tasks completed successfully.")

        unique_jobs = connection.execute(
            """
            SELECT COUNT(DISTINCT job_id)
            FROM search_run_jobs
            WHERE search_run_id = ?
        """,
            (search_run_id,),
        ).fetchone()[0]

        connection.execute(
            """
            UPDATE search_runs
            SET status = 'completed',
                completed_at = CURRENT_TIMESTAMP,
                jobs_found = ?
            WHERE id = ?
        """,
            (unique_jobs, search_run_id),
        )

    return {
        "search_run_id": search_run_id,
        "status": "completed",
        "total_tasks": task_status["total_tasks"],
        "unique_jobs": unique_jobs,
    }
