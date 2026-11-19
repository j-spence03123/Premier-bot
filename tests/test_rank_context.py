from datetime import datetime, timedelta, timezone

from PIL import Image

from graphics.rank_change import draw_rank_change_card
from utils.formatting import parse_time
from utils.rank_context import (act_entries, count_rank_entry, match_context, ordinal, rank_card_context,
                                rank_group, rank_group_name)
from utils.stored_matches import parse_stored

NOW = datetime(2026, 11, 18, 22, tzinfo=timezone.utc)


def row(hours_ago, tier, season="act2", match="m"):
    return {"date_raw": int((NOW - timedelta(hours=hours_ago)).timestamp()), "currenttier": tier,
            "season_id": season, "match_id": f"{match}{hours_ago}"}


def stored(hours_ago, red, blue, team="Red", map_name="Bind"):
    return {"meta": {"id": "x", "started_at": (NOW - timedelta(hours=hours_ago)).isoformat(),
                     "map": {"name": map_name}},
            "stats": {"team": team, "kills": 1, "deaths": 1, "score": 100}, "teams": {"red": red, "blue": blue}}


def test_rank_groups_and_words():
    assert [rank_group(t) for t in (0, 3, 14, 15, 17, 27)] == [None, 0, 3, 4, 4, 8]
    assert rank_group_name("Platinum 2") == "Platinum" and rank_group_name("Radiant") == "Radiant"
    assert [ordinal(n) for n in (1, 2, 3, 11, 12, 22)] == ["First", "Second", "Third", "11th", "12th", "22nd"]


def test_counts_each_time_a_rank_is_reached_this_act():
    history = [row(90, 16, season="act1"), row(80, 13), row(60, 14), row(50, 15), row(40, 14), row(30, 15)]
    counts, complete = act_entries(history, "act2")
    assert complete and counts["4"] == 2 and counts["3"] == 1
    count, record = count_rank_entry(None, history, 15)
    assert count == 2 and record == {"season": "act2", "complete": True, "groups": counts}


def test_current_rank_up_counts_even_before_history_catches_up():
    history = [row(90, 16, season="act1"), row(80, 14)]
    assert count_rank_entry(None, history, 15)[0] == 1


def test_unconfirmed_act_history_hides_the_count_until_saved_tally_is_complete():
    history = [row(20, 14), row(10, 15)]  # does not reach the start of the act
    count, record = count_rank_entry(None, history, 15)
    assert count is None and record["complete"] is False
    saved = {"season": "act2", "complete": True, "groups": {"4": 2}}
    assert count_rank_entry(saved, [row(20, 14), row(10, 14)], 15)[0] == 3


def test_match_context_uses_the_latest_recent_game():
    rows = [stored(5, 13, 2), stored(1, 13, 8)]
    assert match_context(rows, "up", NOW, parse_stored, parse_time) == "After a 13–8 win on Bind"
    assert match_context([stored(1, 8, 13, map_name="Lotus")], "down", NOW, parse_stored, parse_time) == \
        "After an 8–13 loss on Lotus"
    assert match_context([stored(5, 13, 8)], "up", NOW, parse_stored, parse_time) is None


def test_card_context_line_and_taller_card():
    text = rank_card_context("After a 13–8 win on Bind", 3, "Platinum 1")
    assert text == "After a 13–8 win on Bind  ·  Third time in Platinum this act"
    assert rank_card_context(None, None, "Gold 2") is None
    plain = Image.open(draw_rank_change_card("P", "Gold 3", "Platinum 1", "up", None, None))
    with_line = Image.open(draw_rank_change_card("P", "Gold 3", "Platinum 1", "up", None, None, context=text))
    assert (plain.height, with_line.height) == (500, 530)
