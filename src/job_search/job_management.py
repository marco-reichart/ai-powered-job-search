import json
import logging
import re
import unicodedata
from typing import Any, Callable

from src.job_search.database import get_db_connection
from src.job_search.evaluation import classify_evaluation_result, evaluate_job, validate_evaluation
from src.job_search.scoring import calculate_match_score
from src.job_search.statuses import APPLICATION_STATUSES

logger = logging.getLogger(__name__)


def normalize_text(value: Any) -> str:
    """Normalize text for canonical job matching.

    Args:
        value (Any): Text to normalize.

    Returns:
        Normalized text, or an empty string for non-text values.
    """
    if not isinstance(value, str):
        return ""

    value = value.strip().casefold()

    value = value.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")

    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))

    value = re.sub(r"[^a-z0-9]+", " ", value)

    return " ".join(value.split())


def get_or_create_job(job: dict[str, Any]) -> tuple[int, bool]:
    """Find or create a canonical job record.

    Args:
        job (dict[str, Any]): Listing data.

    Returns:
        Job ID and whether a new record was created.
    """
    title = job.get("title") or "Unknown title"
    company = job.get("company") or "Unknown company"
    location = job.get("location")

    location_text = ", ".join(location) if isinstance(location, list) else location or ""

    normalized_title = normalize_text(title)
    normalized_company = normalize_text(company)
    normalized_location = normalize_text(location_text)

    with get_db_connection() as connection:
        existing = connection.execute(
            """
            SELECT id
            FROM jobs
            WHERE normalized_title = ?
              AND normalized_company = ?
              AND normalized_location = ?
            LIMIT 1
        """,
            (normalized_title, normalized_company, normalized_location),
        ).fetchone()

        if existing:
            job_id = existing["id"]

            connection.execute(
                """
                UPDATE jobs
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """,
                (job_id,),
            )

            return job_id, False

        cursor = connection.execute(
            """
            INSERT INTO jobs (
                title,
                company,
                location,
                normalized_title,
                normalized_company,
                normalized_location
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (title, company, location_text, normalized_title, normalized_company, normalized_location),
        )

        return cursor.lastrowid, True


def save_job_listing(job_id: int, job: dict[str, Any]) -> tuple[int, bool]:
    """Insert or update a source listing.

    Args:
        job_id (int): Canonical job ID.
        job (dict[str, Any]): Listing data.

    Returns:
        Listing ID and whether a new listing was created.
    """
    source = job.get("source") or "freehire"
    external_id = job.get("external_id")
    url = job.get("url")

    location = job.get("location")

    if isinstance(location, list):
        location = ", ".join(location)
    elif location is not None:
        location = str(location)

    enrichment = job.get("enrichment") or {}
    employment_type = enrichment.get("employment_type")

    raw_json = json.dumps(job, ensure_ascii=False)

    with get_db_connection() as connection:
        # Look for an existing listing by source and external ID
        existing = None

        if external_id is not None:
            existing = connection.execute(
                """
                SELECT id
                FROM job_listings
                WHERE source = ?
                  AND external_id = ?
            """,
                (source, str(external_id)),
            ).fetchone()

        if existing:
            listing_id = existing["id"]

            connection.execute(
                """
                UPDATE job_listings
                SET job_id = ?,
                    url = ?,
                    title = ?,
                    company = ?,
                    location = ?,
                    work_mode = ?,
                    employment_type = ?,
                    description = ?,
                    raw_json = ?,
                    last_seen_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """,
                (
                    job_id,
                    url,
                    job.get("title"),
                    job.get("company"),
                    location,
                    job.get("work_mode"),
                    employment_type,
                    job.get("description"),
                    raw_json,
                    listing_id,
                ),
            )

            return listing_id, False

        cursor = connection.execute(
            """
            INSERT INTO job_listings (
                job_id,
                source,
                external_id,
                url,
                title,
                company,
                location,
                work_mode,
                employment_type,
                description,
                raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                job_id,
                source,
                str(external_id) if external_id is not None else None,
                url,
                job.get("title"),
                job.get("company"),
                location,
                job.get("work_mode"),
                employment_type,
                job.get("description"),
                raw_json,
            ),
        )

        return cursor.lastrowid, True


