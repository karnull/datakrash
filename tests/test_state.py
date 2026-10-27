"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  Tests for the state file
"""

import pytest

from datakrash.state import FIRED, Challenge, Send, State, StateCorrupt, StateStore
from tests.fakes import START


def test_missing_file_starts_armed(tmp_path):
    assert StateStore(tmp_path / "state.json").load() == State()


def test_round_trip(tmp_path):
    store = StateStore(tmp_path / "state.json")
    state = State(
        phase=FIRED,
        challenge=Challenge(attempt=2, prompt_at=START, cursor="m3"),
        fired_at=START,
        sends=[Send(due=START, delivered=["email"]), Send(due=START, skipped=True)],
        last_run=START,
    )

    store.save(state)

    assert store.load() == state
    assert [path.name for path in tmp_path.iterdir()] == ["state.json"]


@pytest.mark.parametrize(
    "text", ["{not json", '{"phase": "dozing"}', '{"challenge": {"cursor": "m1"}}']
)
def test_corrupt_file_is_reported(tmp_path, text):
    path = tmp_path / "state.json"
    path.write_text(text)

    with pytest.raises(StateCorrupt):
        StateStore(path).load()


def test_quarantine_moves_the_file_aside(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json")

    moved = StateStore(path).quarantine(START)

    assert not path.exists()
    assert moved.read_text() == "{not json"
