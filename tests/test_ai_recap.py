import pytest
import json

from services.ai_recap import generate_recap, recap_facts, generate_session_summary, local_matchfeed_recap


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self.body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self, **kwargs):
        return self.body


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.request = None

    def post(self, url, **kwargs):
        self.request = (url, kwargs)
        return self.response


@pytest.mark.asyncio
async def test_session_summary_receives_match_order_and_rr_coverage():
    http = FakeSession(FakeResponse(200, {"choices": [{"finish_reason": "stop", "message": {
        "content": '{"summary":"Kevin finished the session with a win on Haven."}'
    }}]}))
    data = {"players": ["Kevin"], "matches": [
        {"map": "Haven", "result": "W", "score": "13–8", "moments": [], "rank_changes": [],
         "rr_changes": [{"player_id": "p1", "player": "Kevin", "change": 20}]},
    ]}
    result = await generate_session_summary(http, "test-key", "test-model", data, "kind")
    assert result == "Kevin finished the session with a win on Haven."
    facts = json.loads(http.request[1]["json"]["messages"][1]["content"])
    assert facts["rr_totals"][0]["rr"] == 20
    assert facts["matches"][0]["map"] == "Haven"


@pytest.mark.asyncio
async def test_groq_recap_uses_match_facts_and_extracts_text():
    session = FakeSession(FakeResponse(200, {"choices": [{"finish_reason": "stop",
        "message": {"content": '{"headline":"A wild match", "recap":"A match recap."}'}}]}))
    player = {"puuid": "p1", "name": "Player", "team_id": "Red", "stats": {"kills": 12}}
    detail = {"players": [player], "metadata": {"map": {"name": "Ascent"}}, "teams": [], "kills": []}

    result = await generate_recap(session, "test-key", "qwen/qwen3.8-27b", detail, [player], player)

    assert result == {"headline": "A wild match", "recap": "A match recap."}
    url, request = session.request
    assert url == "https://api.groq.com/openai/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer test-key"
    assert request["json"]["model"] == "qwen/qwen3.8-27b"
    assert "Ascent" in request["json"]["messages"][1]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tone,expected", [("kind", "warm"), ("harsh", "blunt"),
                                           ("constructive", "actionable"), ("no_filter", "profane")])
async def test_recap_prompt_uses_selected_tone(tone, expected):
    session = FakeSession(FakeResponse(200, {"choices": [{"finish_reason": "stop",
        "message": {"content": '{"headline":"Match", "recap":"Recap."}'}}]}))
    await generate_recap(session, "key", "model", {}, [], {}, tone=tone)
    prompt = session.request[1]["json"]["messages"][0]["content"]
    assert expected in prompt
    if tone != "no_filter":
        assert "savage banter" not in prompt


@pytest.mark.asyncio
async def test_groq_error_falls_back_without_exposing_response(caplog):
    session = FakeSession(FakeResponse(429, {"error": {"code": "rate_limit_exceeded"}}))

    assert await generate_recap(session, "secret-key", "model", {}, [], {}) is None
    assert "rate_limit_exceeded" in caplog.text
    assert "secret-key" not in caplog.text


@pytest.mark.asyncio
async def test_invalid_generated_fields_fall_back():
    session = FakeSession(FakeResponse(200, {"choices": [{"finish_reason": "stop",
        "message": {"content": '{"headline":"", "recap":"Some recap."}'}}]}))

    assert await generate_recap(session, "test-key", "model", {}, [], {}) is None


@pytest.mark.asyncio
async def test_transient_server_error_retries_and_returns_recap(monkeypatch):
    responses = iter([
        FakeResponse(503, {}),
        FakeResponse(200, {"choices": [{"finish_reason": "stop", "message": {
            "content": '{"headline":"Match headline", "recap":"Match recap."}'}}]}),
    ])

    class RetryingSession:
        def post(self, *args, **kwargs):
            return next(responses)

    async def skip_sleep(seconds):
        assert seconds == 1

    monkeypatch.setattr("services.ai_recap.asyncio.sleep", skip_sleep)
    assert await generate_recap(RetryingSession(), "key", "model", {}, [], {}) == {
        "headline": "Match headline", "recap": "Match recap."
    }


