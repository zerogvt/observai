"""Per-task prompt construction.

The gateway forwards a `task` (summarize / chat / classify / extract) and the
user `input`. We turn that into a system prompt + user message for the model.
Keeping this in one place makes prompts easy to version and review — which
matters for the transparency side of the project (you can always show exactly
what instruction produced a given output).
"""

SYSTEM_PROMPTS = {
    "summarize": (
        "You are a concise summarization assistant. Summarize the user's text "
        "in a few clear sentences. Preserve key facts; do not invent details."
    ),
    "chat": (
        "You are a helpful, honest assistant. Answer the user clearly and "
        "concisely. If you are unsure, say so rather than guessing."
    ),
    "classify": (
        "You are a classification assistant. Read the user's text and assign "
        "the single most appropriate category. Respond with only the category "
        "label and a one-line justification."
    ),
    "extract": (
        "You are an information-extraction assistant. Extract the key entities "
        "and facts from the user's text as a short bullet list. Do not add "
        "information that is not present in the text."
    ),
}

DEFAULT_SYSTEM = "You are a helpful assistant."


def build_messages(task: str, input_text: str, options: dict):
    """Return (system_prompt, messages[]) for an Ollama chat call.

    `options` can carry per-task hints (e.g. {"max_words": 50} for summarize),
    which we fold into the system prompt so the behavior is explicit.
    """
    system = SYSTEM_PROMPTS.get(task, DEFAULT_SYSTEM)

    if task == "summarize" and isinstance(options.get("max_words"), int):
        system += f" Keep the summary under {options['max_words']} words."
    if task == "classify" and isinstance(options.get("labels"), list):
        labels = ", ".join(str(x) for x in options["labels"])
        system += f" Choose only from these categories: {labels}."

    messages = [{"role": "user", "content": input_text}]
    return system, messages
