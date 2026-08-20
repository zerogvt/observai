"""Load generator.

Runs an endless loop: every ~INTERVAL_SECONDS it sends the next turn of an
ongoing conversation to the target (the gateway by default), records the reply
as context for the next turn, and logs a one-line summary. Shuts down cleanly
on SIGINT/SIGTERM.

It is NOT an HTTP server — it produces traffic rather than serving it. Scale
load by lowering INTERVAL_SECONDS or running more replicas.
"""
import logging
import random
import signal
import threading
import time

import requests

from config import Config
from conversation import Conversation

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("loadgen")

_stop = threading.Event()


def _handle_signal(signum, _frame):
    log.info("received signal %s — stopping after the current cycle", signum)
    _stop.set()


def _extract_output(payload) -> str:
    """Pull the assistant text out of either shape:
    gateway  -> {"result": {"output": ...}}
    inference -> {"output": ...}
    """
    if not isinstance(payload, dict):
        return ""
    if isinstance(payload.get("result"), dict):
        return payload["result"].get("output", "") or ""
    return payload.get("output", "") or ""


def main():
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    convo = Conversation(Config.HISTORY_TURNS, Config.MAX_INPUT_CHARS)
    session = requests.Session()
    turn = 0

    log.info(
        "loadgen starting: target=%s task=%s interval=%.0fs(+<=%.0fs jitter)",
        Config.TARGET_URL, Config.TASK, Config.INTERVAL_SECONDS, Config.INTERVAL_JITTER_SECONDS,
    )

    while not _stop.is_set():
        turn += 1
        user_msg = convo.next_user_message()
        input_text = convo.render_input(user_msg)
        convo.record("user", user_msg)
        request_id = f"loadgen-{int(time.time())}-{turn}"

        try:
            t0 = time.perf_counter()
            resp = session.post(
                Config.TARGET_URL,
                json={"task": Config.TASK, "input": input_text},
                headers={"X-Request-ID": request_id},
                timeout=Config.REQUEST_TIMEOUT_S,
            )
            latency_ms = (time.perf_counter() - t0) * 1000.0

            if resp.status_code == 200:
                data = resp.json()
                output = _extract_output(data)
                convo.record("assistant", output)
                result = data.get("result", data) if isinstance(data, dict) else {}
                tokens_out = result.get("tokens_out") if isinstance(result, dict) else None
                flagged = (data.get("oversight") or {}).get("flagged") if isinstance(data, dict) else None
                log.info(
                    "turn=%d status=200 lat_ms=%.0f in_chars=%d out_chars=%d tokens_out=%s flagged=%s msg=%r",
                    turn, latency_ms, len(input_text), len(output), tokens_out, flagged, user_msg,
                )
                if Config.LOG_RESPONSES:
                    reply = " ".join(output.split())  # collapse newlines to keep one line/turn
                    if len(reply) > Config.RESPONSE_LOG_CHARS:
                        reply = reply[: Config.RESPONSE_LOG_CHARS] + "…"
                    log.info("turn=%d  USER:      %s", turn, user_msg)
                    log.info("turn=%d  ASSISTANT: %s", turn, reply)
            elif resp.status_code == 429:
                log.warning(
                    "turn=%d status=429 rate-limited — interval too low for the gateway's prompt limit",
                    turn,
                )
            else:
                log.warning("turn=%d status=%d body=%.200s", turn, resp.status_code, resp.text)

        except requests.RequestException as e:
            log.error("turn=%d request failed: %s", turn, e)

        # Periodically start a fresh conversation so load stays varied/bounded.
        if convo.user_turns >= Config.RESET_AFTER_TURNS:
            log.info("resetting conversation after %d user turns", convo.user_turns)
            convo.reset()

        # Interruptible sleep: wakes immediately on shutdown signal.
        delay = Config.INTERVAL_SECONDS + random.uniform(0, Config.INTERVAL_JITTER_SECONDS)
        _stop.wait(delay)

    log.info("loadgen stopped after %d turns", turn)


if __name__ == "__main__":
    main()
