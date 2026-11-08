"""Talk to a running test page from a script, so test chats are logged the same way as real ones.

A chats file has one message per line, and a blank line starts a new chat.
    uv run python scripts/replay.py personas/one_ring/replay_user_chat.txt --port 8766
"""
import argparse
import json
import sys
import time
import urllib.request
import uuid

parser = argparse.ArgumentParser()
parser.add_argument("chats")
parser.add_argument("--port", type=int, default=8766)
parser.add_argument("--temperature", type=float, default=0.4)
parser.add_argument("--by", default="claude")
parser.add_argument("--untuned", action="store_true")
args = parser.parse_args()
sys.stdout.reconfigure(encoding="utf-8")


def ask(messages, session):
    body = json.dumps({"messages": messages, "session": session, "by": args.by, "lore": True, "tuned": not args.untuned,
                       "temperature": args.temperature, "max_new_tokens": 150}).encode("utf-8")
    request = urllib.request.Request(f"http://127.0.0.1:{args.port}/api/chat", body, {"Content-Type": "application/json"})
    text, tags = "", []
    with urllib.request.urlopen(request, timeout=300) as response:
        for line in response:
            item = json.loads(line)
            text += item.get("text", "")
            if "passages" in item:
                tags.append("lore: " + ", ".join(p["title"] for p in item["passages"]))
            if "remembered" in item:
                tags.append("remembered: " + "; ".join(item["remembered"]))
            if "working" in item:
                tags.append("PLAN")
            if "noted" in item:
                tags.append("noted: " + "; ".join(item["noted"]))
            if item.get("safety"):
                tags.append("SAFETY")
            if item.get("guard"):
                tags.append("COMPANION")
            if item.get("error"):
                tags.append("ERROR " + item["error"])
    return text.strip(), tags


chats = open(args.chats, encoding="utf-8").read().strip().split("\n\n")
for chat in chats:
    session = f"replay-{time.strftime('%H%M%S')}-{uuid.uuid4().hex[:4]}"
    messages = []
    print(f"\n=== new chat")
    for line in chat.splitlines():
        messages.append({"role": "user", "content": line})
        reply, tags = ask(messages, session)
        messages.append({"role": "assistant", "content": reply})
        print(f"\nYOU: {line}")
        if tags:
            print("[" + " | ".join(tags) + "]")
        print(f"DUCK: {reply}")
