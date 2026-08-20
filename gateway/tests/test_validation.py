"""Unit tests for validate_prompt — pure function, no I/O."""
import pytest

from validation import validate_prompt, ValidationError, PromptRequest


def test_valid_payload_returns_prompt_request():
    req = validate_prompt({"task": "summarize", "input": "some text", "options": {"max_words": 50}})
    assert isinstance(req, PromptRequest)
    assert req.task == "summarize"
    assert req.input_text == "some text"
    assert req.options == {"max_words": 50}


def test_task_is_normalized_to_lowercase_and_trimmed():
    req = validate_prompt({"task": "  SUMMARIZE  ", "input": "x"})
    assert req.task == "summarize"


def test_options_defaults_to_empty_dict_when_absent():
    req = validate_prompt({"task": "chat", "input": "hi"})
    assert req.options == {}


def test_non_dict_payload_rejected():
    with pytest.raises(ValidationError):
        validate_prompt("not a dict")


def test_none_payload_rejected():
    # request.get_json(silent=True) returns None on a bad/empty body.
    with pytest.raises(ValidationError):
        validate_prompt(None)


@pytest.mark.parametrize("bad_task", [None, "", "   ", 123, ["chat"]])
def test_missing_or_bad_task_rejected(bad_task):
    with pytest.raises(ValidationError):
        validate_prompt({"task": bad_task, "input": "x"})


def test_disallowed_task_rejected():
    with pytest.raises(ValidationError):
        validate_prompt({"task": "translate", "input": "x"})


@pytest.mark.parametrize("bad_input", [None, "", "   ", 123, {"a": 1}])
def test_missing_or_bad_input_rejected(bad_input):
    with pytest.raises(ValidationError):
        validate_prompt({"task": "chat", "input": bad_input})


def test_too_long_input_rejected():
    from config import Config

    too_long = "a" * (Config.MAX_INPUT_CHARS + 1)
    with pytest.raises(ValidationError):
        validate_prompt({"task": "chat", "input": too_long})


def test_non_dict_options_rejected():
    with pytest.raises(ValidationError):
        validate_prompt({"task": "chat", "input": "x", "options": ["not", "a", "dict"]})


def test_validation_error_carries_message():
    try:
        validate_prompt({"task": "chat"})  # missing input
    except ValidationError as e:
        assert e.message  # non-empty, human-readable
    else:
        pytest.fail("expected ValidationError")
