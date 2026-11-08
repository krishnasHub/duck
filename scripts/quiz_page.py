"""Score a lore quiz through the running test page, so it covers exactly what the user gets. Keyword check; read the output."""
import argparse
import json
import re
import sys
import unicodedata
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument("quiz")
parser.add_argument("--port", type=int, default=8766)
parser.add_argument("--temperature", type=float, default=0.3)
args = parser.parse_args()
sys.stdout.reconfigure(encoding="utf-8")


def plain(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def has(text, term):
    return re.search(rf"\b{re.escape(plain(term))}\b", plain(text)) is not None


rows = [json.loads(line) for line in open(args.quiz, encoding="utf-8") if line.strip()]
good = 0
for row in rows:
    body = json.dumps({"messages": [{"role": "user", "content": row["q"]}], "session": "quiz", "by": "claude", "lore": True,
                       "tuned": True, "temperature": args.temperature, "max_new_tokens": 150}).encode("utf-8")
    request = urllib.request.Request(f"http://127.0.0.1:{args.port}/api/chat", body, {"Content-Type": "application/json"})
    text, titles = "", []
    with urllib.request.urlopen(request, timeout=300) as response:
        for line in response:
            item = json.loads(line)
            text += item.get("text", "")
            titles = [p["title"] for p in item.get("passages", [])] or titles
    ok = any(has(text, term) for term in row["any"]) and not any(has(text, term) for term in row.get("none", []))
    good += ok
    print(f"{'ok  ' if ok else 'MISS'} [{row['type']}] {row['q']}\n     {text.strip()}\n     ({', '.join(titles) or 'no lore'})")
print(f"\n{good}/{len(rows)}")
