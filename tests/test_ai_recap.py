import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import httpx2
import pytest

from services import ai_recap
from services.ai_recap import generate_recap, recap_facts, local_matchfeed_recap
from services.matchfeed_context import matchfeed_recap_context, recap_callbacks


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


FILLER = ("The rest of the paragraph is padding written without a single figure so the validator only sees "
          "the numbers placed on purpose, which keeps these tests focused on grounding rather than prose. ")


def recap_response(headline="", body=""):
    return {"choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps({"headline": headline, "body": body}),
    }}]}


def grounded(opening):
    return opening + " " + FILLER * 3


@pytest.mark.asyncio
async def test_groq_recap_sends_facts_packet_and_returns_validated_text():
    body = grounded("Player went 12 kills deep on Ascent.")
    session = FakeSession(FakeResponse(200, recap_response("A night on Ascent", body)))
    player = {"puuid": "p1", "name": "Player", "team_id": "Red", "stats": {"kills": 12, "deaths": 10}}
    detail = {"players": [player], "metadata": {"map": {"name": "Ascent"}}, "teams": [], "kills": []}

    result = await generate_recap(session, "test-key", "openai/gpt-oss-120b", detail, [player], player)

    assert result == {"headline": "A NIGHT ON ASCENT", "recap": " ".join(body.split())}
    url, request = session.request
    assert url == "https://api.groq.com/openai/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer test-key"
    payload = request["json"]
    assert payload["model"] == "openai/gpt-oss-120b"
    assert payload["reasoning_effort"] == "low"
    assert payload["temperature"] == 0.85
    assert payload["response_format"] == {"type": "json_object"}
    packet = payload["messages"][-1]["content"]
    assert packet.startswith("FACTS:") and "Ascent" in packet and "- Player:" in packet
    # Both few-shot examples are sent as user/assistant pairs ahead of the real packet.
    assert [m["role"] for m in payload["messages"]] == ["system", "user", "assistant", "user", "assistant", "user"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tone,expected", [("kind", "warm"), ("harsh", "blunt"),
                                           ("constructive", "actionable"), ("no_filter", "profane")])
async def test_recap_prompt_uses_selected_tone(tone, expected):
    session = FakeSession(FakeResponse(200, recap_response("Match", grounded("Quiet."))))
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
    body = grounded("Nobody wrote anything down.")
    responses = iter([
        FakeResponse(503, {}),
        FakeResponse(200, recap_response("Match headline", body)),
    ])

    class RetryingSession:
        def post(self, *args, **kwargs):
            return next(responses)

    async def skip_sleep(seconds):
        assert seconds == 1

    monkeypatch.setattr("services.ai_recap.asyncio.sleep", skip_sleep)
    assert await generate_recap(RetryingSession(), "key", "model", {}, [], {}) == {
        "headline": "MATCH HEADLINE", "recap": " ".join(body.split())
    }


@pytest.mark.asyncio
async def test_invented_number_is_retried_with_feedback_then_accepted():
    player = {"puuid": "p1", "name": "Friend", "team_id": "Red", "stats": {"kills": 13, "deaths": 16}}
    detail = {"players": [player], "metadata": {"map": {"name": "Haven"}},
              "teams": [{"team_id": "Red", "rounds": {"won": 5, "lost": 13}}]}
    bad = recap_response("FRIEND HITS 40 BOMBS", grounded("Friend dropped 412 ADR in a 5-13 loss."))
    good = recap_response("HAVEN HAUNTS FRIEND", grounded("Friend went 13/16 in a 5-13 loss on Haven."))
    responses = iter([FakeResponse(200, bad), FakeResponse(200, good)])
    sent = []

    class Session:
        def post(self, url, **kwargs):
            sent.append(kwargs["json"]["messages"])
            return next(responses)

    result = await generate_recap(Session(), "key", "model", detail, [player], player)
    assert result["headline"] == "HAVEN HAUNTS FRIEND"
    assert "numbers not in FACTS: 40, 412" in sent[1][-1]["content"]


@pytest.mark.asyncio
async def test_two_failed_validations_fall_back_to_local_recap():
    session = FakeSession(FakeResponse(200, recap_response("TOO SHORT", "Friend went 99 for 1.")))
    assert await generate_recap(session, "key", "model", {}, [], {}) is None


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


