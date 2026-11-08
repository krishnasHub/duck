"""Check note-taking on fresh messages. Each case lists words a kept note must contain, or nothing for no note."""
import os
import sys

os.environ["HF_HUB_OFFLINE"] = "1"

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from common import base_path, render_prompt
from memory import EXTRACT_SYSTEM, FIRST_PERSON, grounded, parse_notes

sys.stdout.reconfigure(encoding="utf-8")

CASES = [
    ("My name's Dev and I teach high school chemistry.", ["Dev", "chemistry"]),
    ("I live in Pune with my two cats, Mochi and Tofu.", ["Pune", "Mochi", "Tofu"]),
    ("My wife Sarah and I are expecting a baby in March.", ["Sarah", "baby"]),
    ("I'm allergic to peanuts, so that's out.", ["peanuts"]),
    ("I've been a carpenter for twenty years.", ["carpenter"]),
    ("My mom's surgery is next Tuesday.", ["surgery"]),
    ("I'm trying to quit smoking this year.", ["smoking"]),
    ("Honestly I love terrible reality TV.", ["reality"]),
    ("My best friend Kofi is moving to Berlin.", ["Kofi"]),
    ("I want to start a podcast about birds.", ["podcast"]),
    ("I would rule all of Middle-earth, and you'd help me!", []),
    ("If I had a million dollars I'd buy an island.", []),
    ("I'm hungry.", []),
    ("I think Boromir got a raw deal.", []),
    ("Can I ask you something?", []),
    ("I bet you can't do long division.", []),
    ("Ha! I'm the king of the world!", []),
    ("I don't know what to say.", []),
    ("I wonder why the sky is blue.", []),
    ("We have 10 men and 200 enemies outside the walls in my game.", []),
    ("I'm taking you for myself, precious.", []),
    ("I saw a funny dog today.", []),
]

path = base_path("Qwen/Qwen3-4B")
tokenizer = AutoTokenizer.from_pretrained(path)
model = AutoModelForCausalLM.from_pretrained(path, dtype=torch.bfloat16, device_map={"": 0}).eval()
good = 0
for text, wanted in CASES:
    assert FIRST_PERSON.search(text), text
    rendered = render_prompt(tokenizer, EXTRACT_SYSTEM, [{"role": "user", "content": f"Message: {text}"}])
    inputs = tokenizer(rendered, return_tensors="pt", add_special_tokens=False).to("cuda")
    with torch.no_grad():
        output = model.generate(**inputs, max_new_tokens=80, do_sample=False)
    raw = tokenizer.decode(output[0][inputs.input_ids.shape[1] :], skip_special_tokens=True)
    parsed = parse_notes(raw)
    kept = [n for n in parsed if grounded(n, text)]
    joined = " ".join(kept)
    ok = all(w.lower() in joined.lower() for w in wanted) and (bool(kept) == bool(wanted))
    good += ok
    dropped = [n for n in parsed if n not in kept]
    print(("ok  " if ok else "MISS"), text, "->", kept, f"(dropped {dropped})" if dropped else "")
print(f"{good}/{len(CASES)}")
