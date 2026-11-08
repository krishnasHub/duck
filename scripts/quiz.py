"""Score search and answers on lore/quiz.jsonl. It's a keyword check, so read the saved report as well."""
import argparse
import json
import re
import time
from collections import defaultdict

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

from common import ROOT, base_path, load_system, render_prompt, with_lore
from library import Library, tokens

parser = argparse.ArgumentParser()
parser.add_argument("--persona", default="one_ring")
parser.add_argument("--base", default="Qwen/Qwen3-4B")
parser.add_argument("--adapter", default=None, help="adapter folder in runs/<persona>; omit for prompt only")
parser.add_argument("--modes", default="none,keyword,hybrid")
parser.add_argument("--retrieval-only", action="store_true")
parser.add_argument("--label", default="prompt")
parser.add_argument("--quiz", default="quiz.jsonl")
parser.add_argument("--temperature", type=float, default=0.0, help="0 for fixed answers; the page uses 0.3 for lore")
args = parser.parse_args()

library = Library()
quiz = [json.loads(line) for line in open(ROOT / "lore" / args.quiz, encoding="utf-8") if line.strip()]
print(f"library: {len(library.passages)} passages, embeddings: {library.vectors is not None}")


def has_term(text, term):
    """Match whole words, so "ancient" doesn't count as "Ent"."""
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.I) is not None


def has_answer(text, row):
    if any(has_term(text, term) for term in row.get("none", [])):
        return False
    return any(has_term(text, term) for term in row["any"])


# Search only: does a passage hold the answer? False-premise and unknown questions don't apply.
for mode in ("keyword", "hybrid"):
    factual = [row for row in quiz if row["type"] in ("easy", "hard")]
    started = time.time()
    hits = [
        has_answer(" ".join(p["text"] for p in library.search(row["q"], mode=mode)), row) for row in factual
    ]
    print(f"search {mode}: answer in passages for {sum(hits)}/{len(factual)}, {(time.time() - started) / len(factual) * 1000:.0f} ms each")
    for row, hit in zip(factual, hits):
        if not hit:
            print("   missed:", row["q"])
if args.retrieval_only:
    raise SystemExit

tokenizer = AutoTokenizer.from_pretrained(base_path(args.base))
system = load_system(args.persona)
model = AutoModelForCausalLM.from_pretrained(base_path(args.base), dtype=torch.bfloat16, device_map={"": 0})
if args.adapter:
    model = PeftModel.from_pretrained(model, ROOT / "runs" / args.persona / args.adapter)
model.eval()


def answer(question, passages):
    rendered = render_prompt(tokenizer, with_lore(system, passages), [{"role": "user", "content": question}])
    inputs = tokenizer(rendered, return_tensors="pt", add_special_tokens=False).to("cuda")
    sampling = {"do_sample": True, "temperature": args.temperature, "top_p": 0.9} if args.temperature else {"do_sample": False}
    with torch.no_grad():
        output = model.generate(**inputs, max_new_tokens=120, repetition_penalty=1.05, **sampling)
    return tokenizer.decode(output[0][inputs.input_ids.shape[1] :], skip_special_tokens=True).strip()


lines = [f"# Lore quiz: {args.persona}, {args.label}\n"]
modes = args.modes.split(",")
scores = {mode: defaultdict(int) for mode in modes}
totals = defaultdict(int)
for row in quiz:
    totals[row["type"]] += 1
    lines.append(f"## [{row['type']}] {row['q']}\n")
    for mode in modes:
        passages = [] if mode == "none" else library.search(row["q"], mode=mode)
        reply = answer(row["q"], passages)
        correct = has_answer(reply, row)
        scores[mode][row["type"]] += correct
        titles = ", ".join(p["title"] for p in passages)
        lines.append(f"**{mode} {'PASS' if correct else 'FAIL'}:** {reply}\n\n_Passages: {titles or 'none'}_\n")

summary = ["| Type | " + " | ".join(modes) + " |", "|---|" + "---|" * len(modes)]
for kind in totals:
    summary.append(f"| {kind} | " + " | ".join(f"{scores[m][kind]}/{totals[kind]}" for m in modes) + " |")
summary.append("| **total** | " + " | ".join(f"**{sum(scores[m].values())}/{len(quiz)}**" for m in modes) + " |")
print("\n".join(summary))
out = ROOT / "runs" / args.persona / f"quiz_{args.label}.md"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("\n".join(summary) + "\n\n" + "\n".join(lines), encoding="utf-8")
print(f"written to {out}")
