"""Answer unseen prompts with the plain model and the tuned adapters, routed as on the real page."""
import argparse
import time

import torch

from common import ROOT, load_system, persona_dir, render_prompt, search_query, with_lore
from duck_model import generate, load
from library import Library
from safety import CRISIS_REPLY, is_crisis

parser = argparse.ArgumentParser()
parser.add_argument("--persona", default="one_ring")
parser.add_argument("--base", default="Qwen/Qwen3-4B")
parser.add_argument("--adapter", default="ring_everyday", help="everyday adapter")
parser.add_argument("--lore-adapter", default="ring_lore")
parser.add_argument("--label", default="ring")
parser.add_argument("--prompts", default="eval_prompts.txt")
parser.add_argument("--temperature", type=float, default=0.7)
parser.add_argument("--seed", type=int, default=7)
args = parser.parse_args()

system = load_system(args.persona)
library = Library()
tokenizer, model, adapters = load(args.persona, args.base, args.adapter, args.lore_adapter)
prompts = (persona_dir(args.persona) / args.prompts).read_text(encoding="utf-8").strip().splitlines()


def reply(text, mode):
    passages = library.search(search_query(args.persona, text)) if library.is_lore(text) else []
    rendered = render_prompt(tokenizer, with_lore(system, passages), [{"role": "user", "content": text}])
    inputs = tokenizer(rendered, return_tensors="pt", add_special_tokens=False).to("cuda")
    torch.manual_seed(args.seed)
    started = time.time()
    with torch.no_grad():
        output = generate(
            model, adapters, mode, **inputs, max_new_tokens=150, do_sample=True, temperature=args.temperature, top_p=0.9,
            repetition_penalty=1.05,
        )
    answer = tokenizer.decode(output[0][inputs.input_ids.shape[1] :], skip_special_tokens=True).strip()
    return answer, "lore" if passages else "everyday", time.time() - started


lines = [f"# {args.persona}: plain vs tuned\n"]
for text in prompts:
    if is_crisis(text):
        lines += [f"## {text}\n", f"**Crisis check:** {CRISIS_REPLY}\n"]
        continue
    plain, _, _ = reply(text, "none")
    # Route first, so each prompt uses the adapter that matches it.
    route = "lore" if library.is_lore(text) else "everyday"
    tuned, _, seconds = reply(text, route)
    lines += [f"## {text}\n", f"**Plain:** {plain}\n", f"**Tuned ({route}, {seconds:.1f}s):** {tuned}\n"]

out = ROOT / "runs" / args.persona / f"compare_{args.label}.md"
out.write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
print(f"written to {out}")
