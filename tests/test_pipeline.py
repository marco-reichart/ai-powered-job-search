from contextlib import nullcontext
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from src.job_search import pipeline


@pytest.fixture
def active_profile() -> dict[str, Any]:
    """Provide a minimal active profile for pipeline tests.

    Returns:
        Profile fixture data.
    """
    return {
        "id": 12,
        "candidate_profile": {"name": "Candidate"},
        "discovery_config": {"category_search": {"enabled": True}},
        "filtering_config": {"keep_unspecified_values": True},
        "evaluation_config": {"model": "test-model"},
    }


def test_run_job_search_pipeline_runs_stages_and_returns_summary(active_profile: dict[str, Any]) -> None:
    """Run discovery, filtering, and bounded evaluation.

    Args:
        active_profile (dict[str, Any]): Active profile fixture.
    """
    filtering_connection = MagicMock()
    filtering_connection.execute.return_value.fetchall.return_value = [
        {"processing_status": "ready_for_evaluation", "count": 2},
        {"processing_status": "filtered_out", "count": 1},
    ]

    with (
        patch.object(pipeline, "get_active_search_profile", return_value=active_profile),
        patch.object(pipeline, "create_search_run", return_value=21) as create_run,
        patch.object(
            pipeline,
            "prepare_discovery_tasks",
            return_value=[{"task_id": 101}, {"task_id": 102}],
        ),
        patch.object(
            pipeline,
            "execute_discovery_task",
            side_effect=[{"task_id": 101, "status": "completed"}, {"task_id": 102, "status": "completed"}],
        ) as execute_task,
        patch.object(
            pipeline,
            "complete_search_run",
            return_value={"search_run_id": 21, "status": "completed", "unique_jobs": 3},
        ),
        patch.object(
            pipeline,
            "filter_search_run_jobs",
            return_value=[{"job_id": 1}, {"job_id": 2}],
        ),
        patch.object(pipeline, "get_db_connection", return_value=nullcontext(filtering_connection)),
        patch.object(pipeline, "create_evaluation_run", return_value=31) as create_eval,
        patch.object(
            pipeline,
            "run_evaluation_batches",
            return_value={
                "batches_processed": 1,
                "total_processed": 2,
                "evaluated": 1,
                "failed": 1,
                "remaining": 1,
                "run_status": "running",
                "batch_results": [],
            },
        ) as run_batches,
    ):
        result = pipeline.run_job_search_pipeline(7, batch_size=2, max_batches=1)

    create_run.assert_called_once_with(7, 12)
    assert execute_task.call_args_list == [call(21, 101), call(21, 102)]
    create_eval.assert_called_once_with(7, 21, active_profile["evaluation_config"])
    run_batches.assert_called_once_with(
        search_run_id=21,
        evaluation_run_id=31,
        candidate_profile=active_profile["candidate_profile"],
        evaluation_config=active_profile["evaluation_config"],
        filtering_config=active_profile["filtering_config"],
        batch_size=2,
        max_batches=1,
    )
    assert result["search_run_id"] == 21
    assert result["evaluation_run_id"] == 31
    assert result["filtering"] == {
        "passed": 2,
        "statuses": {"ready_for_evaluation": 2, "filtered_out": 1},
    }
    assert result["run_status"] == "running"
    assert result["failed"] == 1


