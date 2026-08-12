import json

CONFIDENCE_ALIASES: dict[str, float] = {
    "high": 0.9,
    "medium": 0.6,
    "low": 0.3,
}


def normalize_llm_json_text(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        return normalized

    fenced = _extract_fenced_block(normalized)
    if fenced is not None:
        normalized = fenced.strip()

    start_index = _first_json_start_index(normalized)
    if start_index is None:
        return normalized

    candidate = normalized[start_index:]
    try:
        _, end_index = json.JSONDecoder().raw_decode(candidate)
    except json.JSONDecodeError:
        return normalized
    return candidate[:end_index]


def _extract_fenced_block(text: str) -> str | None:
    if not text.startswith("```"):
        return None

    lines = text.splitlines()
    if len(lines) < 3 or lines[-1].strip() != "```":
        return None
    return "\n".join(lines[1:-1])


def _first_json_start_index(text: str) -> int | None:
    object_index = text.find("{")
    array_index = text.find("[")
    if object_index == -1 and array_index == -1:
        return None
    if object_index == -1:
        return array_index
    if array_index == -1:
        return object_index
    return min(object_index, array_index)


def coerce_llm_confidence(value: object) -> object:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in CONFIDENCE_ALIASES:
            return CONFIDENCE_ALIASES[normalized]
    return value


def coerce_string_tuple(value: object) -> object:
    if value is None:
        return ()
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return ()
        return (normalized,)
    # Some models (e.g. gemini-2.5-flash) emit `{}` or `{"flag": "..."}` for
    # list-typed fields; keep the keys so real flags still surface.
    if isinstance(value, dict):
        return tuple(str(key) for key in value)
    return value