def _match_fixture(player, round_winners, moments, map_name="Corrode"):
    enemies = [{"puuid": f"enemy{index}", "team_id": "Blue"} for index in range(5)]
    won = round_winners.count("Red")
    lost = round_winners.count("Blue")
    return {
        "players": [player, *enemies],
        "metadata": {"map": {"name": map_name}},
        "teams": [{"team_id": "Red", "rounds": {"won": won, "lost": lost}}, {"team_id": "Blue"}],
        "rounds": [{"id": index, "winning_team": winner} for index, winner in enumerate(round_winners)],
        "kills": [
            {"round": number - 1, "time_in_round_in_ms": index * 1000, "killer": player,
             "victim": enemy, "weapon": {"name": weapon, "type": "Weapon"}}
            for number, weapon, count in moments
            for index, enemy in enumerate(enemies[:count], start=1)
        ],
    }


def test_lopsided_win_local_story_stays_factual():
    player = {"puuid": "p1", "name": "Player", "team_id": "Red", "is_smurf": True,
              "stats": {"kills": 20, "deaths": 7, "assists": 5, "score": 5445}}
    detail = _match_fixture(player, ["Red"] * 10 + ["Blue"] * 2 + ["Red"] * 3,
                            [(9, "Vandal", 4), (14, "Phantom", 1), (15, "Vandal", 4)])
    factual_story = ("Player dropped a 4K in the final round with the Vandal. "
                     "The team led 10–2 at halftime and won 13–2 on Corrode.")
    assert local_matchfeed_recap(detail, [player], player)["recap"] == factual_story


def test_partial_round_data_never_labels_a_play_match_winning():
    player = {"puuid": "p1", "name": "Player", "team_id": "Red"}
    detail = _match_fixture(player, ["Red"] * 10 + ["Blue"] * 2 + ["Red"] * 3, [(15, "Vandal", 4)])
    detail["rounds"].pop(4)
    facts = recap_facts(detail, [player], player)
    assert "half_results" not in facts and "match_winning_round" not in facts
    assert local_matchfeed_recap(detail, [player], player)["recap"] == (
        "Player dropped a 4K in round 15 with the Vandal. The team won 13–2 on Corrode."
    )


def test_ace_can_contrast_with_verified_second_half_collapse():
    player = {"puuid": "p1", "name": "Friend", "team_id": "Red", "stats": {"kills": 13, "deaths": 16}}
    detail = _match_fixture(player, ["Red"] * 5 + ["Blue"] * 13, [(1, "Sheriff", 5), (11, "Vandal", 3)], "Haven")
    recap = local_matchfeed_recap(detail, [player], player)
    assert recap["headline"] == "Friend's ace wasn't enough"
    assert recap["recap"] == ("Friend dropped an ace in round 1 with the Sheriff. "
                             "The team lost 5–13 on Haven without winning a round after halftime. "
                             "Friend still finished the match at 0.81 K/D.")


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
    session = FakeSession(FakeResponse(200, recap_response("Friend plays Haven", grounded("Friend on Haven."))))

    assert await generate_recap(session, "key", "model", detail, [registered], registered, registered_only=True)
    messages = session.request[1]["json"]["messages"]
    assert "Talk about the FEATURED players only" in messages[0]["content"]
    packet = messages[-1]["content"]
    assert "UnlinkedTeammate" not in packet and "EnemyName" not in packet


@pytest.mark.asyncio
async def test_registered_only_rejects_ai_output_naming_another_player():
    registered = {"puuid": "p1", "name": "Friend", "team_id": "Red"}
    detail = {"players": [registered, {"puuid": "p2", "name": "Stranger", "team_id": "Red"}]}
    session = FakeSession(FakeResponse(200, recap_response("Friend vs Stranger", grounded("Stranger fought hard."))))

    assert await generate_recap(session, "key", "model", detail, [registered], registered,
                                registered_only=True) is None


@pytest.mark.asyncio
async def test_packet_precomputes_acs_so_the_model_never_does_arithmetic():
    player = {"name": "SageMain", "team_id": "Red", "stats": {"score": 5778}}
    detail = {"players": [player], "teams": [{"team_id": "Red", "rounds": {"won": 5, "lost": 13}}]}
    http = FakeSession(FakeResponse(200, recap_response("SAGEMAIN", grounded("SageMain had 412 ADR."))))
    assert await generate_recap(http, "key", "model", detail, [player], player) is None
    packet = http.request[1]["json"]["messages"][-3]["content"]
    assert "RESULT: Defeat 5-13" in packet and "321 ACS" in packet


