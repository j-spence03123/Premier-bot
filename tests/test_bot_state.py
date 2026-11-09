from types import SimpleNamespace

import pytest

from services.bot_state import BotState


@pytest.mark.parametrize("name", ["accounts", "play_sessions", "matchfeeds", "rank_states", "queue_schedules", "agents"])
def test_state_round_trip(tmp_path, name):
    paths = SimpleNamespace(accounts_file=tmp_path / "accounts.json", play_sessions_file=tmp_path / "sessions.json",
                            matchfeeds_file=tmp_path / "feeds.json", rankstates_file=tmp_path / "ranks.json",
                            queue_schedule_file=tmp_path / "queue.json", agents_file=tmp_path / "agents.json")
    state = BotState(paths)
    load = getattr(state, f"load_{name}")
    save = getattr(state, f"save_{name}")
    assert load() == {}
    save({"guild": {"value": 1}})
    assert load() == {"guild": {"value": 1}}
