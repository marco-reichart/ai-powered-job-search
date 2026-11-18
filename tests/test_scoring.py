import pytest

from src.job_search.scoring import calculate_match_score


def test_calculate_match_score_accepts_configuration_weight_names() -> None:
    """Accept configured score-weight names."""
    evaluation = {
        "technical_skills_score": 8,
        "experience_score": 6,
        "role_relevance_score": 9,
    }
    weights = {
        "technical_skills": 0.4,
        "experience": 0.3,
        "role_relevance": 0.3,
    }

    assert calculate_match_score(evaluation, weights) == 77.0


def test_calculate_match_score_maps_configuration_names_to_score_fields() -> None:
    """Map configured weights to evaluation score fields."""
    evaluation = {
        "technical_skills_score": 8,
        "experience_score": 6,
        "role_relevance_score": 9,
    }
    weights = {
        "technical_skills": 0.4,
        "experience": 0.3,
        "role_relevance": 0.3,
    }

    assert calculate_match_score(evaluation, weights) == 77.0


def test_calculate_match_score_requires_matching_score_field() -> None:
    """Raise when a weighted score field is missing."""
    with pytest.raises(KeyError, match="technical_skills_score"):
        calculate_match_score({}, {"technical_skills": 1.0})
