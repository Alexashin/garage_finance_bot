from __future__ import annotations


def parse_amount(text: str) -> int | None:
    """Accepts integer rubles. Allows spaces and + sign."""
    if not text:
        return None
    cleaned = text.strip().replace(" ", "")
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]
    if not cleaned.isdigit():
        return None
    val = int(cleaned)
    if val <= 0:
        return None
    return val
