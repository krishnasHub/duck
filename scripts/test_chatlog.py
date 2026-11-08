"""Check log retention in a throwaway folder, so real logs are never touched."""
import tempfile
from datetime import date
from pathlib import Path

import chatlog

with tempfile.TemporaryDirectory() as folder:
    chatlog.ROOT = Path(folder)
    logs = chatlog.log_dir("test")
    logs.mkdir(parents=True)
    today = date(2026, 12, 31)
    for name in ("2026-11-30", "2026-12-01", "2026-12-31", "2026-11-29", "2026-01-01", "not-a-date"):
        (logs / f"{name}.jsonl").write_text("{}\n", encoding="utf-8")
    removed = chatlog.prune("test", today)
    left = sorted(path.stem for path in logs.glob("*.jsonl"))
    # December 1 is exactly 30 days before December 31, so it stays and November 30 goes.
    assert removed == ["2026-01-01.jsonl", "2026-11-29.jsonl", "2026-11-30.jsonl"], removed
    assert left == ["2026-12-01", "2026-12-31", "not-a-date"], left
    assert not chatlog.prune("missing-persona", today)
print("retention ok: exactly 30 days kept, older files removed, other files left alone")
