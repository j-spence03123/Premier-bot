"""Riot account identifier parsing."""


def split_riot_id(text):
    name, sep, tag = (text or "").strip().rpartition("#")
    return (name.strip(), tag.strip()) if sep and name.strip() and tag.strip() else None