def record_search_run_job(
    search_run_id: int,
    discovery_task_id: int | None,
    job_id: int,
    listing_id: int,
    processing_status: str = "found",
    processing_reason: str | None = None,
) -> tuple[int, bool]:
    """Associate a listing with a search run.

    Args:
        search_run_id (int): Search run ID.
        discovery_task_id (int | None): Discovery task ID.
        job_id (int): Canonical job ID.
        listing_id (int): Source listing ID.
        processing_status (str): Initial processing status.
        processing_reason (str | None): Optional processing explanation.

    Returns:
        Association ID and whether a new association was created.
    """
    with get_db_connection() as connection:
        # Avoid duplicate task/listing associations
        existing = connection.execute(
            """
            SELECT id
            FROM search_run_jobs
            WHERE search_run_id = ?
              AND discovery_task_id = ?
              AND listing_id = ?
        """,
            (search_run_id, discovery_task_id, listing_id),
        ).fetchone()

        if existing:
            return existing["id"], False

        cursor = connection.execute(
            """
            INSERT INTO search_run_jobs (
                search_run_id,
                discovery_task_id,
                job_id,
                listing_id,
                processing_status,
                processing_reason
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (search_run_id, discovery_task_id, job_id, listing_id, processing_status, processing_reason),
        )

        return cursor.lastrowid, True


def save_job_evaluation(
    evaluation_run_id: int,
    job_id: int,
    evaluation: dict[str, Any],
    overall_score: float | None,
) -> None:
    """Store one validated job evaluation.

    Args:
        evaluation_run_id (int): Evaluation run ID.
        job_id (int): Canonical job ID.
        evaluation (dict[str, Any]): Structured evaluation fields.
        overall_score (float | None): Calculated match score.
    """
    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO job_evaluations (
                evaluation_run_id,
                job_id,
                technical_skills_score,
                experience_score,
                role_relevance_score,
                overall_score,
                work_setup,
                job_location,
                location_matches,
                matching_skills_json,
                missing_skills_json,
                matching_responsibilities_json,
                explanation,
                location_explanation,
                raw_evaluation_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(evaluation_run_id, job_id)
            DO UPDATE SET
                technical_skills_score = excluded.technical_skills_score,
                experience_score = excluded.experience_score,
                role_relevance_score = excluded.role_relevance_score,
                overall_score = excluded.overall_score,
                work_setup = excluded.work_setup,
                job_location = excluded.job_location,
                location_matches = excluded.location_matches,
                matching_skills_json = excluded.matching_skills_json,
                missing_skills_json = excluded.missing_skills_json,
                matching_responsibilities_json = excluded.matching_responsibilities_json,
                explanation = excluded.explanation,
                location_explanation = excluded.location_explanation,
                raw_evaluation_json = excluded.raw_evaluation_json,
                created_at = CURRENT_TIMESTAMP
        """,
            (
                evaluation_run_id,
                job_id,
                evaluation["technical_skills_score"],
                evaluation["experience_score"],
                evaluation["role_relevance_score"],
                overall_score,
                evaluation["work_setup"],
                evaluation["job_location"],
                None if evaluation["location_matches"] is None else int(evaluation["location_matches"]),
                json.dumps(evaluation["matching_skills"], ensure_ascii=False),
                json.dumps(evaluation["missing_skills"], ensure_ascii=False),
                json.dumps(evaluation["matching_responsibilities"], ensure_ascii=False),
                evaluation["explanation"],
                evaluation["location_explanation"],
                json.dumps(evaluation, ensure_ascii=False),
            ),
        )


