import json
import logging
from typing import Any, Callable

from src.job_search.database import get_db_connection
from src.job_search.discovery import (
    complete_search_run,
    create_search_run,
    execute_discovery_task,
    prepare_discovery_tasks,
)
from src.job_search.filtering import filter_search_run_jobs
from src.job_search.job_management import (
    create_evaluation_run,
    process_job_batch,
    update_evaluation_run,
)
from src.job_search.profiles import get_active_search_profile, get_search_profile

logger = logging.getLogger(__name__)


def run_evaluation_stage(
    search_run_id: int | None,
    evaluation_run_id: int,
    candidate_profile: dict[str, Any],
    evaluation_config: dict[str, Any],
    filtering_config: dict[str, Any],
    batch_limit: int | None = None,
    search_id: int | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    exclude_job_ids: set[int] | None = None,
) -> dict[str, Any]:
    """Evaluate one batch of unique jobs that passed local filtering.

    Args:
        search_run_id (int | None): Optional search run ID.
        evaluation_run_id (int): Evaluation run ID.
        candidate_profile (dict[str, Any]): Candidate details and skills.
        evaluation_config (dict[str, Any]): Model and scoring settings.
        filtering_config (dict[str, Any]): Location preferences.
        batch_limit (int | None): Maximum jobs to evaluate.
        search_id (int | None): Optional owning search ID.
        progress_callback (Callable[[dict[str, Any]], None] | None): Optional progress callback.
        exclude_job_ids (set[int] | None): Job IDs to skip in this call.

    Returns:
        Batch counts, remaining queue size, and job results.
    """

    if batch_limit is not None and batch_limit < 1:
        raise ValueError("batch_limit must be at least 1.")

    exclude_job_ids = tuple(exclude_job_ids or ())
    excluded_job_clause = ""
    if exclude_job_ids:
        placeholders = ",".join("?" for _ in exclude_job_ids)
        excluded_job_clause = f"AND srj.job_id NOT IN ({placeholders})"

    # Load eligible listing associations that do not have a saved evaluation.
    with get_db_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT
                srj.id AS search_run_job_id,
                srj.job_id,
                srj.listing_id,
                jl.raw_json
            FROM search_run_jobs AS srj
            JOIN job_listings AS jl
                ON jl.id = srj.listing_id
            JOIN search_runs AS sr
                ON sr.id = srj.search_run_id
            WHERE (? IS NULL OR srj.search_run_id = ?)
              AND (? IS NULL OR sr.search_id = ?)
              AND srj.processing_status IN (
                  'ready_for_evaluation', 'evaluation_failed'
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM job_evaluations AS je
                  WHERE je.job_id = srj.job_id
              )
              {excluded_job_clause}
            ORDER BY srj.id DESC
        """,
            (
                search_run_id,
                search_run_id,
                search_id,
                search_id,
                *exclude_job_ids,
            ),
        ).fetchall()

    # Deduplicate by canonical job ID.
    unique_jobs = {}

    for row in rows:
        job_id = row["job_id"]

        if job_id in unique_jobs:
            continue

        job = json.loads(row["raw_json"])

        unique_jobs[job_id] = {
            "job_id": job_id,
            "raw_json": row["raw_json"],
            "title": job.get("title", "Unknown title"),
        }

    jobs_to_evaluate = list(unique_jobs.values())

    if batch_limit is not None:
        jobs_to_evaluate = jobs_to_evaluate[:batch_limit]

    logger.info("Eligible associations: %s", len(rows))
    logger.info("Unique jobs in this batch: %s", len(jobs_to_evaluate))

    # Process the selected batch, if there is one.
    results = []

    try:
        if jobs_to_evaluate:
            results = process_job_batch(
                rows=jobs_to_evaluate,
                evaluation_run_id=evaluation_run_id,
                search_run_id=search_run_id,
                candidate_profile=candidate_profile,
                evaluation_config=evaluation_config,
                filtering_config=filtering_config,
                search_id=search_id,
                progress_callback=progress_callback,
            )

        evaluated = sum(result["status"] == "evaluated" for result in results)

        failed = sum(result["status"] == "evaluation_failed" for result in results)

        # Check what remains after this batch.
        with get_db_connection() as connection:
            remaining = connection.execute(
                """
                SELECT COUNT(DISTINCT srj.job_id)
                FROM search_run_jobs AS srj
                JOIN search_runs AS sr ON sr.id = srj.search_run_id
                WHERE (? IS NULL OR srj.search_run_id = ?)
                  AND (? IS NULL OR sr.search_id = ?)
                  AND srj.processing_status = 'ready_for_evaluation'
                  AND NOT EXISTS (
                      SELECT 1 FROM job_evaluations AS je
                      WHERE je.job_id = srj.job_id
                  )
            """,
                (search_run_id, search_run_id, search_id, search_id),
            ).fetchone()[0]

            total_failed = connection.execute(
                """
                SELECT COUNT(DISTINCT srj.job_id)
                FROM search_run_jobs AS srj
                JOIN search_runs AS sr ON sr.id = srj.search_run_id
                WHERE (? IS NULL OR srj.search_run_id = ?)
                  AND (? IS NULL OR sr.search_id = ?)
                  AND srj.processing_status = 'evaluation_failed'
                  AND NOT EXISTS (
                      SELECT 1 FROM job_evaluations AS je
                      WHERE je.job_id = srj.job_id
                  )
            """,
                (search_run_id, search_run_id, search_id, search_id),
            ).fetchone()[0]

        # Finalize only when no eligible jobs remain.
        if remaining > 0:
            run_status = "running"
            update_evaluation_run(evaluation_run_id, "running")

        elif total_failed > 0:
            run_status = "completed_with_errors"
            update_evaluation_run(
                evaluation_run_id,
                "completed_with_errors",
                error_message=(f"{total_failed} job evaluations failed."),
            )

        else:
            run_status = "completed"
            update_evaluation_run(evaluation_run_id, "completed")

        logger.info("Evaluated in this batch: %s", evaluated)
        logger.info("Failed in this batch: %s", failed)
        logger.info("Unique jobs remaining: %s", remaining)
        logger.info("Evaluation run status: %s", run_status)

        return {
            "total": len(jobs_to_evaluate),
            "evaluated": evaluated,
            "failed": failed,
            "remaining": remaining,
            "run_status": run_status,
            "results": results,
        }

    except Exception as error:
        update_evaluation_run(
            evaluation_run_id,
            "failed",
            error_message=str(error),
        )
        raise


def run_evaluation_batches(
    search_run_id: int | None,
    evaluation_run_id: int,
    candidate_profile: dict[str, Any],
    evaluation_config: dict[str, Any],
    filtering_config: dict[str, Any],
    batch_size: int = 10,
    max_batches: int = 1,
    search_id: int | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Process bounded evaluation batches in one run.

    Args:
        search_run_id (int | None): Optional search run ID.
        evaluation_run_id (int): Evaluation run ID.
        candidate_profile (dict[str, Any]): Candidate details and skills.
        evaluation_config (dict[str, Any]): Model and scoring settings.
        filtering_config (dict[str, Any]): Location preferences.
        batch_size (int): Jobs per batch.
        max_batches (int): Maximum batches to process.
        search_id (int | None): Optional owning search ID.
        progress_callback (Callable[[dict[str, Any]], None] | None): Optional progress callback.

    Returns:
        Combined counts, remaining queue size, and batch results.
    """

    if batch_size < 1:
        raise ValueError("batch_size must be at least 1.")

    if max_batches < 1:
        raise ValueError("max_batches must be at least 1.")

    total_evaluated = 0
    total_failed = 0
    total_processed = 0
    batch_results = []
    attempted_job_ids = set()

    for batch_number in range(1, max_batches + 1):
        logger.info("--- Evaluation batch %s/%s ---", batch_number, max_batches)

        result = run_evaluation_stage(
            search_run_id=search_run_id,
            evaluation_run_id=evaluation_run_id,
            candidate_profile=candidate_profile,
            evaluation_config=evaluation_config,
            filtering_config=filtering_config,
            batch_limit=batch_size,
            search_id=search_id,
            exclude_job_ids=set(attempted_job_ids),
            progress_callback=progress_callback,
        )

        total_processed += result["total"]
        total_evaluated += result["evaluated"]
        total_failed += result["failed"]

        batch_results.append(result)
        attempted_job_ids.update(item["job_id"] for item in result["results"])

        if result["remaining"] == 0:
            break

        if result["total"] == 0:
            break

    final_result = {
        "batches_processed": len(batch_results),
        "total_processed": total_processed,
        "evaluated": total_evaluated,
        "failed": total_failed,
        "remaining": (batch_results[-1]["remaining"] if batch_results else None),
        "run_status": (batch_results[-1]["run_status"] if batch_results else None),
        "batch_results": batch_results,
    }

    logger.info("--- Overall evaluation summary ---")
    logger.info("Batches processed: %s", final_result["batches_processed"])
    logger.info("Total processed: %s", total_processed)
    logger.info("Successfully evaluated: %s", total_evaluated)
    logger.info("Failed: %s", total_failed)
    logger.info("Remaining: %s", final_result["remaining"])
    logger.info("Run status: %s", final_result["run_status"])

    return final_result


