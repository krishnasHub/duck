"""Turn lore Q&A into training rows, using what the library really retrieves for each question.

A row is skipped if its key term isn't in the retrieved passages, so the model never learns
to state a fact that its passages don't support.
"""
import argparse
import json
import re

from common import persona_dir, search_query
from library import ROOT, Library, tokens

parser = argparse.ArgumentParser()
parser.add_argument("--persona", default="one_ring")
parser.add_argument("--val", type=int, default=4, help="send every Nth kept row to validation")
parser.add_argument("--max-generated", type=int, default=None, help="cap how many generated rows are used")
parser.add_argument("--plain", action="store_true", help="drop closing flourishes about the Ring from lore answers")
args = parser.parse_args()

FIRST_PERSON = re.compile(r"\b(I|I'm|I've|me|my|mine|myself)\b")


def plain_answer(text):
    """Keep the opening and any later factual sentences; drop later sentences about the Ring itself."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = [sentences[0]]
    for sentence in sentences[1:]:
        if len(" ".join(kept).split()) < 5 or not FIRST_PERSON.search(sentence):
            kept.append(sentence)
    return " ".join(kept)


library = Library()
folder = persona_dir(args.persona)
rows = [
    {**json.loads(line), "generated": path.stem.endswith("_gen"), "source": path.stem}
    for path in sorted(folder.glob("lore_qa*.jsonl"))
    for line in open(path, encoding="utf-8")
    if line.strip()
]
# Generated rows mustn't teach quiz answers, so the quiz stays a fair test of reading the passages.
quiz_terms = []
for line in open(ROOT / "lore" / "quiz.jsonl", encoding="utf-8"):
    if line.strip():
        row = json.loads(line)
        if row["type"] in ("easy", "hard"):
            quiz_terms += [term for term in row["any"] if len(term) > 3 and term.lower() not in ("horse", "steed", "brother", "brothers", "twin", "twins", "oath")]
quiz_pattern = re.compile("|".join(rf"\b{re.escape(term)}\b" for term in quiz_terms) + r"|Witch-king|Shadowfax|Skogemann|Jungian"
    # Off-topic or wrong rows found by reading samples.
    r"|Erdo|Çetin|Çiftçi|Fafner|Elendilmir|nasal|spirant|Nandorin|Doriathrin|Fourth part", re.I)
before = len(rows)
rows = [row for row in rows if not (row.get("generated") and quiz_pattern.search(row["q"] + " " + row["a"]))]
print(f"dropped {before - len(rows)} generated rows that touch quiz answers")
if args.max_generated is not None:
    # The cap applies to each generated file, so one question style can't crowd out another.
    kept, seen = [], {}
    for row in rows:
        if row.get("generated"):
            seen[row["source"]] = seen.get(row["source"], 0) + 1
            if seen[row["source"]] > args.max_generated:
                continue
        kept.append(row)
    rows = kept

train, val, skipped = [], [], []
for row in rows:
    passages = library.search(search_query(args.persona, row["q"]))
    found = tokens(" ".join(p["title"] + " " + p["text"] for p in passages))
    if not set(tokens(row["key"])) <= set(found):
        skipped.append(row["q"])
        continue
    answer = plain_answer(row["a"]) if args.plain else row["a"]
    item = {
        "passages": passages,
        "messages": [{"role": "user", "content": row["q"]}, {"role": "assistant", "content": answer}],
    }
    kept = len(train) + len(val) + 1
    (val if kept % args.val == 0 else train).append(item)

for name, items in (("train_lore.jsonl", train), ("val_lore.jsonl", val)):
    with open(folder / name, "w", encoding="utf-8") as handle:
        handle.write("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items))
print(f"train {len(train)}, val {len(val)}, skipped {len(skipped)}")
for question in skipped:
    print("  skipped, key term not retrieved:", question)