@pytest.mark.asyncio
async def test_quiet_game_omits_unrelated_history():
    player = {"name": "Friend", "team_id": "Red", "stats": {"score": 4600, "kills": 16, "deaths": 15, "assists": 6}}
    detail = {"metadata": {"map": {"name": "Haven"}}, "teams": [{"team_id": "Red", "rounds": {"won": 13, "lost": 9}}]}
    context = [{"player": "Friend", "yesterday": {"wins": 1, "losses": 1, "draws": 0},
                "previous_match": {"map": "Bind", "score": "10-13", "outcome": "loss"}},
               {"player": "Stranger", "streak_entering_match": {"outcome": "loss", "games": 4}}]
    http = FakeSession(FakeResponse(200, recap_response("Haven holds", grounded("Friend won 13-9 on Haven."))))
    assert await generate_recap(http, "key", "model", detail, [player], player, recap_context=context)
    packet = http.request[1]["json"]["messages"][-1]["content"]
    assert "Stranger" not in packet and "Bind" not in packet
    assert local_matchfeed_recap(detail, [player], player,
                                 recap_context=context)["recap"] == "The team won 13–9 on Haven."


@pytest.mark.parametrize("other_team,shared", [("red", True), ("blue", False)])
def test_same_map_callback_requires_a_shared_side_in_the_previous_game(other_team, shared):
    players = [{"name": "One", "tag": "EU"}, {"name": "Two", "tag": "EU"}]
    start = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
    meta = {"id": "previous", "started_at": (start - timedelta(hours=2)).isoformat(), "map": {"name": "Haven"}}
    def history(team):
        return [{"meta": meta, "stats": {"team": team}, "teams": {"red": 13, "blue": 6}}]
    context = matchfeed_recap_context(players, "current", start, start, {"one#eu": history("red"),
                                                                         "two#eu": history(other_team)}, {})
    facts = {"teammates": players, "rounds": {"won": 5, "lost": 13}, "map": "Haven"}
    subject = "This lineup" if shared else "One"
    assert recap_callbacks(context, facts) == [f"{subject}'s previous game was a 13-6 win on Haven."]


def test_clutch_and_thrifty_are_team_facts_even_when_round_one_has_no_kills():
    player = {"name": "Friend", "puuid": "friend", "team_id": "Red"}
    detail = {"players": [player], "teams": [{"team_id": "Red"}, {"team_id": "Blue"}],
              "rounds": [{"id": 0, "winning_team": "Blue", "ceremony": "CeremonyClutch"},
                         {"id": 1, "winning_team": "Red", "ceremony": "CeremonyClutch"},
                         {"id": 2, "winning_team": "Red", "ceremony": "CeremonyThrifty"}],
              "kills": [{"round": 1, "time_in_round_in_ms": 3000, "killer": player}]}
    facts = recap_facts(detail, [player], player, registered_only=True)
    assert facts["special_round_wins"] == [{"round": 2, "team_win_type": "clutch"},
                                           {"round": 3, "team_win_type": "thrifty"}]
    assert facts["round_highlights"][0]["round"] == 2


def test_fallback_selects_one_callback_from_current_rank_streak_and_form_reversal():
    player = {"name": "One", "team_id": "Red", "stats": {"kills": 8, "deaths": 16}}
    detail = {"metadata": {"map": {"name": "Bind"}}, "teams": [{"team_id": "Red", "rounds": {"won": 7, "lost": 13}}]}
    history = [{"player": "One", "streak_entering_match": {"games": 4, "outcome": "win"},
                "previous_match": {"map": "Haven", "kda": [25, 10, 5]},
                "rank_changes": [{"when": "this match", "direction": "down", "to_rank": "Gold 1"}]}]
    facts = recap_facts(detail, [player], player)
    assert recap_callbacks(history, facts) == ["One ranked down to Gold 1 this match.",
                                               "One came in on 4 straight wins.",
                                               "One went 25/10 in their previous game on Haven."]
    story = local_matchfeed_recap(detail, [player], player, recap_context=history)["recap"]
    assert story == "The team lost 7–13 on Bind. One ranked down to Gold 1 this match."


@pytest.mark.asyncio
async def test_ai_receives_squad_lore_and_games_together_as_facts():
    body = grounded("Friend lost 7-13 on Haven and the Clutch Allergy is back for game 62.")
    http = FakeSession(FakeResponse(200, recap_response("HAVEN RECAP", body)))
    context = {"callback": {"label": "Clutch Allergy", "kind": "inside joke", "player": None,
                            "match_evidence": "The team recorded a loss."}, "games_together": 62}
    player = {"name": "Friend", "team_id": "Red"}
    detail = {"metadata": {"map": {"name": "Haven"}}, "teams": [{"team_id": "Red", "rounds": {"won": 7, "lost": 13}}]}
    result = await generate_recap(http, "test-key", "test-model", detail, [player], player, squad_context=context)
    assert "Clutch Allergy" in result["recap"]
    messages = http.request[1]["json"]["messages"]
    assert "Clutch Allergy" not in messages[0]["content"]
    packet = messages[-1]["content"]
    assert 'LORE: "Clutch Allergy" (inside joke)' in packet and "TOGETHER: 62 games" in packet