def process_single_job(
    row: dict[str, Any],
    evaluation_run_id: int,
    search_run_id: int | None,
    candidate_profile: dict[str, Any],
    evaluation_config: dict[str, Any],
    filtering_config: dict[str, Any],
    search_id: int | None = None,
) -> dict[str, Any]:
    """Evaluate one job and update its processing status.

    Args:
        row (dict[str, Any]): Job ID and source listing data.
        evaluation_run_id (int): Evaluation run ID.
        search_run_id (int | None): Optional search run ID.
        candidate_profile (dict[str, Any]): Candidate details and skills.
        evaluation_config (dict[str, Any]): Model and scoring settings.
        filtering_config (dict[str, Any]): Location preferences.
        search_id (int | None): Optional owning search ID.

    Returns:
        Evaluation result or failure details.
    """
    job_id = row["job_id"]

    try:
        # 1. Load the original job listing
        job = json.loads(row["raw_json"])

        # 2. Evaluate with Ollama
        evaluation = evaluate_job(job, candidate_profile, evaluation_config, filtering_config)

        # 3. Validate the model response
        validate_evaluation(evaluation)

        # 4. Calculate the weighted overall score
        overall_score = calculate_match_score(evaluation, evaluation_config["score_weights"])

        filtering_status = classify_evaluation_result(evaluation, overall_score, evaluation_config)

        # 5. Save the evaluation in SQLite
        save_job_evaluation(evaluation_run_id, job_id, evaluation, overall_score)

        # 6. Update processing status
        with get_db_connection() as connection:
            connection.execute(
                """
                UPDATE search_run_jobs
                SET processing_status = 'evaluated',
                    processing_reason = 'Evaluation completed successfully'
                WHERE (? IS NULL OR search_run_id = ?)
                  AND job_id = ?
                  AND processing_status IN (
                      'ready_for_evaluation', 'evaluation_failed'
                  )
                  AND (? IS NULL OR search_run_id IN (
                      SELECT id FROM search_runs WHERE search_id = ?
                  ))
            """,
                (search_run_id, search_run_id, job_id, search_id, search_id),
            )

        return {
            "job_id": job_id,
            "status": "evaluated",
            "overall_score": overall_score,
            "filtering_status": filtering_status,
            "error": None,
        }

    except Exception as error:
        error_message = str(error)

        # 7. Record the failure in SQLite
        try:
            with get_db_connection() as connection:
                connection.execute(
                    """
                    UPDATE search_run_jobs
                    SET processing_status = 'evaluation_failed',
                        processing_reason = ?
                    WHERE (? IS NULL OR search_run_id = ?)
                      AND job_id = ?
                      AND processing_status IN (
                          'ready_for_evaluation', 'evaluation_failed'
                      )
                      AND (? IS NULL OR search_run_id IN (
                          SELECT id FROM search_runs WHERE search_id = ?
                      ))
                """,
                    (
                        error_message,
                        search_run_id,
                        search_run_id,
                        job_id,
                        search_id,
                        search_id,
                    ),
                )

        except Exception as db_error:
            error_message += f" | Could not update database status: {db_error}"

        return {"job_id": job_id, "status": "evaluation_failed", "overall_score": None, "error": error_message}


def process_job_batch(
    rows: list[dict[str, Any]],
    evaluation_run_id: int,
    search_run_id: int | None,
    candidate_profile: dict[str, Any],
    evaluation_config: dict[str, Any],
    filtering_config: dict[str, Any],
    search_id: int | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Evaluate jobs sequentially and report each completed result.

    Args:
        rows (list[dict[str, Any]]): Jobs to evaluate.
        evaluation_run_id (int): Evaluation run ID.
        search_run_id (int | None): Optional search run ID.
        candidate_profile (dict[str, Any]): Candidate details and skills.
        evaluation_config (dict[str, Any]): Model and scoring settings.
        filtering_config (dict[str, Any]): Location preferences.
        search_id (int | None): Optional owning search ID.
        progress_callback (Callable[[dict[str, Any]], None] | None): Optional result callback.

    Returns:
        Per-job evaluation results.
    """
    results = []

    total = len(rows)

    for index, row in enumerate(rows, start=1):
        logger.info(
            "[%s/%s] Processing job %s: %s",
            index,
            total,
            row["job_id"],
            row["title"],
        )

        result = process_single_job(
            row=row,
            evaluation_run_id=evaluation_run_id,
            search_run_id=search_run_id,
            candidate_profile=candidate_profile,
            evaluation_config=evaluation_config,
            filtering_config=filtering_config,
            search_id=search_id,
        )

        result.setdefault("title", row["title"])
        results.append(result)
        if progress_callback is not None:
            progress_callback(result)

        if result["status"] == "evaluated":
            logger.info("Completed - Score: %s", result["overall_score"])
        else:
            logger.warning("Failed - %s", result["error"])

    successful = sum(result["status"] == "evaluated" for result in results)

    failed = sum(result["status"] == "evaluation_failed" for result in results)

    logger.info("Batch summary: total=%s successful=%s failed=%s", total, successful, failed)

    return results


# ---------------------------------------------------------
# Application status management
# ---------------------------------------------------------


def get_application_statuses(job_ids: list[int], default_status: str | None = "new") -> dict[int, str | None]:
    """Return application statuses for multiple jobs.

    Args:
        job_ids (list[int]): Canonical job IDs.
        default_status (str | None): Value for jobs without a saved status.

    Returns:
        Mapping of job IDs to statuses.
    """
    job_ids = list(dict.fromkeys(job_ids))

    if not job_ids:
        return {}

    placeholders = ",".join("?" for _ in job_ids)

    with get_db_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT job_id, status
            FROM job_application_statuses
            WHERE job_id IN ({placeholders})
            """,
            job_ids,
        ).fetchall()

    statuses = dict.fromkeys(job_ids, default_status)

    for row in rows:
        statuses[row["job_id"]] = row["status"]

    return statuses


