"""Unit tests for prompts.build_messages — pure function, no I/O."""
from prompts import build_messages, SYSTEM_PROMPTS, DEFAULT_SYSTEM


def test_known_task_uses_its_system_prompt():
    system, _ = build_messages("summarize", "some text", {})
    assert system.startswith(SYSTEM_PROMPTS["summarize"])


def test_unknown_task_falls_back_to_default():
    system, _ = build_messages("translate", "some text", {})
    assert system == DEFAULT_SYSTEM


def test_user_input_is_carried_into_messages():
    _, messages = build_messages("chat", "hello world", {})
    assert messages == [{"role": "user", "content": "hello world"}]


def test_summarize_max_words_option_folded_into_system():
    system, _ = build_messages("summarize", "text", {"max_words": 50})
    assert "under 50 words" in system


def test_summarize_ignores_non_int_max_words():
    system, _ = build_messages("summarize", "text", {"max_words": "fifty"})
    assert "words" not in system.replace(SYSTEM_PROMPTS["summarize"], "")


def test_classify_labels_option_folded_into_system():
    system, _ = build_messages("classify", "text", {"labels": ["spam", "ham"]})
    assert "spam, ham" in system
