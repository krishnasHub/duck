"""Compare ways of using the same model on planning questions. Prints tokens as well as replies, since tokens set the Jetson's wait.

Needs a llama-server with the Ring's adapters on --port. Each mode returns the spoken reply and how many tokens it generated.
"""
import argparse
import json
import re
import sys
import time
import urllib.request

from transformers import AutoTokenizer

import planner
import war
from common import base_path, load_system, persona_dir, with_memory

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8771)
parser.add_argument("--modes", default="everyday,plain,think,work_voice,one_pass")
parser.add_argument("--show", action="store_true", help="also print hidden working")
parser.add_argument("--cases", default="plan_cases.jsonl")
args = parser.parse_args()
sys.stdout.reconfigure(encoding="utf-8")

tokenizer = AutoTokenizer.from_pretrained(base_path("Qwen/Qwen3-4B"))
system = with_memory(load_system("one_ring"), [])
EVERYDAY, LORE = 0, 1


def complete(prompt, adapter=None, temperature=0.2, max_tokens=150, stop=None, strip=True):
    payload = {
        "prompt": prompt, "n_predict": max_tokens, "temperature": temperature, "top_p": 0.9, "repeat_penalty": 1.05, "seed": 7,
        "cache_prompt": False, "stop": stop or [],
        "lora": [{"id": EVERYDAY, "scale": 1.0 if adapter == EVERYDAY else 0.0}, {"id": LORE, "scale": 0.0}],
    }
    request = urllib.request.Request(f"http://127.0.0.1:{args.port}/completion", json.dumps(payload).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=600) as response:
        result = json.load(response)
    return (result["content"].strip() if strip else result["content"]), result["timings"]["predicted_n"]


def render(prompt_system, messages, thinking=False):
    return tokenizer.apply_chat_template([{"role": "system", "content": prompt_system}, *messages], tokenize=False,
                                         add_generation_prompt=True, enable_thinking=thinking)


WORK_SYSTEM = (
    "Work out the user's problem carefully and briefly. List the numbers and limits they gave. Do each sum on its own line. "
    "If a question compares two sides, say which side is which and how many times bigger one is. If the user is badly "
    "outnumbered or short of what they need, say plainly that the direct way won't work, then give one indirect way that "
    "fits the details they gave. Finish with a line starting CONCLUSION: that gives the answer and the key numbers. "
    "Don't use facts they didn't give."
)
VOICE_NOTE = (
    "You have already worked this out, and the working below is correct. Give the user the conclusion and its key numbers "
    "in one to three short sentences, in your own voice. Keep every number exactly as it is. Don't mention the working, "
    "and don't use markdown.\n\n"
)
ONE_PASS = (
    "\n\nFor this question, first write WORK: and do the sums step by step, one per line, using only what the user gave you. "
    "Then write SAY: and give your reply to the user in your own voice, in one to three short sentences, with the conclusion and key numbers."
)


def strip_think(text):
    return re.sub(r"<think>.*?(</think>|$)", "", text, flags=re.S).strip()


def run(mode, messages):
    """Returns (spoken reply, tokens generated, hidden working)."""
    if mode == "everyday":
        reply, count = complete(render(system, messages), EVERYDAY, 0.4)
        return reply, count, ""
    if mode == "plain":
        reply, count = complete(render(system, messages))
        return reply, count, ""
    if mode == "think":
        text, count = complete(render(system, messages, thinking=True), max_tokens=500)
        return strip_think(text), count, text
    if mode in ("work_voice", "work_voice_plain"):
        work, first = complete(render(WORK_SYSTEM, messages), max_tokens=200, temperature=0.0)
        adapter = EVERYDAY if mode == "work_voice" else None
        reply, second = complete(render(f"{system}\n\n{VOICE_NOTE}{work}", messages), adapter, 0.3)
        return reply, first + second, work
    if mode in ("planner", "planner_nocheck", "planner_noform"):
        def generate(prompt, max_tokens):
            return complete(prompt, max_tokens=max_tokens, temperature=0.0, strip=False)

        if mode != "planner_nocheck":
            if mode != "planner_noform" and planner.in_war(messages):
                work, first, wrong = planner.plan_battle(generate, render, messages)
                reply, why = planner.final_reply("", work, messages)
                return reply, first, f"{work} || STILL WRONG: {wrong} || REPLACED: {why}"
            source = [{"role": "user", "content": "\n".join(m["content"] for m in messages if m["role"] == "user")}]
            work, first, fixes = planner.work_with_sums(generate, render(planner.WORK_SYSTEM, source), messages[-1]["content"])
        else:
            work, first = generate(render(planner.WORK_SYSTEM, planner.work_messages(messages)), planner.WORK_TOKENS)
            fixes = []
        voiced, second = complete(render(f"{system}\n\n{planner.voice_instructions(work, messages)}", messages), EVERYDAY, 0.3)
        reply, why = planner.final_reply(voiced, work, messages)
        return reply, first + second, f"{work} || FIXED: {fixes} || VOICED: {voiced} || REPLACED: {why}"
    if mode == "one_pass":
        text, count = complete(render(system + ONE_PASS, messages), max_tokens=260, temperature=0.0)
        return text.split("SAY:")[-1].strip(), count, text
    raise ValueError(mode)


def passes(case, reply):
    # A time may be followed by "pm", and a sum by "k" or a comma.
    need = all(re.search(rf"(?<![\w,.])({group})(?![\d])", reply, re.I) for group in case["need"])
    return need and not any(term.lower() in reply.lower() for term in case["avoid"])


cases = [json.loads(line) for line in open(persona_dir("one_ring") / args.cases, encoding="utf-8") if line.strip()]
totals = {}
for case in cases:
    messages = []
    history = case.get("history", [])
    for index, text in enumerate(history):
        messages.append({"role": "user" if index % 2 == 0 else "assistant", "content": text})
    messages.append({"role": "user", "content": case["q"]})
    print(f"\n[{case['id']}] {case['q']}")
    for mode in args.modes.split(","):
        started = time.time()
        reply, count, working = run(mode, messages)
        ok = passes(case, reply)
        entry = totals.setdefault(mode, {"pass": 0, "tokens": 0, "seconds": 0.0, "most": 0})
        entry["pass"] += ok
        entry["tokens"] += count
        entry["seconds"] += time.time() - started
        entry["most"] = max(entry["most"], count)
        print(f"  {'ok  ' if ok else 'MISS'} {mode} ({count} tok): {reply}")
        if args.show and working:
            print("       working: " + working.replace("\n", " / ")[:1200])
print("\nmode: passed, average tokens, most tokens, average seconds here")
for mode, entry in totals.items():
    print(f"  {mode}: {entry['pass']}/{len(cases)}, {entry['tokens'] / len(cases):.0f}, {entry['most']}, {entry['seconds'] / len(cases):.1f}")
