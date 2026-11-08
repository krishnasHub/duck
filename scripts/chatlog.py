"""Record every conversation turn on this PC, so real chats can guide tuning.

Each line in logs/<persona>/<date>.jsonl is one event. Nothing here leaves the machine.
"Forget everything" clears the duck's notes but not these logs, which are kept for 30 days.
"""
import json
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RETENTION_DAYS = 30
_lock = threading.Lock()
_pruned_on = {}


def log_dir(persona):
    return ROOT / "logs" / persona


def prune(persona, today=None, days=RETENTION_DAYS):
    """Delete daily log files more than `days` old. Other files in the folder are left alone. Returns what was deleted."""
    today = today or date.today()
    cutoff = today - timedelta(days=days)
    removed = []
    for path in log_dir(persona).glob("*.jsonl"):
        try:
            logged = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if logged < cutoff:
            path.unlink()
            removed.append(path.name)
    return sorted(removed)


def write(persona, event):
    now = datetime.now().astimezone()
    entry = {"time": now.isoformat(timespec="seconds"), **event}
    folder = log_dir(persona)
    folder.mkdir(parents=True, exist_ok=True)
    with _lock:
        # Checked on the first write of each day, so a page left running still keeps to the limit.
        if _pruned_on.get(persona) != now.date():
            prune(persona, now.date())
            _pruned_on[persona] = now.date()
        with open(folder / f"{now.date()}.jsonl", "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read(persona):
    """All logged events, oldest first."""
    events = []
    for path in sorted(log_dir(persona).glob("*.jsonl")):
        with open(path, encoding="utf-8") as handle:
            events.extend(json.loads(line) for line in handle if line.strip())
    return events
