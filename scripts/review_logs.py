"""Print logged conversations for reading, with how each reply was produced.

    uv run python scripts/review_logs.py --persona one_ring
    uv run python scripts/review_logs.py --by user --last 2
    uv run python scripts/review_logs.py --stats
"""
import argparse
import sys
from collections import Counter

from chatlog import read

parser = argparse.ArgumentParser()
parser.add_argument("--persona", default="one_ring")
parser.add_argument("--by", help="only chats from this tester: user or claude")
parser.add_argument("--last", type=int, help="only the most recent N chats")
parser.add_argument("--stats", action="store_true", help="counts only")
args = parser.parse_args()
sys.stdout.reconfigure(encoding="utf-8")

events = [e for e in read(args.persona) if not args.by or e.get("by") == args.by]
turns = [e for e in events if e.get("type") == "turn"]
if args.stats:
    print(f"{len(turns)} turns in {len({e['session'] for e in turns})} chats")
    print("routes:", dict(Counter(e["route"] for e in turns)))
    print("testers:", dict(Counter(e.get("by") for e in turns)))
    print("corrections:", sum(e.get("type") == "correction" for e in events))
    print("memories added:", sum(e.get("type") == "memory_added" for e in events))
    raise SystemExit

sessions = list(dict.fromkeys(e["session"] for e in events if e.get("session")))
if args.last:
    sessions = sessions[-args.last :]
for session in sessions:
    chat = [e for e in events if e.get("session") == session]
    print(f"\n=== {session}, {chat[0]['time']}, by {chat[0].get('by')}")
    for event in chat:
        kind = event.get("type")
        if kind == "turn":
            details = event["route"]
            if event.get("passages"):
                details += " | " + ", ".join(event["passages"])
            if event.get("memory"):
                details += " | remembered: " + "; ".join(event["memory"])
            if event.get("flourish"):
                details += " | closing line added"
            print(f"\nYOU: {event['user']}\n[{details}]\nDUCK: {event['reply']}")
        elif kind == "correction":
            print(f"\nCORRECTED TO: {event['corrected']}")
        elif kind == "memory_added":
            print(f"  (noted: {event['note']})")