def test_match_and_round_times_are_converted_to_seconds():
    detail = {"metadata": {"game_length_in_ms": 1_980_000}, "kills": [
        {"round": 0, "time_in_round_in_ms": 12_500, "killer": {}, "victim": {}},
        {"round": 1, "time_in_round_in_ms": None, "killer": {}, "victim": {}},
    ]}

    facts = recap_facts(detail, [], {})

    assert facts["duration_seconds"] == 1980
    assert facts["round_highlights"][0]["first_blood"]["seconds"] == 12.5
    assert len(facts["round_highlights"]) == 1


def test_round_highlights_summarise_multikills_without_repeating_all_events():
    player = {"puuid": "p1", "name": "Player", "team_id": "Red"}
    detail = {"players": [player], "kills": [
        {"round": 0, "time_in_round_in_ms": time, "killer": {"puuid": "p1"}, "victim": {}}
        for time in (1000, 2000, 3000, 4000)
    ]}

    highlights = recap_facts(detail, [player], player)["round_highlights"]

    assert highlights == [{"round": 1, "first_blood": {"seconds": 1.0, "killer": "Player", "victim": "Unknown"},
                           "multikills": [{"player": "Player", "kills": 4}]}]


def test_recap_uses_verified_weapons_and_ace():
    player = {"puuid": "p1", "name": "Friend", "team_id": "Red"}
    enemies = [{"puuid": f"enemy-{number}", "team_id": "Blue"} for number in range(5)]
    kills = [
        {"round": 0, "time_in_round_in_ms": 1000 * index, "killer": player, "victim": enemy,
         "weapon": {"name": "Sheriff", "type": "Weapon"}}
        for index, enemy in enumerate(enemies, 1)
    ]
    detail = {"players": [player, *enemies], "kills": kills}
    highlight = recap_facts(detail, [player], player, registered_only=True)["round_highlights"][0]
    assert highlight["first_blood"]["weapon"] == "Sheriff"
    assert highlight["multikills"][0] == {
        "player": "Friend", "kills": 5, "ace": True, "weapon_kills": {"Sheriff": 5},
    }
    assert "ace in round 1 with the Sheriff" in local_matchfeed_recap(detail, [player], player)["recap"]

    kills[-1]["weapon"] = {"name": "Paint Shells", "type": "Ability"}
    recap = local_matchfeed_recap(detail, [player], player)["recap"]
    assert "ace in round 1" in recap
    assert "Sheriff" not in recap
    assert "Paint Shells" not in recap


@pytest.mark.asyncio
@pytest.mark.parametrize("story, expected", [
    ("Friend dropped a [[WEAPON]] 4K. The team lost Haven 5–13.", "Friend dropped a Sheriff 4K."),
    ("Friend dropped a 4K. The team lost Haven 5–13.", "Friend dropped a 4K."),
    ("Friend dropped a [[WEAPON]] 4K. The [[WEAPON]] clocked out.", None),
    ("Friend dropped a 4K. Then came the Vandal cleanup.", None),
])
async def test_weapon_is_optional_and_limited_to_opening_highlight(story, expected):
    player = {"puuid": "p1", "name": "Friend", "team_id": "Red", "stats": {"kills": 9, "deaths": 15}}
    kills = [
        {"round": round_id, "time_in_round_in_ms": index * 1000, "killer": player,
         "weapon": {"name": weapon, "type": "Weapon"}}
        for round_id, weapon, count in ((0, "Sheriff", 4), (1, "Vandal", 3))
        for index in range(1, count + 1)
    ]
    teams = [{"team_id": "Red", "rounds": {"won": 5, "lost": 13}}, {"team_id": "Blue"}]
    rounds = [{"id": index, "winning_team": "Red" if index < 5 else "Blue"} for index in range(18)]
    detail = {"players": [player], "kills": kills, "teams": teams, "rounds": rounds}
    response = {"choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps({"headline": "An opening to remember", "recap": story})
    }}]}
    http = FakeSession(FakeResponse(200, response))
    result = await generate_recap(http, "test-key", "test-model", detail, [player], player)
    if expected:
        assert result["recap"].startswith(expected)
    else:
        assert result is None
    payload = http.request[1]["json"]["messages"][1]["content"]
    assert "Sheriff" not in payload and "Vandal" not in payload
    facts = json.loads(payload)
    assert facts["half_results"] == {"first_half": [5, 7], "second_half": [0, 6]}
    assert facts["teammates"][0]["match_kd"] == 0.6

    fallback = local_matchfeed_recap(detail, [player], player)
    assert fallback["recap"].count("Sheriff") == 1 and "Vandal" not in fallback["recap"]
    assert "Sheriff" not in fallback["headline"]
    assert fallback["recap"].index("5–13") < fallback["recap"].index("3K")
    assert "0–6 in the second half" in fallback["recap"]
    assert "half_results" not in recap_facts({**detail, "rounds": rounds[:-1]}, [player], player)