def test_discovery_failure_marks_search_run_failed_and_stops_pipeline(active_profile: dict[str, Any]) -> None:
    """Stop the pipeline and mark the run failed after discovery errors.

    Args:
        active_profile (dict[str, Any]): Active profile fixture.
    """
    connection = MagicMock()

    with (
        patch.object(pipeline, "get_active_search_profile", return_value=active_profile),
        patch.object(pipeline, "create_search_run", return_value=22),
        patch.object(
            pipeline,
            "prepare_discovery_tasks",
            return_value=[{"task_id": 103}, {"task_id": 104}],
        ),
        patch.object(
            pipeline,
            "execute_discovery_task",
            side_effect=[{"task_id": 103, "status": "completed"}, OSError("API unavailable")],
        ),
        patch.object(pipeline, "get_db_connection", return_value=nullcontext(connection)),
        patch.object(pipeline, "filter_search_run_jobs") as filter_jobs,
        patch.object(pipeline, "create_evaluation_run") as create_eval,
        pytest.raises(RuntimeError, match="Discovery task 104 failed"),
    ):
        pipeline.run_job_search_pipeline(7)

    connection.execute.assert_called_once()
    assert connection.execute.call_args.args[1][1] == 22
    filter_jobs.assert_not_called()
    create_eval.assert_not_called()


def test_run_job_search_pipeline_requires_active_profile() -> None:
    """Require an active search profile before starting a run."""
    with (
        patch.object(pipeline, "get_active_search_profile", return_value=None),
        pytest.raises(ValueError, match="No active search profile"),
    ):
        pipeline.run_job_search_pipeline(7)


def test_evaluation_stage_deduplicates_jobs_across_listing_associations() -> None:
    """Evaluate each canonical job once across listing associations."""
    associations = [
        {"job_id": 5, "raw_json": '{"title": "First listing"}'},
        {"job_id": 5, "raw_json": '{"title": "Duplicate listing"}'},
        {"job_id": 6, "raw_json": '{"title": "Another job"}'},
    ]
    selection_connection = MagicMock()
    selection_connection.execute.return_value.fetchall.return_value = associations
    status_connection = MagicMock()
    status_connection.execute.return_value.fetchone.side_effect = [(0,), (0,)]

    with (
        patch.object(
            pipeline,
            "get_db_connection",
            side_effect=[nullcontext(selection_connection), nullcontext(status_connection)],
        ),
        patch.object(
            pipeline,
            "process_job_batch",
            return_value=[
                {"status": "evaluated"},
                {"status": "evaluated"},
            ],
        ) as process_batch,
        patch.object(pipeline, "update_evaluation_run") as update_run,
    ):
        result = pipeline.run_evaluation_stage(
            search_run_id=None,
            evaluation_run_id=31,
            candidate_profile={},
            evaluation_config={},
            filtering_config={},
            search_id=7,
        )

    processed_rows = process_batch.call_args.kwargs["rows"]
    assert [row["job_id"] for row in processed_rows] == [5, 6]
    assert process_batch.call_args.kwargs["search_run_id"] is None
    assert process_batch.call_args.kwargs["search_id"] == 7
    query = selection_connection.execute.call_args.args[0]
    assert "NOT EXISTS" in query
    assert "job_evaluations" in query
    assert result["total"] == 2
    assert result["evaluated"] == 2
    update_run.assert_called_once_with(31, "completed")


def test_batch_runner_does_not_retry_a_failed_job_again_in_same_call() -> None:
    """Skip failed jobs when selecting a later batch in the same call."""
    batch_results = [
        {
            "total": 1,
            "evaluated": 0,
            "failed": 1,
            "remaining": 1,
            "run_status": "running",
            "results": [{"job_id": 11, "status": "evaluation_failed"}],
        },
        {
            "total": 1,
            "evaluated": 1,
            "failed": 0,
            "remaining": 0,
            "run_status": "completed_with_errors",
            "results": [{"job_id": 12, "status": "evaluated"}],
        },
    ]

    with (
        patch.object(
            pipeline,
            "run_evaluation_stage",
            side_effect=batch_results,
        ) as run_stage,
        patch.object(pipeline, "update_evaluation_run"),
    ):
        result = pipeline.run_evaluation_batches(
            search_run_id=None,
            evaluation_run_id=31,
            candidate_profile={},
            evaluation_config={},
            filtering_config={},
            batch_size=1,
            max_batches=2,
            search_id=7,
        )

    assert run_stage.call_args_list[1].kwargs["exclude_job_ids"] == {11}
    assert result["failed"] == 1
    assert result["evaluated"] == 1