def run_job_search_pipeline(search_id: int, batch_size: int = 10, max_batches: int = 1) -> dict[str, Any]:
    """Run discovery, filtering, and bounded evaluation.

    Args:
        search_id (int): Search ID.
        batch_size (int): Jobs per evaluation batch.
        max_batches (int): Maximum batches to process.

    Returns:
        Search, filtering, and evaluation summaries.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1.")

    if max_batches < 1:
        raise ValueError("max_batches must be at least 1.")

    profile = get_active_search_profile(search_id)

    if profile is None:
        raise ValueError(f"No active search profile found for search {search_id}.")

    search_run_id = create_search_run(search_id, profile["id"])

    try:
        discovery_tasks = prepare_discovery_tasks(
            search_run_id,
            profile["discovery_config"],
        )
        discovery_results = []

        for task in discovery_tasks:
            try:
                result = execute_discovery_task(
                    search_run_id,
                    task["task_id"],
                )
            except Exception as error:
                raise RuntimeError(
                    f"Discovery task {task['task_id']} failed; filtering and evaluation were not started."
                ) from error

            discovery_results.append(result)

        discovery_summary = complete_search_run(search_run_id)
    except Exception as error:
        with get_db_connection() as connection:
            connection.execute(
                """
                UPDATE search_runs
                SET status = 'failed',
                    error_message = ?,
                    completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND status = 'running'
            """,
                (str(error), search_run_id),
            )
        raise

    passed_jobs = filter_search_run_jobs(
        search_run_id,
        profile["filtering_config"],
    )

    with get_db_connection() as connection:
        filtering_counts = connection.execute(
            """
            SELECT processing_status, COUNT(*) AS count
            FROM search_run_jobs
            WHERE search_run_id = ?
            GROUP BY processing_status
        """,
            (search_run_id,),
        ).fetchall()

    filtering_summary = {
        "passed": len(passed_jobs),
        "statuses": {row["processing_status"]: row["count"] for row in filtering_counts},
    }

    evaluation_run_id = create_evaluation_run(
        search_id,
        search_run_id,
        profile["evaluation_config"],
    )
    evaluation_summary = run_evaluation_batches(
        search_run_id=search_run_id,
        evaluation_run_id=evaluation_run_id,
        candidate_profile=profile["candidate_profile"],
        evaluation_config=profile["evaluation_config"],
        filtering_config=profile["filtering_config"],
        batch_size=batch_size,
        max_batches=max_batches,
    )

    return {
        "search_run_id": search_run_id,
        "evaluation_run_id": evaluation_run_id,
        "discovery": {
            **discovery_summary,
            "tasks": discovery_results,
        },
        "filtering": filtering_summary,
        "evaluation": evaluation_summary,
        "run_status": evaluation_summary["run_status"],
        "evaluated": evaluation_summary["evaluated"],
        "failed": evaluation_summary["failed"],
        "remaining": evaluation_summary["remaining"],
    }


def run_job_discovery(search_id: int) -> dict[str, Any]:
    """Run discovery and local filtering without LLM evaluation.

    Args:
        search_id (int): Search ID.

    Returns:
        Discovery and filtering summaries.
    """
    profile = get_active_search_profile(search_id)

    if profile is None:
        raise ValueError(f"No active search profile found for search {search_id}.")

    search_run_id = create_search_run(search_id, profile["id"])

    try:
        discovery_tasks = prepare_discovery_tasks(
            search_run_id,
            profile["discovery_config"],
        )
        discovery_results = []

        for task in discovery_tasks:
            try:
                result = execute_discovery_task(search_run_id, task["task_id"])
            except Exception as error:
                raise RuntimeError(f"Discovery task {task['task_id']} failed; filtering was not started.") from error
            discovery_results.append(result)

        discovery_summary = complete_search_run(search_run_id)
    except Exception as error:
        with get_db_connection() as connection:
            connection.execute(
                """
                UPDATE search_runs
                SET status = 'failed',
                    error_message = ?,
                    completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND status = 'running'
            """,
                (str(error), search_run_id),
            )
        raise

    passed_jobs = filter_search_run_jobs(
        search_run_id,
        profile["filtering_config"],
    )

    with get_db_connection() as connection:
        filtering_counts = connection.execute(
            """
            SELECT processing_status, COUNT(*) AS count
            FROM search_run_jobs
            WHERE search_run_id = ?
            GROUP BY processing_status
        """,
            (search_run_id,),
        ).fetchall()

    return {
        "search_run_id": search_run_id,
        "discovery": {
            **discovery_summary,
            "tasks": discovery_results,
        },
        "filtering": {
            "passed": len(passed_jobs),
            "statuses": {row["processing_status"]: row["count"] for row in filtering_counts},
        },
    }


def get_latest_search_run_summary(search_id: int) -> dict[str, Any]:
    """Return the latest run metadata and job counts.

    Args:
        search_id (int): Search ID.

    Returns:
        Latest run status and processing counts.
    """
    with get_db_connection() as connection:
        search_run = connection.execute(
            """
            SELECT id, status, started_at, completed_at
            FROM search_runs
            WHERE search_id = ?
            ORDER BY id DESC
            LIMIT 1
        """,
            (search_id,),
        ).fetchone()

        if search_run is None:
            return {
                "search_run_id": None,
                "status": None,
                "started_at": None,
                "completed_at": None,
                "ready_for_evaluation": 0,
                "evaluated": 0,
                "evaluation_failed": 0,
            }

        counts = connection.execute(
            """
            SELECT
                processing_status,
                COUNT(DISTINCT job_id) AS count
            FROM search_run_jobs
            WHERE search_run_id = ?
            GROUP BY processing_status
        """,
            (search_run["id"],),
        ).fetchall()

    status_counts = {row["processing_status"]: row["count"] for row in counts}

    return {
        "search_run_id": search_run["id"],
        "status": search_run["status"],
        "started_at": search_run["started_at"],
        "completed_at": search_run["completed_at"],
        "ready_for_evaluation": status_counts.get("ready_for_evaluation", 0),
        "evaluated": status_counts.get("evaluated", 0),
        "evaluation_failed": status_counts.get("evaluation_failed", 0),
    }


def get_search_evaluation_queue_summary(search_id: int) -> dict[str, int]:
    """Count unevaluated jobs and prior evaluation outcomes.

    Args:
        search_id (int): Search ID.

    Returns:
        Queue, evaluated, and failed job counts.
    """
    with get_db_connection() as connection:
        unevaluated_jobs = connection.execute(
            """
            SELECT COUNT(DISTINCT srj.job_id)
            FROM search_run_jobs AS srj
            JOIN search_runs AS sr ON sr.id = srj.search_run_id
            WHERE sr.search_id = ?
              AND srj.processing_status IN (
                  'ready_for_evaluation', 'evaluation_failed'
              )
              AND NOT EXISTS (
                  SELECT 1 FROM job_evaluations AS je
                  WHERE je.job_id = srj.job_id
              )
        """,
            (search_id,),
        ).fetchone()[0]

        already_evaluated = connection.execute(
            """
            SELECT COUNT(DISTINCT srj.job_id)
            FROM search_run_jobs AS srj
            JOIN search_runs AS sr ON sr.id = srj.search_run_id
            WHERE sr.search_id = ?
              AND EXISTS (
                  SELECT 1 FROM job_evaluations AS je
                  WHERE je.job_id = srj.job_id
              )
        """,
            (search_id,),
        ).fetchone()[0]

        unevaluated_failures = connection.execute(
            """
            SELECT COUNT(DISTINCT srj.job_id)
            FROM search_run_jobs AS srj
            JOIN search_runs AS sr ON sr.id = srj.search_run_id
            WHERE sr.search_id = ?
              AND srj.processing_status = 'evaluation_failed'
              AND NOT EXISTS (
                  SELECT 1 FROM job_evaluations AS je
                  WHERE je.job_id = srj.job_id
              )
        """,
            (search_id,),
        ).fetchone()[0]

    return {
        "unevaluated_jobs": unevaluated_jobs,
        "evaluated": already_evaluated,
        "evaluation_failed": unevaluated_failures,
    }


def run_job_evaluation(
    search_id: int,
    batch_size: int = 10,
    max_batches: int = 1,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Evaluate unique unevaluated jobs across a search's runs.

    Args:
        search_id (int): Search ID.
        batch_size (int): Jobs per batch.
        max_batches (int): Maximum batches to process.
        progress_callback (Callable[[dict[str, Any]], None] | None): Optional progress callback.

    Returns:
        Evaluation run ID and batch summary.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1.")

    if max_batches < 1:
        raise ValueError("max_batches must be at least 1.")

    queue = get_search_evaluation_queue_summary(search_id)
    if queue["unevaluated_jobs"] == 0:
        raise ValueError("There are no unevaluated jobs ready for evaluation.")

    profile = get_active_search_profile(search_id)
    if profile is None:
        raise ValueError(f"No active search profile found for search {search_id}.")

    with get_db_connection() as connection:
        search_run = connection.execute(
            """
            SELECT id
            FROM search_runs
            WHERE search_id = ?
              AND status = 'completed'
            ORDER BY id DESC
            LIMIT 1
        """,
            (search_id,),
        ).fetchone()
        evaluation_run = connection.execute(
            """
            SELECT id
            FROM evaluation_runs
            WHERE search_id = ?
              AND status = 'running'
            ORDER BY id DESC
            LIMIT 1
        """,
            (search_id,),
        ).fetchone()

    if search_run is None:
        raise ValueError("A completed discovery run is required before evaluation.")

    evaluation_run_id = (
        evaluation_run["id"]
        if evaluation_run is not None
        else create_evaluation_run(
            search_id,
            search_run["id"],
            profile["evaluation_config"],
        )
    )

    evaluation_summary = run_evaluation_batches(
        search_run_id=None,
        evaluation_run_id=evaluation_run_id,
        candidate_profile=profile["candidate_profile"],
        evaluation_config=profile["evaluation_config"],
        filtering_config=profile["filtering_config"],
        batch_size=batch_size,
        max_batches=max_batches,
        search_id=search_id,
        progress_callback=progress_callback,
    )

    return {
        "search_run_id": search_run["id"],
        "evaluation_run_id": evaluation_run_id,
        **evaluation_summary,
    }