@pytest.mark.asyncio
async def test_match_recap_marks_smurf_and_uses_fallback_if_ai_ignores_it():
    player = {"puuid": "p1", "name": "Alt", "team_id": "Red",
              "is_smurf": True, "stats": {"kills": 5, "deaths": 16}}
    main = {"puuid": "p2", "name": "Main", "team_id": "Red",
            "stats": {"kills": 2, "deaths": 16}}
    players = [player, main]
    detail = {"players": players}
    http = FakeSession(FakeResponse(200, {"choices": [{"finish_reason": "stop", "message": {
        "content": '{"headline":"Rough game","recap":"Alt lost on Haven."}'
    }}]}))

    assert await generate_recap(http, "test-key", "test-model", detail, players, player) is None
    facts = json.loads(http.request[1]["json"]["messages"][1]["content"])
    alt, normal = facts["teammates"]
    assert alt["is_smurf"] and alt["poor_smurf_performance"]
    assert "is_smurf" not in normal
    recap = local_matchfeed_recap(detail, players, player, tone="harsh")["recap"]
    assert "Alt played on a registered smurf and went 5/16" in recap
    assert "scoreboard missed the memo" in recap


@pytest.mark.asyncio
async def test_registered_only_recap_omits_other_players_and_events():
    registered = {"puuid": "p1", "name": "Friend", "team_id": "Red", "stats": {"kills": 12}}
    unregistered = {"puuid": "p2", "name": "UnlinkedTeammate", "team_id": "Red"}
    opponent = {"puuid": "p3", "name": "EnemyName", "team_id": "Blue"}
    detail = {"players": [registered, unregistered, opponent], "metadata": {"map": {"name": "Haven"}},
              "teams": [], "kills": [
                  {"round": 0, "time_in_round_in_ms": 1000, "killer": {"puuid": "p1"}, "victim": {"puuid": "p3"}},
                  {"round": 1, "time_in_round_in_ms": 1000, "killer": {"puuid": "p3"}, "victim": {"puuid": "p1"}},
                  {"round": 2, "time_in_round_in_ms": 1000, "killer": {"puuid": "p2"}, "victim": {"puuid": "p3"}},
              ]}
    response = {"choices": [{"finish_reason": "stop", "message": {
        "content": '{"headline":"Friend plays Haven", "recap":"Friend fought hard."}'}}]}
    session = FakeSession(FakeResponse(200, response))

    assert await generate_recap(session, "key", "model", detail, [registered], registered, registered_only=True)
    messages = session.request[1]["json"]["messages"]
    assert "Only discuss named players listed in teammates" in messages[0]["content"]
    raw = messages[1]["content"]
    assert "UnlinkedTeammate" not in raw and "EnemyName" not in raw
    facts = json.loads(raw)
    assert facts["round_highlights"] == [
        {"round": 1, "first_blood": {"seconds": 1.0, "player": "Friend"}},
        {"round": 2, "first_death": {"seconds": 1.0, "player": "Friend"}},
    ]


@pytest.mark.asyncio
async def test_registered_only_rejects_ai_output_naming_another_player():
    registered = {"puuid": "p1", "name": "Friend", "team_id": "Red"}
    detail = {"players": [registered, {"puuid": "p2", "name": "Stranger", "team_id": "Red"}]}
    response = {"choices": [{"finish_reason": "stop", "message": {
        "content": '{"headline":"Friend vs Stranger", "recap":"Friend played."}'}}]}
    session = FakeSession(FakeResponse(200, response))

    assert await generate_recap(session, "key", "model", detail, [registered], registered, registered_only=True) is None
