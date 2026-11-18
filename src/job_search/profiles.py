import json
from typing import Any

from src.job_search.database import get_db_connection


def create_job_search(name: str, description: str | None = None) -> int:
    """Create a job search.

    Args:
        name (str): Search name.
        description (str | None): Optional search description.

    Returns:
        New search ID.
    """
    if not name or not name.strip():
        raise ValueError("Search name cannot be empty.")

    with get_db_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO job_searches (name, description)
            VALUES (?, ?)
            """,
            (name.strip(), description),
        )

        return cursor.lastrowid


def save_search_profile(
    search_id: int,
    candidate_profile: dict[str, Any],
    discovery_config: dict[str, Any],
    filtering_config: dict[str, Any],
    evaluation_config: dict[str, Any],
) -> int:
    """Save and activate a versioned search profile.

    Args:
        search_id (int): Search that owns the profile.
        candidate_profile (dict[str, Any]): Candidate details and skills.
        discovery_config (dict[str, Any]): Job discovery settings.
        filtering_config (dict[str, Any]): Local and LLM filtering settings.
        evaluation_config (dict[str, Any]): Model and scoring settings.

    Returns:
        New profile ID.
    """
    configurations = {
        "candidate_profile": candidate_profile,
        "discovery_config": discovery_config,
        "filtering_config": filtering_config,
        "evaluation_config": evaluation_config,
    }

    # Validate that all configurations can be serialized
    for name, config in configurations.items():
        if not isinstance(config, dict):
            raise TypeError(f"{name} must be a dictionary.")

    with get_db_connection() as connection:
        # Determine the next profile version
        result = connection.execute(
            """
            SELECT COALESCE(MAX(version), 0) + 1 AS next_version
            FROM search_profiles
            WHERE search_id = ?
        """,
            (search_id,),
        ).fetchone()

        version = result["next_version"]

        # Deactivate the previous profile
        connection.execute(
            """
            UPDATE search_profiles
            SET is_active = 0
            WHERE search_id = ?
        """,
            (search_id,),
        )

        # Insert the new profile
        cursor = connection.execute(
            """
            INSERT INTO search_profiles (
                search_id,
                version,
                candidate_profile_json,
                discovery_config_json,
                filtering_config_json,
                evaluation_config_json,
                is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, 1)
        """,
            (
                search_id,
                version,
                json.dumps(candidate_profile, ensure_ascii=False),
                json.dumps(discovery_config, ensure_ascii=False),
                json.dumps(filtering_config, ensure_ascii=False),
                json.dumps(evaluation_config, ensure_ascii=False),
            ),
        )

        profile_id = cursor.lastrowid

    return profile_id


def get_job_searches() -> list[dict[str, Any]]:
    """Return all saved searches, newest first.

    Returns:
        Search records.
    """
    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM job_searches
            ORDER BY created_at DESC
            """
        ).fetchall()

        return [dict(row) for row in rows]


def get_active_search_profile(search_id: int) -> dict[str, Any] | None:
    """Return a search's active profile.

    Args:
        search_id (int): Search ID.

    Returns:
        Decoded profile, or None when no active profile exists.
    """
    with get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM search_profiles
            WHERE search_id = ?
              AND is_active = 1
            LIMIT 1
        """,
            (search_id,),
        ).fetchone()

    return _decode_search_profile(row)


def get_search_profile(profile_id: int) -> dict[str, Any] | None:
    """Return a saved profile, including inactive versions.

    Args:
        profile_id (int): Profile ID.

    Returns:
        Decoded profile, or None when it does not exist.
    """
    with get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM search_profiles
            WHERE id = ?
        """,
            (profile_id,),
        ).fetchone()

    return _decode_search_profile(row)


def _decode_search_profile(row: Any) -> dict[str, Any] | None:
    """Decode JSON configuration fields in a profile row.

    Args:
        row (Any): Database row, or None.

    Returns:
        Decoded profile, or None.
    """
    if row is None:
        return None

    profile = dict(row)
    profile["candidate_profile"] = json.loads(profile.pop("candidate_profile_json"))
    profile["discovery_config"] = json.loads(profile.pop("discovery_config_json"))
    profile["filtering_config"] = json.loads(profile.pop("filtering_config_json"))
    profile["evaluation_config"] = json.loads(profile.pop("evaluation_config_json"))
    return profile
