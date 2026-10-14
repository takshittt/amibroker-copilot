from pathlib import Path

import pytest

from copilot.evals import load_tasks
from copilot.kb import KBError

EVALS_DIR = Path(__file__).resolve().parents[3] / "evals" / "write"

TASK = """\
id: sample
market: nse_eq
timeframe: daily
difficulty: easy
request: Buy on a moving average cross.
expect:
  status: checked
  retrieved: [MA]
  calls: [MA, Cross]
"""


def problems(directory, catalog):
    with pytest.raises(KBError) as raised:
        load_tasks(directory, catalog)
    return raised.value.problems


def test_the_write_test_set_loads(catalog):
    tasks = load_tasks(EVALS_DIR, catalog)
    assert len(tasks) >= 10
    assert len({task.id for task in tasks}) == len(tasks)
    assert {task.market for task in tasks} >= {"nse_eq", "nse_fo", "mcx", "crypto"}
    assert {task.difficulty for task in tasks} == {"easy", "medium", "hard"}
    assert {task.expect.status for task in tasks} == {"checked", "clarify"}
    assert {"daily", "5min"} <= {task.timeframe for task in tasks}


def test_valid_task_loads(tmp_path, catalog):
    (tmp_path / "sample.yaml").write_text(TASK)
    (task,) = load_tasks(tmp_path, catalog)
    assert task.expect.calls == ["MA", "Cross"]


@pytest.mark.parametrize(
    ("old", "new", "words"),
    [
        ("market: nse_eq", "market: moon", "unknown market"),
        ("timeframe: daily", "timeframe: 1d", "unknown timeframe"),
        ("retrieved: [MA]", "retrieved: [TrailStop]", "TrailStop is not in the function list"),
        ("id: sample", "id: other", "must match the file name"),
        ("status: checked", "status: perfect", "status"),
        ("difficulty: easy", "difficulty: easy\nnotes: x", "notes"),
    ],
)
def test_bad_task_is_reported(tmp_path, catalog, old, new, words):
    (tmp_path / "sample.yaml").write_text(TASK.replace(old, new))
    found = problems(tmp_path, catalog)
    assert len(found) == 1
    assert "sample.yaml" in found[0]
    assert words in found[0]


def test_empty_directory_is_a_problem(tmp_path, catalog):
    assert "no task files" in problems(tmp_path, catalog)[0]
