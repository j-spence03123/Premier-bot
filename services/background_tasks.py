"""Long-running match and reminder polling tasks."""

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
from urllib.parse import quote
from zoneinfo import ZoneInfoNotFoundError

import discord

from services.account_registry import iter_linked_accounts
from services.json_store import JsonStoreError
from services.match_history import cached_match_detail
from services.matchfeed import format_match_notification, group_registered_players, next_matchfeed_counts
from services.matchfeed_context import matchfeed_recap_context
from services.session_recap import post_session_recaps, session_match
from utils.recap_tones import normalize_tone


MATCHFEED_POLL_SECONDS = 120
MATCHFEED_CACHE_SECONDS = 100


async def queue_reminder_loop(*, client, load_queue_schedules, build_lineup_reminder, next_queue_start, save_queue_schedules):
    await client.wait_until_ready()
    while not client.is_closed():
        now = datetime.now(timezone.utc)
        try:
            configs = load_queue_schedules()
        except JsonStoreError as exc:
            print(f"Queue reminder state is unavailable: {exc}")
            await asyncio.sleep(60)
            continue
        original_configs = deepcopy(configs)
        dirty = False
        for guild_id, config in configs.items():
            try:
                queue_start = next_queue_start(config, now)
                if not queue_start:
                    continue
                seconds_until = (queue_start.astimezone(timezone.utc) - now).total_seconds()
                local_date = queue_start.date().isoformat()
                if 0 < seconds_until <= 30 * 60 and config.get("last_reminder_date") != local_date:
                    channel_id = int(config["channel_id"])
                    channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
                    label = queue_start.strftime("%A %H:%M %Z")
                    guild = client.get_guild(int(guild_id))
                    embed, picked_user_ids, lineup_file = await build_lineup_reminder(
                        f"Queue reminder · {label}", "Queue window starts in about 30 minutes.", guild
                    )
                    mentions = " ".join(f"<@{uid}>" for uid in picked_user_ids)
                    content = "Players with agent picks:" + (f" {mentions}" if mentions else " nobody has picked an agent yet.")
                    send_args = {
                        "content": content,
                        "embed": embed,
                        "allowed_mentions": discord.AllowedMentions(users=[discord.Object(id=uid) for uid in picked_user_ids]),
                    }
                    if lineup_file:
                        send_args["file"] = lineup_file
                    await channel.send(**send_args)
                    config["last_reminder_date"] = local_date
                    dirty = True
            except (KeyError, ValueError, ZoneInfoNotFoundError, discord.DiscordException) as exc:
                print(f"Queue reminder failed for guild {guild_id}: {exc}")
        if dirty:
            try:
                latest = load_queue_schedules()
                for guild_id, updated in configs.items():
                    original = original_configs.get(guild_id)
                    current = latest.get(guild_id)
                    if not original or not current:
                        continue
                    original_schedule = {key: value for key, value in original.items() if key != "last_reminder_date"}
                    current_schedule = {key: value for key, value in current.items() if key != "last_reminder_date"}
                    if original_schedule == current_schedule:
                        current["last_reminder_date"] = updated.get("last_reminder_date")
                save_queue_schedules(latest)
            except JsonStoreError as exc:
                print(f"Could not save queue reminder state: {exc}")
        await asyncio.sleep(60)


