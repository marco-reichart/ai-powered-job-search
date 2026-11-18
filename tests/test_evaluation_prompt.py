from unittest.mock import patch

from src.job_search.evaluation import evaluate_job


def build_system_prompt(allow_visits: bool) -> str:
    """Build the system prompt with the requested office-visit rule.

    Args:
        allow_visits (bool): Whether occasional office visits are acceptable.

    Returns:
        Generated system prompt.
    """
    evaluation_config = {
        "model": "test-model",
        "temperature": 0,
        "context_size": 2048,
    }
    filtering_config = {
        "preferred_locations": ["Paris"],
        "remote_rules": {
            "remote_country": "France",
            "allow_mandatory_office_visits": allow_visits,
        },
    }

    with patch("src.job_search.evaluation.requests.post") as post:
        post.return_value.json.return_value = {
            "message": {"content": "{}"},
        }
        evaluate_job({}, {}, evaluation_config, filtering_config)

    return post.call_args.kwargs["json"]["messages"][0]["content"]


def test_prompt_uses_configured_remote_country() -> None:
    """Use the configured country in remote-work instructions."""
    system_prompt = build_system_prompt(allow_visits=False)

    assert "allow working from France" in system_prompt
    assert "Do not assume remote work is available from France" in system_prompt
    assert "Germany" not in system_prompt


def test_prompt_applies_office_visit_preference() -> None:
    """Reflect the office-visit preference in the prompt."""
    accepting_visits_prompt = build_system_prompt(allow_visits=True)
    rejecting_visits_prompt = build_system_prompt(allow_visits=False)

    assert "Occasional mandatory office visits are acceptable" in accepting_visits_prompt
    assert "Any required attendance makes the location a mismatch" not in accepting_visits_prompt
    assert "No mandatory office attendance is acceptable" in rejecting_visits_prompt
    assert "Any required attendance makes the location a mismatch" in rejecting_visits_prompt
