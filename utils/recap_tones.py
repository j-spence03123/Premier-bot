"""Shared matchfeed recap tone choices and prompt instructions."""

DEFAULT_TONE = "constructive"
TONE_LABELS = {"no_filter": "No filter", "kind": "Kind", "harsh": "Harsh", "constructive": "Constructive"}
TONE_PROMPTS = {
    "no_filter": ("Use the voice of an adult teammate who can be profane and merciless about the game. "
                  "Let the specific play set up the roast. Swear when it lands."),
    "kind": "Be warm, encouraging and positive. Avoid profanity, insults and mocking players.",
    "harsh": "Be blunt and sharply critical of poor performances, with dry competitive banter. Avoid profanity.",
    "constructive": ("Be respectful, balanced and specific. Identify strengths and areas to improve using the "
                     "available stats; give actionable suggestions without inventing what happened. Avoid profanity."),
}


def normalize_tone(tone):
    return tone if tone in TONE_PROMPTS else DEFAULT_TONE
