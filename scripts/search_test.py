"""Compare search settings on paraphrased questions, where exact keywords won't always help."""
import json
import re
from collections import Counter, defaultdict

from library import ROOT, Library

library = Library()
rows = []
for name in ("search_benchmark.jsonl", "quiz.jsonl"):
    for line in open(ROOT / "lore" / name, encoding="utf-8"):
        row = json.loads(line) if line.strip() else None
        if row and row.get("type", "factual") in ("factual", "easy", "hard"):
            row["set"] = "paraphrase" if name.startswith("search") else "direct"
            rows.append(row)


def weighted(query, keyword_weight, meaning_weight, top=4, per_title=2, pool=40):
    merged = defaultdict(float)
    for weight, ranking in (
        (keyword_weight, library.keyword_ranking(query, pool)),
        (meaning_weight, library.meaning_ranking(query, pool)),
    ):
        for rank, index in enumerate(ranking):
            merged[index] += weight / (60 + rank)
    results, used = [], Counter()
    for index in sorted(merged, key=merged.get, reverse=True):
        passage = library.passages[index]
        if used[passage["title"]] < per_title:
            used[passage["title"]] += 1
            results.append(passage)
        if len(results) == top:
            break
    return results


def hit(passages, row):
    text = " ".join(p["title"] + " " + p["text"] for p in passages)
    return any(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.I) for term in row["any"])


print(f"{len(library.passages)} passages")
score = Counter()
misses = []
for row in rows:
    found = hit(library.search(row["q"]), row)
    score[row["set"]] += found
    if not found:
        misses.append(row["q"][:44])
print(f"{'taking turns':14} paraphrase {score['paraphrase']}/16  direct {score['direct']}/13  missed: {misses}")
for label, weights in (
    ("keyword only", (1, 0)),
    ("meaning only", (0, 1)),
    ("equal", (1, 1)),
    ("meaning x2", (1, 2)),
    ("keyword x2", (2, 1)),
):
    score = Counter()
    misses = []
    for row in rows:
        found = hit(weighted(row["q"], *weights), row)
        score[row["set"]] += found
        if not found and row["set"] == "paraphrase":
            misses.append(row["q"][:44])
    print(f"{label:14} paraphrase {score['paraphrase']}/16  direct {score['direct']}/13  missed: {misses}")
