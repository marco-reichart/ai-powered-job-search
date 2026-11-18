import json
import logging
from typing import Any

import pandas as pd
import requests

OLLAMA_API_URL = "http://localhost:11434/api/chat"
logger = logging.getLogger(__name__)


def evaluate_job(
    job: dict[str, Any],
    candidate_profile: dict[str, Any],
    evaluation_config: dict[str, Any],
    filtering_config: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate a job against the candidate profile with Ollama.

    Args:
        job (dict[str, Any]): Listing data.
        candidate_profile (dict[str, Any]): Candidate details and skills.
        evaluation_config (dict[str, Any]): Model settings.
        filtering_config (dict[str, Any]): Location preferences.

    Returns:
        Structured evaluation.
    """

    preferred_locations = filtering_config["preferred_locations"]

    preferred_locations_text = "\n".join(f"- {location}" for location in preferred_locations)

    remote_rules = filtering_config["remote_rules"]
    remote_country = remote_rules["remote_country"]
    allow_mandatory_office_visits = remote_rules["allow_mandatory_office_visits"]
    remote_visit_instruction = (
        "Occasional mandatory office visits are acceptable. They do not by themselves make the location a mismatch."
        if allow_mandatory_office_visits
        else (
            "No mandatory office attendance is acceptable, including "
            "occasional visits. Any required attendance makes the "
            "location a mismatch."
        )
    )

    system_prompt = f"""
You are an experienced technical recruiter evaluating job opportunities.

Compare the candidate profile with the job listing and return a structured
evaluation of the candidate's suitability.

CANDIDATE PROFILE USAGE

- Use experience.professional_summary as evidence of the candidate's work,
  domain, and accomplishments when assessing experience and role relevance.
- Use experience.years_of_experience when comparing the candidate's seniority
  with the job requirements.
- Use technical_skills when assessing technical skills and target_roles when
  assessing role relevance.
- Treat an empty summary or unspecified years of experience as missing
  information; do not infer details that are not in the profile.

Evaluate three scoring criteria independently, each from 0 to 10.

SCORING CRITERIA

1. technical_skills_score
How well do the candidate's technical skills match the required and
preferred skills?

- 10: Nearly all important technical requirements are met.
- 5: Several relevant skills match, but important gaps exist.
- 0: Core technical requirements are missing.

2. experience_score
How well does the candidate's professional experience and seniority
match the requirements?

- 10: Experience and seniority closely match.
- 5: Relevant background, but some important requirements are unmet.
- 0: Background is fundamentally unsuitable.

3. role_relevance_score
How closely do the actual responsibilities match the candidate's
target roles?

- 10: Responsibilities closely match the target roles.
- 5: Similar field or partial overlap in responsibilities.
- 0: Unrelated role and responsibilities.

LOCATION CLASSIFICATION

Determine the actual work arrangement and job location using both
the listing metadata and the full job description.

Extract:
- work_setup: "remote", "hybrid", "onsite" or "unknown"
- job_location: city, region or country, or null
- location_matches: true, false or null

Candidate's preferred locations:
{preferred_locations_text}

Location rules:

REMOTE:
- Must be genuinely remote and allow working from {remote_country}.
- {remote_visit_instruction}

HYBRID:
- Must be based in one of the preferred locations or a region
  clearly including one of them.
- Hybrid positions elsewhere are not a match.

ONSITE:
- Must be based in one of the preferred locations or a region
  clearly including one of them.
- On-site positions elsewhere are not a match.

GENERAL:
- The job description takes precedence over conflicting metadata.
- Do not assume a job is fully remote just because it is labelled
  remote in the metadata.
- Do not infer the job location from the company's headquarters.
- Do not assume remote work is available from {remote_country}.
- If multiple locations are listed, at least one must be preferred.
- Use null when the available information is insufficient.

OTHER EVALUATION RULES

- Use only information from the candidate profile and job listing.
- Distinguish required skills from preferred skills.
- Evaluate the three scoring criteria independently of location.
- Keep explanations concise, a few sentences at most.
- Return valid JSON only. Do not include Markdown or additional text.

OUTPUT FORMAT

Return exactly this JSON structure:

{{
    "technical_skills_score": 0,
    "experience_score": 0,
    "role_relevance_score": 0,
    "work_setup": "",
    "job_location": "",
    "location_matches": true,
    "matching_skills": [],
    "missing_skills": [],
    "matching_responsibilities": [],
    "explanation": "",
    "location_explanation": ""
}}

Output requirements:
- Return every field shown in the JSON structure below.
- Do not omit any fields, even if you have no information for them.
- Scores must be numbers between 0 and 10, or null.
- work_setup must be "remote", "hybrid", "onsite" or "unknown".
- job_location must be a string or null.
- location_matches must be true, false or null.
- All matching/missing fields must be arrays of strings.
- Both explanations must be strings.
"""

    user_prompt = f"""
CANDIDATE PROFILE:

{json.dumps(candidate_profile, ensure_ascii=False, indent=2)}

JOB LISTING:

{json.dumps(job, ensure_ascii=False, indent=2)}

Evaluate the job using the instructions and output structure.
Return only valid JSON.
"""

    payload = {
        "model": evaluation_config["model"],
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        "format": "json",
        "stream": False,
        "options": {
            "temperature": evaluation_config["temperature"],
            "num_ctx": evaluation_config["context_size"],
        },
    }

    response = requests.post(OLLAMA_API_URL, json=payload, timeout=300)

    response.raise_for_status()

    result = response.json()
    content = result["message"]["content"]

    try:
        evaluation = json.loads(content)

    except json.JSONDecodeError as error:
        raise ValueError(f"Ollama returned invalid JSON: {error}\nResponse:\n{content}") from error

    return evaluation


def validate_evaluation(evaluation: dict[str, Any]) -> bool:
    """Validate the required evaluation fields and value ranges.

    Args:
        evaluation (dict[str, Any]): Structured model response.

    Returns:
        True when validation succeeds.
    """
    required_fields = {
        "technical_skills_score",
        "experience_score",
        "role_relevance_score",
        "work_setup",
        "job_location",
        "location_matches",
        "matching_skills",
        "missing_skills",
        "matching_responsibilities",
        "explanation",
    }

    missing_fields = required_fields - evaluation.keys()

    if missing_fields:
        raise ValueError(f"Missing fields: {missing_fields}")

    score_fields = ["technical_skills_score", "experience_score", "role_relevance_score"]

    for field in score_fields:
        score = evaluation[field]

        if score is not None:
            if not isinstance(score, (int, float)) or isinstance(score, bool):
                raise ValueError(f"Invalid score in {field}: {score}")

            if not 0 <= score <= 10:
                raise ValueError(f"Score outside 0-10 in {field}: {score}")

    if evaluation["work_setup"] not in {"remote", "hybrid", "onsite", "unknown"}:
        raise ValueError("Invalid work_setup")

    if evaluation["location_matches"] not in {True, False, None}:
        raise ValueError("Invalid location_matches")

    if evaluation["job_location"] is not None and not isinstance(evaluation["job_location"], str):
        raise ValueError("job_location must be a string or None")

    for field in ["matching_skills", "missing_skills", "matching_responsibilities"]:
        if not isinstance(evaluation[field], list):
            raise ValueError(f"{field} must be a list")

        if not all(isinstance(item, str) for item in evaluation[field]):
            raise ValueError(f"All items in {field} must be strings")

    if not isinstance(evaluation["explanation"], str):
        raise ValueError("explanation must be a string")

    return True


def classify_location_match(evaluation: dict[str, Any]) -> str:
    """Convert the location match result to a status.

    Args:
        evaluation (dict[str, Any]): Structured evaluation.

    Returns:
        matched, rejected, or unclear.
    """
    location_match = evaluation["location_matches"]

    if location_match is True:
        return "matched"

    if location_match is False:
        return "rejected"

    return "unclear"


def classify_evaluation_result(
    evaluation: dict[str, Any],
    overall_score: float | None,
    evaluation_config: dict[str, Any],
) -> str:
    """Classify a job against location and score filters.

    Args:
        evaluation (dict[str, Any]): Structured evaluation.
        overall_score (float | None): Weighted match score.
        evaluation_config (dict[str, Any]): Minimum score settings.

    Returns:
        kept, filtered_location, or filtered_score.
    """

    minimum_score = evaluation_config.get("minimum_score", 50)

    if not isinstance(minimum_score, (int, float)):
        raise ValueError("minimum_score must be a number")

    if not 0 <= minimum_score <= 100:
        raise ValueError("minimum_score must be between 0 and 100")

    # Location filtering takes priority.
    if evaluation["location_matches"] is False:
        return "filtered_location"

    # Apply the configurable minimum score.
    if overall_score is not None and overall_score < minimum_score:
        return "filtered_score"

    return "kept"
