import re


HEAVY_TAG_PATTERN = re.compile(
    r"(?<!\S)@heavy(?!\S)",
    re.IGNORECASE,
)

ENHANCER_TAG_PATTERN = re.compile(
    r"(?<!\S)@enhance(?!\S)",
    re.IGNORECASE,
)

TAG_LOOKAHEAD_CHARS = 50


def detect_explicit_route(text: str) -> str | None:
    lookahead_zone = text[:TAG_LOOKAHEAD_CHARS]

    has_heavy = bool(
        HEAVY_TAG_PATTERN.search(lookahead_zone)
    )

    has_enhancer = bool(
        ENHANCER_TAG_PATTERN.search(lookahead_zone)
    )

    if has_heavy and has_enhancer:
        return "ENHANCER_HEAVY"

    if has_heavy:
        return "HEAVY"

    if has_enhancer:
        return "ENHANCER"

    return None


def strip_leading_tags(text: str) -> str:
    lookahead_zone = text[:TAG_LOOKAHEAD_CHARS]

    cleaned = HEAVY_TAG_PATTERN.sub(
        "",
        lookahead_zone,
        count=1,
    )

    cleaned = ENHANCER_TAG_PATTERN.sub(
        "",
        cleaned,
        count=1,
    )

    return (
        text[:TAG_LOOKAHEAD_CHARS]
        .replace(lookahead_zone, cleaned)
        + text[TAG_LOOKAHEAD_CHARS:]
    ).strip()