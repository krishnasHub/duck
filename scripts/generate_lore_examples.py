"""Use the base model on the 4090 to write Q&A from library passages, keeping only answers the passage supports.

Also writes "the passages don't say" examples, using a real question with unrelated passages.
Quiz and benchmark questions are filtered out, so they stay a fair test.
"""
import argparse
import json
import random
import re
from collections import Counter

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from common import base_path, persona_dir
from library import ROOT, Library, tokens

parser = argparse.ArgumentParser()
parser.add_argument("--persona", default="one_ring")
parser.add_argument("--base", default="Qwen/Qwen3-4B")
parser.add_argument("--count", type=int, default=450, help="passages to try")
parser.add_argument("--seed", type=int, default=11)
parser.add_argument("--kind", choices=("any", "why"), default="any")
args = parser.parse_args()
random.seed(args.seed)

library = Library()
OUT_OF_WORLD = re.compile(
    r"Tolkien|scholar|critic|comment|Shippey|Flieger|Kocher|Letters|publish|edition|novel|author|reader|essay|journal|"
    r"Beowulf|Christian|medieval|Old English|Norse|film|Jackson|translat|illustrat|philolog|chapter|narrative|writes|wrote",
    re.I,
)
in_world = [
    p for p in library.passages
    if not OUT_OF_WORLD.search(p["text"]) and not OUT_OF_WORLD.search(p["title"]) and len(p["text"].split()) >= 40
]
print(f"{len(in_world)} in-world passages of {len(library.passages)}")
random.shuffle(in_world)
# Spread across articles, so a few long ones don't dominate.
per_title, chosen = Counter(), []
for passage in in_world:
    if per_title[passage["title"]] < 4:
        per_title[passage["title"]] += 1
        chosen.append(passage)
    if len(chosen) == args.count:
        break
print(f"trying {len(chosen)} passages from {len(per_title)} articles")

tests = []
for name in ("quiz.jsonl", "search_benchmark.jsonl"):
    tests += [set(tokens(json.loads(line)["q"])) for line in open(ROOT / "lore" / name, encoding="utf-8") if line.strip()]


def too_close_to_test(question):
    words = set(tokens(question))
    return any(len(words & test) / max(len(words | test), 1) >= 0.5 for test in tests)


tokenizer = AutoTokenizer.from_pretrained(base_path(args.base))
model = AutoModelForCausalLM.from_pretrained(base_path(args.base), dtype=torch.bfloat16, device_map={"": 0}).eval()
KIND = {
    "any": "one simple question that a curious fan might ask",
    "why": "one question beginning with Why or How, or What happened, that a curious fan might ask about causes or events",
}[args.kind]
INSTRUCTION = (
    f"Read the passage. Write {KIND}, and its answer in one short sentence. "
    "The question must name who or what it asks about, and must make sense without seeing the passage. "
    "Use only facts stated in the passage. Reply only with JSON: {\"q\": \"...\", \"a\": \"...\"}\n\nPassage: "
)


def ask(passage):
    rendered = tokenizer.apply_chat_template(
        [{"role": "user", "content": INSTRUCTION + passage["text"]}],
        tokenize=False, add_generation_prompt=True, enable_thinking=False,
    )
    inputs = tokenizer(rendered, return_tensors="pt", add_special_tokens=False).to("cuda")
    with torch.no_grad():
        output = model.generate(**inputs, max_new_tokens=90, do_sample=False)
    return tokenizer.decode(output[0][inputs.input_ids.shape[1] :], skip_special_tokens=True)


def names_in(text):
    return {t for word in re.findall(r"\b[^\W\d_]+\b", text) if word[0].isupper() for t in tokens(word)}


reasons = Counter()
rows = []
for number, passage in enumerate(chosen, 1):
    reply = ask(passage)
    match = re.search(r"\{.*\}", reply, re.S)
    if number % 50 == 0:
        print(f"{number}/{len(chosen)}: kept {len(rows)}, dropped {dict(reasons)}", flush=True)
    try:
        item = json.loads(match.group(0))
        question, answer = item["q"].strip(), item["a"].strip()
    except (AttributeError, ValueError, KeyError, TypeError):
        reasons["bad format"] += 1
        continue
    passage_words = set(tokens(passage["title"] + " " + passage["text"]))
    answer_words = set(tokens(answer))
    if not question.endswith("?") or len(answer.split()) > 35 or len(answer.split()) < 3:
        reasons["bad shape"] += 1
    elif OUT_OF_WORLD.search(question + " " + answer) or re.search(r"\b(passage|text|article)\b", question + answer, re.I):
        reasons["out of world"] += 1
    elif len(answer_words - passage_words) / max(len(answer_words), 1) > 0.15 or not names_in(answer) <= passage_words:
        reasons["answer not in passage"] += 1
    elif not names_in(question):
        reasons["question names nothing"] += 1
    elif too_close_to_test(question):
        reasons["too close to a test question"] += 1
    elif args.kind == "why" and not re.match(r"(why|how|what happen)", question, re.I):
        reasons["not a why or how question"] += 1
    else:
        key = sorted(names_in(answer) or answer_words, key=len, reverse=True)[0]
        rows.append({"q": question, "a": answer, "key": key})

folder = persona_dir(args.persona)
out_name = "lore_qa_why_gen.jsonl" if args.kind == "why" else "lore_qa_gen.jsonl"
with open(folder / out_name, "w", encoding="utf-8") as handle:
    handle.write("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
print(f"kept {len(rows)}, dropped {dict(reasons)}")
if args.kind == "why":
    for row in random.sample(rows, min(25, len(rows))):
        print(" ", row["q"], "->", row["a"])
    raise SystemExit

REFUSALS = [
    "I can't recall that, and I won't make it up.",
    "That isn't in my memory, so I won't invent it.",
    "I can't recall anything about that.",
    "My memory holds nothing on that, and I won't pretend otherwise.",
    "I don't recall that, and I'd rather not guess.",
]
negatives = []
for row in random.sample(rows, min(90, len(rows))):
    # Passages must not mention what the question is about.
    question_names = names_in(row["q"]) | set(tokens(row["key"]))
    pool = [
        p for p in random.sample(library.passages, 60)
        if not question_names & set(tokens(p["title"] + " " + p["text"]))
    ]
    if len(pool) >= 4:
        negatives.append(
            {
                "passages": pool[:4],
                "messages": [
                    {"role": "user", "content": row["q"]},
                    {"role": "assistant", "content": random.choice(REFUSALS)},
                ],
            }
        )
with open(folder / "train_no_answer.jsonl", "w", encoding="utf-8") as handle:
    handle.write("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in negatives))
print(f"wrote {len(negatives)} no-answer examples")
for row in random.sample(rows, min(12, len(rows))):
    print(" ", row["q"], "->", row["a"])
