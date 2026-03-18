import json
import os
import time
from pathlib import Path


TRACE_ROOT = Path.home() / ".mathhistoria" / "traces"


def build_trace_path(run_id: str) -> str:
    TRACE_ROOT.mkdir(parents=True, exist_ok=True)
    return str(TRACE_ROOT / f"{run_id}.jsonl")


def append_trace_event(trace_path: str | None, event: str, **payload) -> None:
    if not trace_path:
        return

    record = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "event": event,
        "payload": payload,
    }
    try:
        os.makedirs(os.path.dirname(trace_path), exist_ok=True)
        with open(trace_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass
