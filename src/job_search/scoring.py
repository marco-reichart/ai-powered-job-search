from typing import Any


def calculate_match_score(evaluation: dict[str, Any], score_weights: dict[str, float]) -> float | None:
    """Calculate a weighted score from available criteria.

    Args:
        evaluation (dict[str, Any]): Criterion scores.
        score_weights (dict[str, float]): Weight for each criterion.

    Returns:
        Overall score from 0 to 100, or None when no scores are available.
    """
    weighted_score = 0
    available_weight = 0

    for field, weight in score_weights.items():
        score = evaluation[f"{field}_score"]

        if score is not None:
            weighted_score += score * weight
            available_weight += weight

    if available_weight == 0:
        return None

    overall_score = weighted_score / available_weight

    return round(overall_score * 10, 1)
