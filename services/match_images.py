"""Load assets and render match and rank announcement images."""

import asyncio

import discord


async def play_match_image(detail, queued_players, all_teammates, representative, summary_players=None, tone="no_filter", *, map_background_path, icon_maps, icon_img, session, api_key, model, generate_recap, draw_play_result):
    map_data = (detail.get("metadata", {}).get("map") or {})
    map_uuid = map_data.get("id") or map_data.get("uuid")
    map_name = map_data.get("name", "Unknown")
    path = await map_background_path(map_uuid, map_name) if map_uuid else None
    raw_agents = [p.get("agent") or p.get("character") or {} for p in queued_players]
    needs_catalog = any(
        not ((agent.get("id") or agent.get("uuid")) if isinstance(agent, dict) else "")
        for agent in raw_agents
    )
    catalog = {}
    if needs_catalog:
        try:
            catalog = await icon_maps()
        except Exception as exc:
            print(f"Agent catalog unavailable; loading by player agent IDs: {exc}")
    ids_by_name = {name.casefold(): agent_id for agent_id, name in catalog.get("agent_names", {}).items()}
    icon_jobs = {}
    agent_names_by_puuid = {}
    for player in queued_players:
        agent_obj = player.get("agent") or player.get("character") or {}
        if isinstance(agent_obj, dict):
            agent_name = agent_obj.get("name") or agent_obj.get("display_name") or agent_obj.get("displayName") or ""
            raw_agent_id = agent_obj.get("id") or agent_obj.get("uuid") or ""
        else:
            agent_name, raw_agent_id = str(agent_obj), ""
        agent_id = str(raw_agent_id).lower()
        if agent_id not in catalog.get("agents", {}):
            agent_id = ids_by_name.get(agent_name.casefold(), agent_id)
        direct_icon_url = f"https://media.valorant-api.com/agents/{agent_id}/displayicon.png" if agent_id else None
        icon_urls = ([
            direct_icon_url,
            f"https://media.valorant-api.com/agents/{agent_id}/bustportrait.png",
            f"https://media.valorant-api.com/agents/{agent_id}/killfeedportrait.png",
        ] if direct_icon_url else [])
        icon_urls.extend(catalog.get("agent_icon_urls", {}).get(agent_id) or [catalog.get("agents", {}).get(agent_id)])
        icon_urls = list(dict.fromkeys(url for url in icon_urls if url))
        puuid = player.get("puuid")
        if icon_urls and puuid:
            agent_names_by_puuid[puuid] = agent_name
            async def fetch_agent_icon(urls=icon_urls):
                for url in urls:
                    image = await icon_img(url, 96)
                    if image is not None:
                        return image
                return None
            icon_jobs[puuid] = fetch_agent_icon()
    loaded = await asyncio.gather(*icon_jobs.values()) if icon_jobs else []
    icons_by_puuid = dict(zip(icon_jobs, loaded))
    missing = [agent_names_by_puuid[puuid] for puuid, icon in icons_by_puuid.items() if icon is None]
    if missing:
        print("Agent art unavailable for match card: " + ", ".join(missing))
    # Keep rendering input local; API response objects remain unchanged.
    render_players = [dict(p, _play_icon=icons_by_puuid.get(p.get("puuid"))) for p in queued_players]
    loop = asyncio.get_running_loop()
    focus = summary_players if summary_players is not None else all_teammates
    recap = await generate_recap(session, api_key, model,
                                 detail, focus, representative, registered_only=summary_players is not None, tone=tone)
    buffer = await loop.run_in_executor(None, draw_play_result, detail, render_players, all_teammates,
                                        representative, path, recap, summary_players, tone)
    return discord.File(buffer, filename="match.png")


async def rank_change_image(player_name, from_id, from_name, to_id, to_name, direction,
                            from_rr=None, to_rr=None, rr_change=None, *, icon_maps, icon_img, draw_rank_change_card):
    """Build a rank-change card in the same dark, coral-accented style as match cards."""
    try:
        tier_icons = (await icon_maps()).get("tiers", {})
    except Exception as exc:
        print(f"Rank icon catalog unavailable: {exc}")
        tier_icons = {}
    old_icon, new_icon = await asyncio.gather(
        icon_img(tier_icons.get(str(from_id)), 132),
        icon_img(tier_icons.get(str(to_id)), 132),
    )
    loop = asyncio.get_running_loop()
    buffer = await loop.run_in_executor(
        None, draw_rank_change_card, player_name, from_name, to_name, direction, old_icon, new_icon,
        from_rr, to_rr, rr_change
    )
    return discord.File(buffer, filename="rank-change.png")
