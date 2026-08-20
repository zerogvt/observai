"""Conversation state for the load generator.

The gateway/inference services are stateless (each request is independent), so
to simulate an ongoing chat we keep the transcript here and feed a windowed
version back as context on each turn. Follow-up messages are drawn from simple
pools — enough to produce varied, continuous, conversational load without
needing a model on this side to invent them.
"""
import random

# Conversation starters — a new conversation begins with one of these.
OPENERS = [
    "Explain how DNS resolution works, step by step.",
    "What's the difference between TCP and UDP?",
    "Summarize the CAP theorem in plain terms.",
    "How does a Kubernetes readiness probe differ from a liveness probe?",
    "What is OpenTelemetry and what problem does it solve?",
    "Explain the idea behind distributed tracing.",
    "What are the tradeoffs between SQL and NoSQL databases?",
    "How does TLS establish a secure connection?",
    "What is a service mesh and when would you use one?",
    "Explain eventual consistency with an example.",
]

# Follow-ups — used once a conversation is under way, to keep it going.
FOLLOWUPS = [
    "Can you elaborate on that?",
    "Why is that the case?",
    "Give me a concrete example.",
    "What are the common pitfalls?",
    "How would that behave under heavy load?",
    "What's a simpler way to explain it?",
    "How does that relate to observability?",
    "What would you monitor to catch problems here?",
    "Are there any security implications?",
    "Summarize what we've covered so far.",
]


class Conversation:
    def __init__(self, history_turns: int, max_input_chars: int):
        self.history_turns = history_turns
        self.max_input_chars = max_input_chars
        self.turns = []       # list of (role, text)
        self.user_turns = 0

    def reset(self):
        self.turns = []
        self.user_turns = 0

    def next_user_message(self) -> str:
        return random.choice(OPENERS if not self.turns else FOLLOWUPS)

    def render_input(self, user_message: str) -> str:
        """Build the transcript to send: a window of recent turns + the new
        user message. Trimmed from the front to stay under the char cap."""
        window = self.turns[-(self.history_turns * 2):]
        lines = [f"{role}: {text}" for role, text in window]
        lines.append(f"user: {user_message}")
        transcript = "\n".join(lines)
        if len(transcript) > self.max_input_chars:
            transcript = transcript[-self.max_input_chars:]
        return transcript

    def record(self, role: str, text: str):
        self.turns.append((role, text))
        if role == "user":
            self.user_turns += 1
