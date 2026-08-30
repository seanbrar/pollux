"""Unit tests for ``OutputCollection`` aggregation and status."""

from __future__ import annotations

import pytest

from pollux.interaction.collection import OutputCollection
from pollux.interaction.output import CompletionStatus, Metrics, Output, Usage

pytestmark = pytest.mark.unit


def _output(
    text: str,
    total: int = 0,
    *,
    completion_status: CompletionStatus = "clean",
) -> Output:
    return Output(
        text=text,
        usage=Usage(total_tokens=total),
        metrics=Metrics(completion_status=completion_status),
    )


def test_answers_and_structured_preserve_order():
    coll = OutputCollection(
        outputs=(
            Output(text="a", structured={"v": 1}),
            Output(text="b", structured={"v": 2}),
        )
    )
    assert coll.answers == ["a", "b"]
    assert coll.structured == [{"v": 1}, {"v": 2}]


def test_usage_is_summed_across_outputs():
    coll = OutputCollection(outputs=(_output("a", 3), _output("b", 5)))
    assert coll.usage.total_tokens == 8


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (["clean", "clean"], "ok"),
        (["clean", "error"], "partial"),
        (["error", "error"], "error"),
        ([], "ok"),
    ],
)
def test_status_reflects_execution_outcomes(statuses, expected):
    coll = OutputCollection(
        outputs=tuple(_output("", completion_status=status) for status in statuses)
    )
    assert coll.status == expected


def test_structured_output_does_not_require_text_for_success():
    coll = OutputCollection(outputs=(Output(structured={"value": 1}),))
    assert coll.status == "ok"


def test_to_jsonable_includes_outputs_and_aggregates():
    coll = OutputCollection(outputs=(_output("a", 1), _output("b", 2)))
    payload = coll.to_jsonable()
    assert payload["status"] == "ok"
    assert [o["text"] for o in payload["outputs"]] == ["a", "b"]
    assert payload["usage"]["total_tokens"] == 3
    assert "prompt_indexes" not in payload
    assert "source_indexes" not in payload
