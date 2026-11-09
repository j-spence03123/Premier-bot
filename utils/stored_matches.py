"""Parse stored match data for player histories."""


def parse_stored(m):
    """One entry of the stored-matches endpoint (same parsing as the tracker app)."""
    meta, s, teams = m.get("meta", {}), m.get("stats", {}), m.get("teams", {})
    team = str(s.get("team", "")).lower()
    won, score = None, ""
    if team in ("red", "blue") and "red" in teams and "blue" in teams:
        other = "blue" if team == "red" else "red"
        score = f"{teams[team]}-{teams[other]}"
        won = None if teams[team] == teams[other] else teams[team] > teams[other]
    shots, dmg = s.get("shots", {}), s.get("damage", {})
    rounds = max((teams.get("red") or 0) + (teams.get("blue") or 0), 1)
    total_shots = sum(shots.get(k, 0) for k in ("head", "body", "leg"))
    return {
        "started": meta.get("started_at"),
        "map": (meta.get("map") or {}).get("name", "?"),
        "agent": (s.get("character") or {}).get("name", "?"),
        "agent_id": str((s.get("character") or {}).get("id") or (s.get("character") or {}).get("uuid") or "").lower(),
        "k": s.get("kills", 0),
        "d": s.get("deaths", 0),
        "a": s.get("assists", 0),
        "won": won,
        "score": score,
        "acs": round(s.get("score", 0) / rounds),
        "adr": round(dmg.get("made", 0) / rounds),
        "hs": round(100 * shots.get("head", 0) / total_shots) if total_shots else 0,
    }