def update_application_status(
    job_id: int,
    new_status: str,
    notes: str | None = None,
    default_status: str = "new",
) -> dict[str, Any]:
    """Save an application status and record any transition.

    Args:
        job_id (int): Canonical job ID.
        new_status (str): Status to save.
        notes (str | None): Optional status notes.
        default_status (str): Prior status when no record exists.

    Returns:
        Status transition details.
    """
    if new_status not in APPLICATION_STATUSES:
        raise ValueError(f"Invalid application status: {new_status}. Allowed statuses: {sorted(APPLICATION_STATUSES)}")

    with get_db_connection() as connection:
        # Retrieve the existing application record.
        existing = connection.execute(
            """
            SELECT status, notes
            FROM job_application_statuses
            WHERE job_id = ?
        """,
            (job_id,),
        ).fetchone()

        if existing is None:
            old_status = default_status or "new"

            # Create the initial status record.
            connection.execute(
                """
                INSERT INTO job_application_statuses (
                    job_id,
                    status,
                    notes
                )
                VALUES (?, 'new', ?)
            """,
                (job_id, notes),
            )

            current_notes = notes

        else:
            old_status = existing["status"]
            if old_status == "new" and default_status == "ai_filtered":
                old_status = "ai_filtered"
            current_notes = existing["notes"]

        # Update notes only when new notes were supplied.
        if notes is not None:
            current_notes = notes

        # Record a transition only if the status actually changes.
        status_changed = old_status != new_status

        if status_changed:
            connection.execute(
                """
                UPDATE job_application_statuses
                SET status = ?,
                    notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
            """,
                (new_status, current_notes, job_id),
            )

            connection.execute(
                """
                INSERT INTO job_status_history (
                    job_id,
                    old_status,
                    new_status,
                    notes
                )
                VALUES (?, ?, ?, ?)
            """,
                (job_id, old_status, new_status, notes),
            )

        elif notes is not None:
            # Notes can be updated without creating a status transition.
            connection.execute(
                """
                UPDATE job_application_statuses
                SET notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
            """,
                (current_notes, job_id),
            )

    return {
        "job_id": job_id,
        "old_status": old_status,
        "new_status": new_status,
        "changed": status_changed,
    }


def get_application_status_history(job_id: int) -> list[dict[str, Any]]:
    """Return a job's status history in chronological order.

    Args:
        job_id (int): Canonical job ID.

    Returns:
        Status history records.
    """
    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                job_id,
                old_status,
                new_status,
                changed_at,
                notes
            FROM job_status_history
            WHERE job_id = ?
            ORDER BY changed_at ASC, id ASC
        """,
            (job_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def create_evaluation_run(search_id: int, search_run_id: int | None, evaluation_config: dict[str, Any]) -> int:
    """Create an evaluation run with its model settings.

    Args:
        search_id (int): Owning search ID.
        search_run_id (int | None): Optional discovery run ID.
        evaluation_config (dict[str, Any]): Model and scoring settings.

    Returns:
        New evaluation run ID.
    """

    model_name = evaluation_config["model"]
    context_size = evaluation_config.get("context_size")
    temperature = evaluation_config.get("temperature")
    score_weights = evaluation_config.get("score_weights", {})

    with get_db_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO evaluation_runs (
                search_id,
                search_run_id,
                model_name,
                context_size,
                temperature,
                score_weights_json,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, 'running')
        """,
            (
                search_id,
                search_run_id,
                model_name,
                context_size,
                temperature,
                json.dumps(score_weights, ensure_ascii=False),
            ),
        )

        evaluation_run_id = cursor.lastrowid

    return evaluation_run_id


def update_evaluation_run(evaluation_run_id: int, status: str, error_message: str | None = None) -> None:
    """Update an evaluation run's status.

    Args:
        evaluation_run_id (int): Evaluation run ID.
        status (str): New run status.
        error_message (str | None): Optional failure explanation.
    """

    allowed_statuses = {"running", "completed", "completed_with_errors", "failed", "cancelled"}

    if status not in allowed_statuses:
        raise ValueError(f"Invalid evaluation run status: {status}")

    with get_db_connection() as connection:
        connection.execute(
            """
            UPDATE evaluation_runs
            SET status = ?,
                error_message = ?,
                started_at = CASE
                    WHEN ? = 'running' AND started_at IS NULL
                    THEN CURRENT_TIMESTAMP
                    ELSE started_at
                END,
                completed_at = CASE
                    WHEN ? = 'running'
                    THEN NULL
                    WHEN ? IN (
                        'completed',
                        'completed_with_errors',
                        'failed',
                        'cancelled'
                    )
                    THEN CURRENT_TIMESTAMP
                    ELSE completed_at
                END
            WHERE id = ?
        """,
            (status, error_message, status, status, status, evaluation_run_id),
        )
