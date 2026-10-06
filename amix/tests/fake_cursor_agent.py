"""Stand-in for the Cursor Agent CLI. It never opens a network connection."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    args = sys.argv[1:]
    _log(args)
    if "--version" in args or "-v" in args:
        print("2026.10.01-test")
        return 0
    if "models" in args or "--list-models" in args:
        print("Available models")
        print("")
        print("auto - Auto (default)")
        print("grok-4.7-high - Grok 4.7 High")
        print("composer-2.5 - Composer 2.5")
        return 0
    if "status" in args or "whoami" in args:
        if os.environ.get("FAKE_CURSOR_AUTH") == "no":
            print("Not logged in")
            return 1
        print("Logged in")
        return 0
    if "login" in args:
        return 0
    if "-p" not in args and "--print" not in args:
        return 2
    prompt = sys.stdin.read()
    mode = os.environ.get("FAKE_CURSOR_MODE", "ok")
    if mode == "sleep":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        path = os.environ.get("FAKE_CURSOR_CHILD", "")
        if path:
            Path(path).write_text(str(child.pid), encoding="utf-8")
        time.sleep(60)
        return 0
    if mode == "exit":
        return 2
    if mode == "loop":
        state = os.environ.get("FAKE_CURSOR_LOOP_STATE", "")
        marker = Path(state) if state else None
        if marker is None or not marker.is_file():
            if marker is not None:
                marker.write_text("1", encoding="utf-8")
            print(
                "NonRetriableError: Agent Looping Detected The model got stuck in a repeating response pattern",
                file=sys.stderr,
            )
            return 1
    if mode == "fence":
        print(json.dumps({"type": "result", "is_error": False, "result": "```json\n{\"ok\": true}\n```"}))
        return 0
    try:
        payload = _payload(prompt)
    except json.JSONDecodeError:
        print(json.dumps({"type": "result", "is_error": True, "result": ""}))
        return 1
    if mode == "bad" or (mode == "repair" and "repair" not in payload):
        print(json.dumps({"type": "result", "is_error": False, "result": "not json"}))
        return 0
    try:
        body = _cover(payload)
    except (KeyError, IndexError, TypeError):
        print(json.dumps({"type": "result", "is_error": True, "result": ""}))
        return 1
    print(json.dumps({
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": json.dumps(body, ensure_ascii=False),
    }))
    return 0


def _log(args: list[str]) -> None:
    path = os.environ.get("FAKE_CURSOR_LOG", "")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"argv": args, "cwd": os.getcwd()}) + "\n")


def _payload(prompt: str) -> dict:
    marker = "\nDATA\n"
    if marker not in prompt:
        return {}
    parsed = json.loads(prompt.split(marker, 1)[1])
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _cover(payload: dict) -> dict:
    stage = payload.get("stage")
    if stage == "consolidate":
        return {"candidates": list(payload.get("candidates") or [])}
    if stage == "discover":
        primary = [turn for turn in payload["turns"] if turn.get("role") == "primary"]
        return {"candidates": [{
            "conversation_thread_id": payload["conversation_thread_id"],
            "first_turn_id": primary[0]["turn_id"],
            "last_turn_id": primary[-1]["turn_id"],
            "title": "Whole moment",
            "summary": "Setup and payoff.",
            "hook": "The last turn answers the first.",
        }]}
    if stage == "merge":
        candidates = payload["candidates"]
        if isinstance(candidates[0], dict):
            start = candidates[0]["start_turn_id"]
            end = candidates[-1]["end_turn_id"]
        else:
            start = candidates[0][0]
            end = candidates[-1][1]
        return {"threads": [{
            "start_turn_id": start,
            "end_turn_id": end,
            "title": "Whole",
            "summary": "All of it",
        }]}
    turns = payload["turns"]
    if isinstance(turns[0], dict):
        primary = [turn for turn in turns if turn.get("role", "primary") == "primary"]
        start = primary[0]["turn_id"]
        end = primary[-1]["turn_id"]
    else:
        start = turns[0][0]
        end = turns[-1][0]
    return {"threads": [{
        "start_turn_id": start,
        "end_turn_id": end,
        "title": "Chunk",
        "summary": "Kept",
    }]}


if __name__ == "__main__":
    sys.exit(main())
