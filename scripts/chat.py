"""Type to the tuned duck in the terminal. Runs entirely from local files."""
import argparse
import os

os.environ["HF_HUB_OFFLINE"] = "1"

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

from common import ROOT, base_path, load_system, render_prompt

parser = argparse.ArgumentParser()
parser.add_argument("--persona", default="gandalf")
parser.add_argument("--base", default="Qwen/Qwen3-4B")
parser.add_argument("--no-adapter", action="store_true", help="use the persona prompt without the tuned weights")
args = parser.parse_args()

tokenizer = AutoTokenizer.from_pretrained(base_path(args.base))
system = load_system(args.persona)
model = AutoModelForCausalLM.from_pretrained(base_path(args.base), dtype=torch.bfloat16, device_map={"": 0})
if not args.no_adapter:
    model = PeftModel.from_pretrained(model, ROOT / "runs" / args.persona / "adapter")
model.eval()

history = []
print("Talk to the duck. Type 'quit' to leave or 'reset' to clear this conversation.\n")
while True:
    text = input("you> ").strip()
    if text.lower() == "quit":
        break
    if text.lower() == "reset":
        history = []
        print("(conversation cleared)\n")
        continue
    if not text:
        continue
    history.append({"role": "user", "content": text})
    rendered = render_prompt(tokenizer, system, history)
    inputs = tokenizer(rendered, return_tensors="pt", add_special_tokens=False).to("cuda")
    with torch.no_grad():
        output = model.generate(
            **inputs, max_new_tokens=150, do_sample=True, temperature=0.7, top_p=0.9, repetition_penalty=1.05
        )
    answer = tokenizer.decode(output[0][inputs.input_ids.shape[1] :], skip_special_tokens=True).strip()
    history.append({"role": "assistant", "content": answer})
    print(f"duck> {answer}\n")