async def play_session_loop(*, client, load_play_sessions, load_matchfeeds, load_accounts, cached_api, cached, match_detail, parse_time, play_match_image, save_play_sessions, AFFINITY):
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            sessions = load_play_sessions()
            accounts = load_accounts()
            matchfeeds = load_matchfeeds()
        except JsonStoreError as exc:
            print(f"Play session state is unavailable: {exc}")
            await asyncio.sleep(300)
            continue
        session_identities = {
            key: (session.get("owner_id"), session.get("started_at"), tuple(session.get("players", [])))
            for key, session in sessions.items()
        }
        dirty = False
        for key, session in list(sessions.items()):
            try:
                if str(session.get("guild_id")) in matchfeeds:
                    continue  # the global match feed owns auto-posts for this guild
                candidates, tracked = {}, {}
                queue_ids = {str(uid) for uid in session.get("players", [])}
                for uid, account, smurf in iter_linked_accounts(accounts):
                    if uid not in queue_ids:
                        continue
                    tracked[f"{account['name']}#{account['tag']}".casefold()] = smurf
                    region = account.get("region") or AFFINITY
                    data = await cached_api(f"/valorant/v1/stored-matches/{region}/{quote(account['name'])}/{quote(account['tag'])}",
                                            240, mode="competitive", size=10)
                    for item in data or []:
                        mid = (item.get("meta") or {}).get("id")
                        if mid:
                            candidates.setdefault(mid, {"item": item, "region": region})
                seen = set(session.get("seen", []))
                fresh = []
                for mid, candidate in candidates.items():
                    if mid in seen:
                        continue
                    started = parse_time((candidate["item"].get("meta") or {}).get("started_at"))
                    since = parse_time(session.get("started_at"))
                    seen.add(mid)
                    if started and since and started >= since:
                        fresh.append((mid, started, candidate["region"]))
                session["seen"] = list(seen)[-100:]
                session["started_at"] = session.get("started_at") or datetime.now(timezone.utc).isoformat()
                dirty = True
                channel = client.get_channel(int(session["channel_id"])) or await client.fetch_channel(int(session["channel_id"]))
                for mid, _, region in sorted(fresh, key=lambda item: item[1]):
                    detail = await cached_match_detail(cached, match_detail, mid, region)
                    participants = detail.get("players", [])
                    # Only announce matches where at least one tracked account played.
                    ours = []
                    for player in participants:
                        key = f"{player.get('name', '')}#{player.get('tag', '')}".casefold()
                        if key in tracked:
                            ours.append({**player, "is_smurf": tracked[key]})
                    if not ours:
                        continue
                    team = ours[0].get("team_id")
                    teammates = [p for p in participants if p.get("team_id") == team]
                    recap_players = [player for player in ours if player.get("team_id") == team]
                    if any(player["is_smurf"] for player in recap_players):
                        card = await play_match_image(detail, teammates, teammates, ours[0], summary_players=recap_players)
                    else:
                        card = await play_match_image(detail, teammates, teammates, ours[0])
                    await channel.send(file=card, allowed_mentions=discord.AllowedMentions.none())
            except Exception as exc:
                print(f"Play session poll failed for channel {key}: {exc}")
        if dirty:
            try:
                latest = load_play_sessions()
                for key, updated in sessions.items():
                    current = latest.get(key)
                    if not current:
                        continue
                    identity = (current.get("owner_id"), current.get("started_at"), tuple(current.get("players", [])))
                    if identity == session_identities.get(key):
                        current["seen"] = list(updated.get("seen", []))
                        current["started_at"] = updated.get("started_at")
                save_play_sessions(latest)
            except JsonStoreError as exc:
                print(f"Could not save play session state: {exc}")
        await asyncio.sleep(300)


