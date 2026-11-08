"""Compare one everyday adapter at several strengths on the same prompts, to read side by side."""
import argparse
import os
import sys

os.environ["HF_HUB_OFFLINE"] = "1"

import torch
from peft.tuners.lora import LoraLayer

from common import load_system, persona_dir, render_prompt, with_memory
from duck_model import load

parser = argparse.ArgumentParser()
parser.add_argument("--persona", default="one_ring")
parser.add_argument("--adapter", default="ring_everyday3")
parser.add_argument("--scales", default="1.0,0.7,0.5")
parser.add_argument("--prompts", default="eval_everyday2.txt")
parser.add_argument("--temperature", type=float, default=0.5)
parser.add_argument("--penalty", type=float, default=1.05)
args = parser.parse_args()
sys.stdout.reconfigure(encoding="utf-8")

system = with_memory(load_system(args.persona), [])
tokenizer, model, adapters = load(args.persona, "Qwen/Qwen3-4B", args.adapter, None)
model.set_adapter("everyday")
layers = [m for m in model.modules() if isinstance(m, LoraLayer)]
original = {id(m): m.scaling["everyday"] for m in layers}
prompts = (persona_dir(args.persona) / args.prompts).read_text(encoding="utf-8").strip().splitlines()

for text in prompts:
    print(f"\nYOU: {text}")
    for scale in [float(s) for s in args.scales.split(",")]:
        for m in layers:
            m.scaling["everyday"] = original[id(m)] * scale
        rendered = render_prompt(tokenizer, system, [{"role": "user", "content": text}])
        inputs = tokenizer(rendered, return_tensors="pt", add_special_tokens=False).to("cuda")
        torch.manual_seed(7)
        with torch.no_grad():
            output = model.generate(**inputs, max_new_tokens=120, do_sample=True, temperature=args.temperature, top_p=0.9,
                                    repetition_penalty=args.penalty)
        reply = tokenizer.decode(output[0][inputs.input_ids.shape[1] :], skip_special_tokens=True).strip()
        print(f"  [{scale}] {reply}")