# --- Claude recaps -------------------------------------------------------------------------------

CLAUDE_PLAYER = {"puuid": "p1", "name": "Player", "team_id": "Red", "stats": {"kills": 12, "deaths": 10}}
CLAUDE_DETAIL = {"players": [CLAUDE_PLAYER], "metadata": {"map": {"name": "Ascent"}}, "teams": [], "kills": []}
GOOD_BODY = grounded("Player went 12 kills deep on Ascent.")


def claude_message(headline="A night on Ascent", body=GOOD_BODY, stop_reason="end_turn"):
    text = json.dumps({"headline": headline, "body": body})
    return SimpleNamespace(content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
                           stop_reason=stop_reason, stop_details=None,
                           usage=SimpleNamespace(input_tokens=2000, output_tokens=900))


def claude_client(*results):
    create = AsyncMock(side_effect=list(results))
    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create))), create


def api_error(status, error_type, message="error"):
    response = httpx2.Response(status, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    body = {"type": "error", "error": {"type": error_type, "message": message}}
    cls = anthropic.AuthenticationError if status == 401 else anthropic.APIStatusError
    return cls(message, response=response, body=body)


async def recap_with(client, groq_session=None, groq_key="groq-key"):
    session = groq_session or FakeSession(FakeResponse(200, recap_response("Groq backup", GOOD_BODY)))
    result = await generate_recap(session, groq_key, "openai/gpt-oss-120b", CLAUDE_DETAIL, [CLAUDE_PLAYER],
                                  CLAUDE_PLAYER, claude_client=client, claude_model="claude-sonnet-5-5",
                                  claude_effort="medium")
    return result, session


@pytest.fixture(autouse=True)
def reset_claude_warnings():
    ai_recap._claude_warned.clear()


@pytest.mark.asyncio
async def test_claude_writes_the_recap_with_medium_effort_and_json_schema(caplog):
    client, create = claude_client(claude_message())
    caplog.set_level("INFO")
    result, session = await recap_with(client)
    assert result == {"headline": "A NIGHT ON ASCENT", "recap": " ".join(GOOD_BODY.split())}
    assert session.request is None  # Groq was not needed
    request = create.await_args.kwargs
    assert request["model"] == "claude-sonnet-5-5"
    assert request["output_config"]["effort"] == "medium"
    assert request["output_config"]["format"]["schema"] == ai_recap.RECAP_SCHEMA
    assert request["fallbacks"] == "default" and request["betas"] == ai_recap.CLAUDE_RECAP_BETAS
    assert "temperature" not in request and "thinking" not in request
    assert "You write post-match recaps" in request["system"]
    assert [m["role"] for m in request["messages"]] == ["user", "assistant", "user", "assistant", "user"]
    assert request["messages"][-1]["content"].startswith("FACTS:")
    assert "2000 input and 900 output tokens" in caplog.text


@pytest.mark.asyncio
async def test_claude_gets_one_rewrite_then_falls_back_to_local_not_groq():
    bad = claude_message(body="Player went 99 kills deep. " + FILLER * 3)
    client, create = claude_client(bad, bad)
    result, session = await recap_with(client)
    assert result is None and session.request is None
    retry = create.await_args_list[1].kwargs["messages"]
    assert retry[-2]["role"] == "assistant" and retry[-1]["content"].startswith("Rejected: numbers not in FACTS: 99")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [
    api_error(402, "billing_error", "Your credit balance is too low"),
    api_error(401, "authentication_error"),
    api_error(529, "overloaded_error"),
    anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")),
    claude_message(stop_reason="refusal"),
    RuntimeError("unexpected SDK change"),
])
async def test_claude_unavailable_falls_back_to_groq(failure):
    client, _ = claude_client(failure)
    result, session = await recap_with(client)
    assert result["headline"] == "GROQ BACKUP"
    assert session.request is not None


@pytest.mark.asyncio
async def test_claude_unavailable_without_groq_uses_local_recap():
    client, _ = claude_client(api_error(529, "overloaded_error"))
    result, session = await recap_with(client, groq_key=None)
    assert result is None and session.request is None


@pytest.mark.asyncio
async def test_low_credit_is_logged_once_until_a_recap_succeeds(caplog):
    credit = api_error(402, "billing_error", "Your credit balance is too low")
    client, _ = claude_client(credit, credit, claude_message(), credit)
    for _ in range(4):
        await recap_with(client)
    assert caplog.text.count("credit balance is too low") == 2  # once, then again after the top-up worked
