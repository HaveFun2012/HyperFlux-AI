"""Decide how a chat message is handled: web search, math, or plain model chat."""

import re

SEARCH_TRIGGERS = [
    "who won", "latest", "current", "news", "what happened",
    "price", "prime minister", "who is", "update", "patch", "drivers",
    "weather", "today", "yesterday", "this week", "this month",
    "in 2026", "right now", "currently", "how bout in",
]

_CODE_WORDS = re.compile(
    r"\b(?:def|import|class|function|stdout|stderr|traceback|stack trace|"
    r"syntax error|compiler|compile|debugger|pip install|markdown|script|"
    r"code block|while|for _)\b"
)
_CODING_REQUEST = re.compile(
    r"\b(?:how do i|how to|help me)\b.*"
    r"\b(?:write|code|implement|debug|fix|create|build)\b.*"
    r"\b(?:python|script|function|loop|class|program|code)\b"
)
_MATH_WORDS = re.compile(
    r"\b(?:math|mathematics|probability|fraction|equation|algebra|"
    r"numerator|denominator|divided by|multiplied by|plus|minus|"
    r"times|square root)\b"
)


def is_search_intent(low_input):
    """True when a (lower-cased) message asks about current events.

    Coding prompts stay on the local model, even when they mention current
    events or include an explicit search prefix.
    """
    code_indicators = _CODE_WORDS.search(low_input)
    has_code_tokens = bool(code_indicators) or any(
        token in low_input for token in ("{", "}", "```")
    )
    coding_request = bool(code_indicators) or bool(_CODING_REQUEST.search(low_input))
    if has_code_tokens or coding_request:
        return False
    explicit_search = low_input.startswith(("search:", "web:", "/search "))
    return explicit_search or any(
        re.search(rf"\b{re.escape(trigger)}\b", low_input)
        for trigger in SEARCH_TRIGGERS
    )


def looks_like_arithmetic(low_input):
    return any(c in low_input for c in "+-*/=") and any(c.isdigit() for c in low_input)


def is_math_request(low_input):
    return bool(_MATH_WORDS.search(low_input))


def brain_lookup(local_brain, low_input):
    """Return a canned answer from the local brain whose key loosely matches the message."""
    clean_term = (
        low_input.replace("what is", "").replace("who is", "").replace("tell me about", "")
        .strip("?!. ")
    )
    for key in local_brain:
        if key in clean_term or clean_term in key:
            return local_brain[key]
    return None
