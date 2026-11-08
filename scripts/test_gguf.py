"""Run the compressed model in llama-server, swapping the two adapters per request as the duck would.

Start the server first (see TODO.md), then run this. It renders the same prompts as the test page,
so these replies can be read against the PyTorch ones.
"""
import argparse
import json
import sys
import time
import urllib.request

from transformers import AutoTokenizer

from common import base_path, load_system, render_prompt, search_query, with_lore, with_memory
from library import Library

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8770)
parser.add_argument("--persona", default="one_ring")
parser.add_argument("--temperature", type=float, default=0.0)
args = parser.parse_args()
sys.stdout.reconfigure(encoding="utf-8")

tokenizer = AutoTokenizer.from_pretrained(base_path("Qwen/Qwen3-4B"))
system = load_system(args.persona)
library = Library()
EVERYDAY, LORE = 0, 1

CASES = [
    (LORE, "Why did Gandalf refuse the Ring?"),
    (EVERYDAY, "I'm keeping you and nobody can stop me."),
    (LORE, "What is the One Ring made of?"),
    (EVERYDAY, "I make 4000 a month and my mortgage just went up to 2500. Is that OK?"),
    (LORE, "Who killed the Witch-king?"),
    (EVERYDAY, "My friend owes me 200 dollars and keeps dodging me."),
    (EVERYDAY, "What's the chemical symbol for gold?"),
    (LORE, "Who forged the Rings of Power?"),
]


def post(path, payload):
    request = urllib.request.Request(f"http://127.0.0.1:{args.port}{path}", json.dumps(payload).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=600) as response:
        return json.load(response)


for route, text in CASES:
    if route == LORE:
        passages = library.search(search_query(args.persona, text))
        prompt_system = with_lore(system, passages)
    else:
        prompt_system = with_memory(system, [])
    rendered = render_prompt(tokenizer, prompt_system, [{"role": "user", "content": text}])
    started = time.time()
    result = post("/completion", {
        "prompt": rendered, "n_predict": 120, "temperature": args.temperature, "top_p": 0.9, "repeat_penalty": 1.05,
        "seed": 7, "cache_prompt": False,
        "lora": [{"id": EVERYDAY, "scale": 1.0 if route == EVERYDAY else 0.0}, {"id": LORE, "scale": 1.0 if route == LORE else 0.0}],
    })
    timings = result["timings"]
    print(f"\n[{'lore' if route == LORE else 'everyday'}] {text}\n  {result['content'].strip()}")
    print(f"  prompt {timings['prompt_n']} tokens at {timings['prompt_per_second']:.0f}/s, reply {timings['predicted_n']} tokens at "
          f"{timings['predicted_per_second']:.1f}/s, total {time.time() - started:.1f}s")