async def matchfeed_loop(*, client, load_matchfeeds, load_accounts, load_rank_states, save_rank_states, cached_api, cached, match_detail, parse_time, play_match_image, rank_change_image, save_matchfeed_progress, AFFINITY, prepare_recap=None):
    """Poll linked accounts and post once per match when registered players appear."""
    await client.wait_until_ready()
    loop = asyncio.get_running_loop()
    while not client.is_closed():
        cycle_started = loop.time()
        try:
            feeds = load_matchfeeds()
            accounts = load_accounts()
            rank_states = load_rank_states()
        except JsonStoreError as exc:
            print(f"Match feed state is unavailable: {exc}")
            await asyncio.sleep(MATCHFEED_POLL_SECONDS)
            continue
        rank_state_updates = {}
        rank_changes = []
        try:
            if feeds and accounts:
                linked = {}
                for user_id, account, smurf in iter_linked_accounts(accounts):
                    riot_key = f"{account['name']}#{account['tag']}".casefold()
                    entry = linked.setdefault(riot_key, {"account": account, "user_ids": set(), "is_smurf": smurf})
                    entry["user_ids"].add(user_id)

                candidates = {}
                histories = {}
                rank_histories = {}
                complete_poll = True
                for index, (riot_key, entry) in enumerate(linked.items()):
                    account = entry["account"]
                    region = account.get("region") or AFFINITY
                    if index:
                        await asyncio.sleep(2.3)  # pace requests below the basic rate limit

                    try:
                        history = await cached_api(
                            f"/valorant/v1/stored-matches/{region}/{quote(account['name'])}/{quote(account['tag'])}",
                            MATCHFEED_CACHE_SECONDS, mode="competitive", size=10,
                        )
                    except Exception as exc:
                        print(f"Match feed history failed for {account['name']}#{account['tag']}: {exc}")
                        complete_poll = False
                        history = []
                    histories[riot_key] = history or []
                    for item in history or []:
                        meta = item.get("meta") or {}
                        match_id = meta.get("id")
                        started = parse_time(meta.get("started_at"))
                        if not match_id or not started:
                            continue
                        candidate = candidates.setdefault(match_id, {
                            "started": started, "region": region, "account_keys": set(),
                        })
                        candidate["account_keys"].add(riot_key)

                member_cache = {}

                async def guild_member(guild, user_id):
                    nonlocal complete_poll
                    cache_key = (guild.id, user_id)
                    if cache_key in member_cache:
                        return member_cache[cache_key]
                    member = guild.get_member(int(user_id))
                    if member is None:
                        try:
                            member = await guild.fetch_member(int(user_id))
                        except discord.NotFound:
                            member = None
                        except discord.HTTPException as exc:
                            print(f"Could not resolve match feed member {user_id} in {guild.id}: {exc}")
                            complete_poll = False
                            member = None
                    member_cache[cache_key] = member
                    return member

                for match_id, candidate in sorted(candidates.items(), key=lambda item: item[1]["started"]):
                    eligible_feeds = []
                    for guild_key, feed in feeds.items():
                        seen = {str(mid) for mid in feed.get("seen", [])}
                        since = parse_time(feed.get("started_at"))
                        if str(match_id) not in seen and since and candidate["started"] >= since:
                            eligible_feeds.append((guild_key, feed))
                    if not eligible_feeds:
                        continue

                    await asyncio.sleep(2.3)
                    try:
                        detail = await cached_match_detail(cached, match_detail, match_id, candidate["region"])
                    except Exception as exc:
                        print(f"Match feed detail failed for {match_id}: {exc}")
                        complete_poll = False
                        continue

                    team_groups = group_registered_players(detail.get("players", []), linked)

                    shared_teams = [
                        (team_id, group) for team_id, group in team_groups.items()
                        if group["account_keys"]
                    ]
                    team_records = {str(team.get("team_id")): team for team in detail.get("teams", [])}
                    map_data = (detail.get("metadata") or {}).get("map") or {}
                    map_name = map_data.get("name", "Unknown") if isinstance(map_data, dict) else str(map_data)
                    notify_targets = []
                    for guild_key, feed in eligible_feeds:
                        if not shared_teams:
                            feed["seen"] = (list(feed.get("seen", [])) + [str(match_id)])[-1000:]
                            save_matchfeed_progress(feeds, guild_key)
                            continue
                        guild = client.get_guild(int(guild_key))
                        if guild is None:
                            continue
                        channel = client.get_channel(int(feed.get("channel_id", 0)))
                        if channel is None:
                            try:
                                channel = await client.fetch_channel(int(feed["channel_id"]))
                            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
                                print(f"Could not resolve match feed channel for guild {guild_key}: {exc}")
                                complete_poll = False
                                continue

                        guild_groups = []
                        for team_id, group in shared_teams:
                            mentions, member_account_keys, discord_names = [], set(), {}
                            for riot_key in group["account_keys"]:
                                for user_id in sorted(linked[riot_key]["user_ids"]):
                                    member = await guild_member(guild, user_id)
                                    if member:
                                        member_account_keys.add(riot_key)
                                        mentions.append(user_id)
                                        display_name = getattr(member, "display_name", None)
                                        if display_name:
                                            discord_names.setdefault(riot_key, display_name)
                            if member_account_keys:
                                guild_groups.append((team_id, group, list(dict.fromkeys(mentions)),
                                                     member_account_keys, discord_names))
                        if not guild_groups:
                            feed["seen"] = (list(feed.get("seen", [])) + [str(match_id)])[-1000:]
                            save_matchfeed_progress(feeds, guild_key)
                            continue
                        guild_groups.sort(key=lambda item: (
                            len(item[1]["account_keys"]),
                            bool(team_records.get(item[0], {}).get("won")),
                        ), reverse=True)
                        team_id, group, mentions, member_account_keys, discord_names = guild_groups[0]
                        team_record = team_records.get(team_id, {})
                        rounds = team_record.get("rounds") or {}
                        score = f"{rounds.get('won', 0)}-{rounds.get('lost', 0)}"
                        result_word = "won" if team_record.get("won") else "lost"
                        all_team_players = [p for p in detail.get("players", []) if str(p.get("team_id")) == team_id]
                        registered_players = []
                        for player in group["players"]:
                            key = f"{player.get('name', '')}#{player.get('tag', '')}".casefold()
                            if key in member_account_keys:
                                registered_players.append({**player, "is_smurf": linked[key]["is_smurf"]})
                        notify_targets.append((guild_key, feed, channel, mentions, team_id,
                                               registered_players, all_team_players, result_word, score, discord_names))

                    if notify_targets:
                        started = candidate["started"]
                        duration_ms = (detail.get("metadata") or {}).get("game_length_in_ms") or 0
                        finished = started + timedelta(milliseconds=duration_ms)
                        cards_by_roster = {}
                        for guild_key, feed, channel, mentions, team_id, registered_players, all_team_players, result_word, score, discord_names in notify_targets:
                            try:
                                tone = normalize_tone(feed.get("tone"))
                                for player in registered_players:
                                    key = f"{player['name']}#{player['tag']}".casefold()
                                    if key in rank_histories:
                                        continue
                                    account = linked[key]["account"]
                                    region = account.get("region") or AFFINITY
                                    await asyncio.sleep(2.3)
                                    try:
                                        rank_history = await cached_api(
                                            f"/valorant/v1/mmr-history/{region}/{quote(account['name'])}/{quote(account['tag'])}",
                                            MATCHFEED_CACHE_SECONDS,
                                        )
                                        rank_histories[key] = rank_history if isinstance(rank_history, list) else []
                                    except Exception as exc:
                                        print(f"Match feed rank history failed for {account['name']}#{account['tag']}: {exc}")
                                        rank_histories[key] = []
                                recap_context = matchfeed_recap_context(
                                    registered_players, match_id, started, finished, histories, rank_histories,
                                )
                                counts, footer = next_matchfeed_counts(
                                    feed, registered_players, match_id, started, finished,
                                    recap_match=session_match(detail, registered_players, match_id, started, finished, recap_context, rank_histories),
                                )
                                roster_key = (team_id, tuple(p.get("puuid") for p in registered_players),
                                              tone, footer, tuple(sorted(discord_names.items())))
                                if roster_key not in cards_by_roster:
                                    card = await play_match_image(detail, registered_players, all_team_players,
                                                                  registered_players[0], summary_players=registered_players,
                                                                  tone=tone, footer=footer, recap_context=recap_context,
                                                                  discord_names=discord_names)
                                    cards_by_roster[roster_key] = card.fp.getvalue()
                                await channel.send(
                                    content=format_match_notification(
                                        mentions, result_word, score, map_name
                                    ),
                                    file=discord.File(io.BytesIO(cards_by_roster[roster_key]), filename="match.png"),
                                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                                )
                            except discord.HTTPException as exc:
                                print(f"Could not post match feed {match_id} in guild {guild_key}: {exc}")
                                complete_poll = False
                                continue
                            feed["match_counts"] = counts
                            feed["seen"] = (list(feed.get("seen", [])) + [str(match_id)])[-1000:]
                            save_matchfeed_progress(feeds, guild_key)

                if complete_poll:
                    await post_session_recaps(
                        client=client, feeds=feeds, load_matchfeeds=load_matchfeeds,
                        save_matchfeed_progress=save_matchfeed_progress,
                        prepare_recap=prepare_recap,
                    )

                # Let completed match posts and session recaps go out before checking current ranks.
                for riot_key, entry in linked.items():
                    account = entry["account"]
                    region = account.get("region") or AFFINITY
                    await asyncio.sleep(2.3)
                    try:
                        rank_data = await cached_api(
                            f"/valorant/v3/mmr/{region}/pc/{quote(account['name'])}/{quote(account['tag'])}",
                            MATCHFEED_CACHE_SECONDS,
                        )
                        current = (rank_data.get("current") or {}) if isinstance(rank_data, dict) else {}
                        tier = current.get("tier") or {}
                        if not tier:
                            raise ValueError("Rank response did not include a current tier")
                        tier_id = int(tier.get("id") or 0)
                        tier_name = tier.get("name") or "Unrated"
                        previous = rank_states.get(riot_key)
                        if previous is not None and int(previous.get("tier_id") or 0) != tier_id:
                            rank_changes.append({
                                "riot_key": riot_key,
                                "user_ids": sorted(entry["user_ids"]),
                                "name": account["name"],
                                "from_id": int(previous.get("tier_id") or 0),
                                "from_name": previous.get("tier_name") or "Unrated",
                                "to_id": tier_id,
                                "to_name": tier_name,
                                "direction": "up" if tier_id > int(previous.get("tier_id") or 0) else "down",
                                "from_rr": previous.get("rr"),
                                "to_rr": current.get("rr"),
                                "rr_change": current.get("last_change"),
                            })
                        updated_rank = {
                            "tier_id": tier_id, "tier_name": tier_name, "rr": current.get("rr")
                        }
                        if updated_rank != previous:
                            rank_state_updates[riot_key] = updated_rank
                    except Exception as exc:
                        print(f"Match feed rank check failed for {account['name']}#{account['tag']}: {exc}")

                for event in rank_changes:
                    try:
                        card = await rank_change_image(
                            event["name"], event["from_id"], event["from_name"],
                            event["to_id"], event["to_name"], event["direction"],
                            event["from_rr"], event["to_rr"], event["rr_change"],
                        )
                        image_bytes = card.fp.getvalue()
                    except Exception as exc:
                        print(f"Could not render rank change card for {event['name']}: {exc}")
                        continue
                    for guild_key, feed in feeds.items():
                        guild = client.get_guild(int(guild_key))
                        if guild is None:
                            continue
                        matching_users = []
                        for user_id in event["user_ids"]:
                            if await guild_member(guild, user_id):
                                matching_users.append(user_id)
                        if not matching_users:
                            continue
                        channel = client.get_channel(int(feed.get("channel_id", 0)))
                        if channel is None:
                            try:
                                channel = await client.fetch_channel(int(feed["channel_id"]))
                            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
                                print(f"Could not resolve rank feed channel for guild {guild_key}: {exc}")
                                continue
                        direction_text = "ranked up" if event["direction"] == "up" else "deranked"
                        mention_text = " ".join(f"<@{user_id}>" for user_id in matching_users)
                        try:
                            await channel.send(
                                content=f"{mention_text} {direction_text}!",
                                file=discord.File(io.BytesIO(image_bytes), filename="rank-change.png"),
                                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                            )
                        except discord.HTTPException as exc:
                            print(f"Could not post rank change for {event['name']} in guild {guild_key}: {exc}")
                if rank_state_updates:
                    rank_states.update(rank_state_updates)
                    save_rank_states(rank_states)
        except Exception as exc:
            print(f"Match feed poll failed: {exc}")
        await asyncio.sleep(max(1, MATCHFEED_POLL_SECONDS - (loop.time() - cycle_started)))
