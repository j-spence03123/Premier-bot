from datetime import datetime, timedelta, timezone

from services.matchfeed import next_matchfeed_counts


BASE = datetime(2026, 11, 17, 18, tzinfo=timezone.utc)
PLAYERS = [
    {"puuid": "player", "name": "Player", "tag": "TEST"},
    {"puuid": "player2", "name": "Player2", "tag": "TEST"},
]


def add_match(feed, mid="one", players=PLAYERS, started=BASE):
    counts, footer = next_matchfeed_counts(feed, players, mid, started, started + timedelta(minutes=35))
    feed["match_counts"] = counts
    return footer


def test_group_and_solo_sessions_are_independent():
    feed = {}
    add_match(feed)
    footer = add_match(feed, "two", started=BASE + timedelta(minutes=45))
    solo = add_match(feed, "three", players=PLAYERS[:1], started=BASE + timedelta(minutes=90))
    assert footer.startswith("Second group")
    assert solo.startswith("First solo")
    assert sorted(s["count"] for s in feed["match_counts"]["sessions"].values()) == [1, 2]


def test_session_resets_after_one_hour_gap():
    feed = {}
    add_match(feed)
    assert add_match(feed, "two", started=BASE + timedelta(minutes=95)).startswith("First group")


def test_legacy_recap_state_is_dropped():
    feed = {}
    add_match(feed)
    session = next(iter(feed["match_counts"]["sessions"].values()))
    session.update(matches=[{"id": "one"}], recap_id="abc")
    feed["match_counts"]["pending_recaps"] = {"old": {}}
    add_match(feed, "two", started=BASE + timedelta(minutes=45))
    assert set(feed["match_counts"]) == {"sessions"}
    assert set(next(iter(feed["match_counts"]["sessions"].values()))) == {"last_finished", "count"}
