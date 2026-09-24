"""Results: what an evaluation knows about itself, and Agent.ask on top of it."""

import asyncio
from dataclasses import replace

import pytest

from flashrsi.core import Agent, Results, Task, Trajectory


def graded(*pairs, metric="accuracy"):
    return Results(
        (
            replace(
                Trajectory(task=Task(name, "question"), output="answer"),
                metrics={metric: value, "other": 1.0},
            )
            for name, value in pairs
        ),
        metric=metric,
    )


# -- Results ---------------------------------------------------------------


def test_an_evaluation_knows_its_own_score_without_being_told_the_metric():
    results = graded(("a", 1.0), ("b", 0.0), ("c", 0.5))

    assert results.score == 0.5
    # The same scores, read one task at a time: a comparison the mean cannot
    # express reads this instead.
    assert dict(results.per_task) == {"a": 1.0, "b": 0.0, "c": 0.5}


def test_an_evaluation_is_still_a_tuple_of_trajectories():
    """Existing loops keep working: this replaces no traversal."""
    results = graded(("a", 1.0), ("b", 0.0))

    assert isinstance(results, tuple)
    assert len(results) == 2
    assert [item.task.task_id for item in results] == ["a", "b"]
    assert results[0].output == "answer"
    assert len(list(zip(results, results, strict=True))) == 2


def test_slicing_an_evaluation_drops_the_score():
    """A subset was never measured as one, so it does not claim a score."""
    results = graded(("a", 1.0), ("b", 0.0))

    assert isinstance(results[:1], tuple)
    assert not isinstance(results[:1], Results)


def test_an_empty_evaluation_has_no_score_rather_than_a_zero_one():
    empty = Results((), metric="accuracy")

    assert not empty and dict(empty.per_task) == {}
    with pytest.raises(ValueError, match="empty evaluation"):
        empty.score


def test_per_task_reads_the_metric_the_evaluation_was_graded_on():
    results = graded(("a", 1.0), ("b", 0.0), metric="f1")

    assert dict(results.per_task) == {"a": 1.0, "b": 0.0}
    # A metric the grader did not attach is an error, not a silent zero, and it
    # is raised where the mistake is -- at construction, not at the first read.
    with pytest.raises(KeyError):
        Results(results, metric="absent")


def test_the_scores_are_read_once_and_the_same_mapping_is_handed_out():
    """A caller wanting both the mean and the per-task scores walks once."""
    results = graded(("a", 1.0), ("b", 0.0))

    assert results.per_task is results.per_task
    assert results.score == 0.5


# -- Agent.ask -------------------------------------------------------------


class Worker(Agent):
    name = "worker"
    description = "Offline Worker."

    def __init__(self, output="<INS>answered</INS>", status="finished"):
        super().__init__({"llm": {"model_name": "offline"}})
        self._output, self._status = output, status
        self.directories = []

    async def _run(self, prompt, working_dir=None):
        self.directories.append(working_dir)
        if self._status == "error":
            return Trajectory(status="error", error_message=self._output)
        return Trajectory(output=self._output)


def test_ask_answers_with_the_text_the_agent_produced():
    """Plain text: how a reply is wrapped is the asking prompt's business."""
    reply = asyncio.run(Worker().ask("question"))

    assert reply == "<INS>answered</INS>"
    assert type(reply) is str


def test_ask_raises_rather_than_handing_back_a_failed_run():
    """A caller that wants the text wants the call to have worked."""
    with pytest.raises(RuntimeError, match="worker failed: no model"):
        asyncio.run(Worker("no model configured", status="error").ask("question"))


def test_ask_can_produce_its_answer_by_editing_a_directory(tmp_path):
    worker = Worker()

    reply = asyncio.run(worker.ask("edit this", tmp_path))

    assert reply == "<INS>answered</INS>"
    assert worker.directories == [tmp_path.resolve()]


def test_an_observer_sees_every_question_and_supplies_the_error_text():
    """This is how an Algorithm records Worker calls without the algorithm
    arranging it, and how credentials it cannot see are redacted."""
    seen = []
    worker = Worker("secret-value", status="error")
    worker._observer = lambda prompt, result: (
        seen.append((prompt, result)) or "[hidden]"
    )

    with pytest.raises(RuntimeError, match=r"worker failed: \[hidden\]"):
        asyncio.run(worker.ask("question"))

    assert [prompt for prompt, _ in seen] == ["question"]
    assert seen[0][1].error_message == "secret-value"
