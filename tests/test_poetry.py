"""Independent edition excerpts and deterministic local-day bilingual selection."""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from inkage.config import parse_config
from inkage.run import context_for


def poem(day=13, language="mixed", hour=8):
    sc = parse_config({"sources": {"poetry": {"panels": ["250x122-bw"], "language": language}}}).sources[0]
    now = datetime(2026, 10, day, hour, tzinfo=ZoneInfo("Asia/Singapore"))
    return asyncio.run(sc.cls().fetch(context_for(sc, now)))


def test_mixed_days_alternate_complete_authentic_poems():
    # Oct 13/14/15/16 is a fixed calendar oracle, not recomputed from selection logic.
    assert [(poem(day)["title"], poem(day)["language"]) for day in range(13, 17)] == [
        ("Rain", "en"),
        ("静夜思", "zh"),
        ("Happy Thought", "en"),
        ("登鹳雀楼", "zh"),
    ]


def test_stevenson_full_poem_matches_1905_edition():
    # Project Gutenberg #25609, Happy Thought, p. 28; both lines constitute the entire poem.
    data = poem(day=15, language="mixed")
    assert (data["author"], data["lines"], data["source"]) == (
        "Robert Louis Stevenson",
        ["The world is so full of a number of things,", "I'm sure we should all be as happy as kings."],
        "https://www.gutenberg.org/cache/epub/25609/pg25609-images.html#HAPPY_THOUGHT",
    )


def test_tang_full_poem_matches_named_edition():
    # 唐诗三百首 version of 静夜思 (other historical editions use different wording).
    data = poem(day=14)
    assert (data["author"], data["lines"], data["edition"]) == (
        "李白",
        ["床前明月光，", "疑是地上霜。", "举头望明月，", "低头思故乡。"],
        "唐诗三百首 · Simplified Chinese transcription",
    )


@pytest.mark.parametrize("language", ["en", "zh"])
def test_language_filter_and_reruns(language):
    data = poem(language=language)
    assert data == poem(language=language, hour=23)
    assert {poem(day=day, language=language)["language"] for day in range(13, 19)} == {language}


def test_unknown_language_is_explicit_error():
    with pytest.raises(ValueError, match="language must be"):
        poem(language="fr")


def test_rotation_changes_at_configured_local_midnight():
    sc = parse_config({"sources": {"poetry": {"panels": ["250x122-bw"], "timezone": "Asia/Singapore"}}}).sources[0]
    titles = []
    for hour, minute in ((15, 59), (16, 0)):
        now = datetime(2026, 10, 13, hour, minute, tzinfo=ZoneInfo("UTC"))
        titles.append(asyncio.run(sc.cls().fetch(context_for(sc, now)))["title"])
    assert titles == ["Rain", "静夜思"]
