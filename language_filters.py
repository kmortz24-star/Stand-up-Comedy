"""Conservative source-language checks for movie, TV and YouTube catalogs.

An unknown language is NOT evidence of English audio: it stays eligible while
language backfill/review runs. The report explicitly counts unknowns.
"""
from __future__ import annotations
from collections import defaultdict
import unicodedata


def language_code(value) -> str:
    """Recognize ISO-style English codes such as en / en-US / en_GB."""
    if not isinstance(value, str):
        return ""
    value = value.strip().casefold().replace("_", "-")
    return value.split("-", 1)[0]


def explicitly_non_english(record: dict, *, fields=("original_language",)) -> bool:
    for field in fields:
        raw = language_code(record.get(field))
        if raw:
            return raw not in {"en", "eng"}
    return False


def performer_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return " ".join("".join(char for char in value if not unicodedata.combining(char)).split())


def performer_non_english_evidence(records: list[dict]) -> set[str]:
    """Use independent language metadata for the same comic, not their name/country.

    If a performer has *any* English-language special, do not infer a language
    for their untagged performances (bilingual comedians need individual checks).
    """
    languages = defaultdict(set)
    for r in records:
        key = performer_key(r.get("performer"))
        lang = language_code(r.get("original_language"))
        if key and lang:
            languages[key].add(lang)
    return {name for name, codes in languages.items()
            if codes and "en" not in codes and "eng" not in codes}


def movie_allowed(record: dict, english_only: bool, non_english_performers=frozenset()) -> bool:
    if not english_only:
        return True
    lang = language_code(record.get("original_language"))
    if lang:
        return lang in {"en", "eng"}
    return performer_key(record.get("performer")) not in non_english_performers


def youtube_allowed(video: dict, english_only: bool) -> bool:
    if not english_only:
        return True
    # Actual audio language outranks metadata/title language if both are given.
    for field in ("audio_language", "default_audio_language", "language", "default_language"):
        lang = language_code(video.get(field))
        if lang:
            return lang in {"en", "eng"}
    return True  # Unverified: no language metadata available in this upload.
