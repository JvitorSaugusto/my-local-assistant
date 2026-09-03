import re


HEAVY_TAG_PATTERN = re.compile(r"(?<!\S)@heavy(?!\S)", re.IGNORECASE)
TAG_LOOKAHEAD_CHARS = 30
ENHANCER_TAG_PATTERN = re.compile(r"(?<!\S)@enhancer(?!\S)", re.IGNORECASE)


def detect_explicit_route(text: str) -> str | None:
    lookahead_zone = text[:TAG_LOOKAHEAD_CHARS]

    if HEAVY_TAG_PATTERN.search(lookahead_zone):
        return "HEAVY"
    
    if ENHANCER_TAG_PATTERN.search(lookahead_zone):
        return "ENHANCER"

    return None

def strip_leading_heavy_tag(text: str) -> str:
    lookahead_zone = text[:TAG_LOOKAHEAD_CHARS]
    match = HEAVY_TAG_PATTERN.search(lookahead_zone)
    if not match:
        return text
    start, end = match.span()
    return (text[:start] + text[end:]).strip()

def strip_leading_enhancer_tag(text: str) -> str:
    lookahead_zone = text[:TAG_LOOKAHEAD_CHARS]
    match = ENHANCER_TAG_PATTERN.search(lookahead_zone)
    if not match:
        return text
    start, end = match.span()
    return (text[:start] + text[end:]).strip()