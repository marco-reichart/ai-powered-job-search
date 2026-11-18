import json
import re
from typing import Any

from src.job_search.database import get_db_connection


def normalize_value(value: Any) -> str:
    """Normalize a preference value for comparison.

    Args:
        value (Any): Value to normalize.

    Returns:
        Normalized string, or an empty string for non-text values.
    """
    if not isinstance(value, str):
        return ""

    value = value.strip().lower()
    value = value.replace("-", "_").replace(" ", "_")

    return value


def normalize_location(value: Any) -> str:
    """Normalize a location for case-insensitive matching.

    Args:
        value (Any): Location to normalize.

    Returns:
        Normalized location, or an empty string for non-text values.
    """
    if not isinstance(value, str):
        return ""

    value = value.strip().lower()

    value = value.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")

    return value


def is_unspecified_location(value: str) -> bool:
    """Treat country-only and unusable location labels as unspecified.

    Args:
        value (str): Location label.

    Returns:
        Whether the location lacks a specific place.
    """
    normalized = normalize_location(value)
    tokens = re.findall(r"[a-z0-9]+", normalized)
    country_tokens = {"deutschland", "germany", "de"}

    return not tokens or all(token in country_tokens for token in tokens)


def get_job_location_values(job: dict[str, Any]) -> list[str]:
    """Collect location, city, and metro values from a listing.

    Args:
        job (dict[str, Any]): Listing data.

    Returns:
        Non-empty location strings.
    """
    values = []

    location = job.get("location")

    if isinstance(location, str) and location.strip():
        values.append(location)

    for field in ["cities", "metros"]:
        field_values = job.get(field) or []

        if isinstance(field_values, str):
            field_values = [field_values]

        values.extend(value for value in field_values if isinstance(value, str) and value.strip())

    return values


def is_allowed_location(job: dict[str, Any], config: dict[str, Any]) -> bool:
    """Check whether a listing has an allowed or unspecified location.

    Args:
        job (dict[str, Any]): Listing data.
        config (dict[str, Any]): Local filtering settings.

    Returns:
        Whether the location passes the configured rule.
    """
    location_values = get_job_location_values(job)
    specific_locations = [value for value in location_values if not is_unspecified_location(value)]

    if not specific_locations:
        return config["keep_unspecified_values"]

    normalized_locations = [normalize_location(value) for value in specific_locations]
    allowed_values = [
        normalize_location(value)
        for value in (config["allowed_cities"] + config["allowed_metros"])
        if not is_unspecified_location(value)
    ]

    return any(allowed in location for location in normalized_locations for allowed in allowed_values if allowed)


def matches_preference(value: Any, allowed_values: list[Any], keep_unspecified: bool) -> bool:
    """Check a value against an allow-list.

    Args:
        value (Any): Listing value or values.
        allowed_values (list[Any]): Accepted values.
        keep_unspecified (bool): Whether missing values pass.

    Returns:
        Whether the value is allowed.
    """
    if value is None or value == "":
        return keep_unspecified

    if isinstance(value, list):
        if not value:
            return keep_unspecified

        allowed = {normalize_value(item) for item in allowed_values}

        return any(normalize_value(item) in allowed for item in value)

    return normalize_value(value) in {normalize_value(item) for item in allowed_values}


def filter_single_job(job: dict[str, Any], config: dict[str, Any]) -> tuple[bool, str]:
    """Apply local eligibility rules to one listing.

    Args:
        job (dict[str, Any]): Listing data.
        config (dict[str, Any]): Local filtering settings.

    Returns:
        Pass/fail result and reason.
    """
    keep_unspecified = config["keep_unspecified_values"]

    if not matches_preference(job.get("work_mode"), config["allowed_work_modes"], keep_unspecified):
        return False, "work_mode_not_allowed"

    enrichment = job.get("enrichment") or {}

    if not matches_preference(enrichment.get("employment_type"), config["allowed_employment_types"], keep_unspecified):
        return False, "employment_type_not_allowed"

    is_remote = normalize_value(job.get("work_mode")) == "remote"

    if not (is_remote and config["remote_rules"]["ignore_location_for_remote"]) and not is_allowed_location(
        job, config
    ):
        return False, "location_not_allowed"

    return True, "passed"


def filter_search_run_jobs(search_run_id: int, filtering_config: dict[str, Any]) -> list[dict[str, Any]]:
    """Filter newly discovered listings for a search run.

    Args:
        search_run_id (int): Search run ID.
        filtering_config (dict[str, Any]): Local filtering settings.

    Returns:
        Listings that passed filtering.
    """

    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                srj.id AS search_run_job_id,
                srj.job_id,
                srj.listing_id,
                jl.raw_json
            FROM search_run_jobs AS srj
            JOIN job_listings AS jl
                ON jl.id = srj.listing_id
            WHERE srj.search_run_id = ?
              AND srj.processing_status = 'found'
            ORDER BY srj.id
        """,
            (search_run_id,),
        ).fetchall()

    passed_jobs = []

    for row in rows:
        try:
            job = json.loads(row["raw_json"])

            passed, reason = filter_single_job(job, filtering_config)

            if passed:
                status = "ready_for_evaluation"
            elif "location" in reason.lower():
                status = "location_mismatch"
            else:
                status = "filtered_out"

            with get_db_connection() as connection:
                connection.execute(
                    """
                    UPDATE search_run_jobs
                    SET processing_status = ?,
                        processing_reason = ?
                    WHERE id = ?
                """,
                    (status, reason, row["search_run_job_id"]),
                )

            if passed:
                passed_jobs.append(
                    {
                        "search_run_job_id": row["search_run_job_id"],
                        "job_id": row["job_id"],
                        "listing_id": row["listing_id"],
                        "raw_json": row["raw_json"],
                    }
                )

        except Exception as error:
            error_message = f"Filtering failed: {str(error)}"

            with get_db_connection() as connection:
                connection.execute(
                    """
                    UPDATE search_run_jobs
                    SET processing_status = 'filtered_out',
                        processing_reason = ?
                    WHERE id = ?
                """,
                    (error_message, row["search_run_job_id"]),
                )

    return passed_jobs
