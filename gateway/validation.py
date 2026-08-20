"""Incoming request validation.

Kept separate from the route handler so it's easy to unit-test and so the
handler stays readable. Returns a cleaned payload or raises ValidationError.
"""
from dataclasses import dataclass

from config import Config


class ValidationError(Exception):
    """Raised when an incoming /prompt payload is malformed."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class PromptRequest:
    task: str
    input_text: str
    # Free-form per-task options (e.g. {"max_words": 100} for summarize).
    options: dict


def validate_prompt(payload) -> PromptRequest:
    """Validate and normalize an incoming /prompt body.

    Expected shape:
        {
          "task": "summarize",
          "input": "some text ...",
          "options": { ... }      # optional
        }
    """
    if not isinstance(payload, dict):
        raise ValidationError("Body must be a JSON object.")

    task = payload.get("task")
    if not isinstance(task, str) or not task.strip():
        raise ValidationError("Field 'task' is required and must be a non-empty string.")
    task = task.strip().lower()
    if task not in Config.ALLOWED_TASKS:
        raise ValidationError(
            f"Unsupported task '{task}'. Allowed: {sorted(Config.ALLOWED_TASKS)}."
        )

    text = payload.get("input")
    if not isinstance(text, str) or not text.strip():
        raise ValidationError("Field 'input' is required and must be a non-empty string.")
    if len(text) > Config.MAX_INPUT_CHARS:
        raise ValidationError(
            f"Input too long: {len(text)} chars (max {Config.MAX_INPUT_CHARS})."
        )

    options = payload.get("options", {})
    if not isinstance(options, dict):
        raise ValidationError("Field 'options' must be an object if provided.")

    return PromptRequest(task=task, input_text=text, options=options)
