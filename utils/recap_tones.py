"""Shared matchfeed recap tone choices and prompt instructions."""

DEFAULT_TONE = "constructive"
TONE_LABELS = {"no_filter": "No filter", "kind": "Kind", "harsh": "Harsh", "constructive": "Constructive"}
TONE_PROMPTS = {
    "no_filter": ("This is profane, savage banter between adult friends. Make the recap thoroughly rude: "
                  "use several uncensored swear words throughout, including fuck, fucking, shit and arse. "
                  "Mercilessly roast poor performances with creative insults based on actual stats. "
                  "Call strong performers sweaty bastards or tryhards."),
    "kind": "Be warm, encouraging and positive. Avoid profanity, insults and mocking players.",
    "harsh": "Be blunt and sharply critical of poor performances, with dry competitive banter. Avoid profanity.",
    "constructive": ("Be respectful, balanced and specific. Identify strengths and areas to improve using the "
                     "available stats; give actionable suggestions without inventing what happened. Avoid profanity."),
}


def normalize_tone(tone):
    return tone if tone in TONE_PROMPTS else DEFAULT_TONE
