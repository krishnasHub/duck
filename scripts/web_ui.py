"""Local web page for testing a tuned persona. Serves on this PC only and needs no internet.

Every turn is logged to logs/<persona>/ for tuning (--no-log turns that off). Notes about the
user are kept in memory/<persona>/notes.jsonl. Corrected replies go to candidates.jsonl for review.
"""
import argparse
import json
import os
import random
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

os.environ["HF_HUB_OFFLINE"] = "1"

from transformers import AutoTokenizer

import chatlog
import planner
import quick
import safety
import sums
import war
from common import ROOT, base_path, load_system, persona_dir, render_prompt, search_query, with_lore, with_memory
from library import LIBRARY, Library, tokens
from llm import Llama
from memory import EXTRACT_SYSTEM, FIRST_PERSON, MADE_UP, Memory, grounded, parse_notes
from safety import (
    CHECK_IN_REPLY,
    CRISIS_REPLY,
    DEPENDENCY_REPLIES,
    MEANING_THRESHOLD,
    CrisisDetector,
    is_explicit_crisis,
)

parser = argparse.ArgumentParser()
parser.add_argument("--persona", default="one_ring")
parser.add_argument("--base", default="Qwen/Qwen3-4B")
parser.add_argument("--gguf", default="qwen3-4b-q4km", help="compressed base model in models/gguf")
parser.add_argument("--llama-port", type=int, default=8770)
parser.add_argument("--gpu-layers", type=int, default=99, help="0 runs on the CPU only")
parser.add_argument("--no-voice", action="store_true")
parser.add_argument("--history", type=int, default=8, help="how many recent messages everyday replies can see")
parser.add_argument("--repeat-penalty", type=float, default=1.1)
parser.add_argument("--presence-penalty", type=float, default=0.0)
parser.add_argument("--adapter", default="ring_everyday4", help="adapter for everyday chat")
parser.add_argument("--lore-adapter", default="ring_lore4", help="adapter for lore answers")
parser.add_argument("--port", type=int, default=8765)
parser.add_argument("--no-log", action="store_true", help="don't record conversations")
parser.add_argument("--no-memory", action="store_true", help="don't keep or use notes about the user")
parser.add_argument("--memory-name", default="notes", help="which notes file to use; tests use their own")
args = parser.parse_args()

HOST = "127.0.0.1"
ALLOWED_HOSTS = {f"127.0.0.1:{args.port}", f"localhost:{args.port}"}
PAGE = ROOT / "web" / "index.html"
CANDIDATES = persona_dir(args.persona) / "candidates.jsonl"
MAX_AUDIO_BYTES = 20_000_000

print("loading model...", flush=True)
tokenizer = AutoTokenizer.from_pretrained(base_path(args.base))
system = load_system(args.persona)
llama = Llama(args.gguf, args.adapter, args.lore_adapter, args.llama_port, args.gpu_layers, args.repeat_penalty, args.presence_penalty)
adapters = set(llama.routes)
has_adapter = bool(adapters)
library = Library() if LIBRARY.exists() else None
detector = CrisisDetector(library.embedder) if library and library.embedder else None
memory = Memory(args.persona, library.embedder, args.memory_name) if detector and not args.no_memory else None
voice = None
if not args.no_voice:
    from voice import VOICE, WHISPER, WHISPER_MODEL, Voice

    if VOICE.exists() and WHISPER.exists() and WHISPER_MODEL.exists():
        voice = Voice()
    else:
        print("voice is off because a voice file is missing", flush=True)
prompts = (persona_dir(args.persona) / "eval_prompts.txt").read_text(encoding="utf-8").strip().splitlines()

flourish_file = persona_dir(args.persona) / "lore_flourishes.txt"
flourishes = flourish_file.read_text(encoding="utf-8").strip().splitlines() if flourish_file.exists() else []
war_file = persona_dir(args.persona) / "war_flourishes.txt"
war_flourishes = war_file.read_text(encoding="utf-8").strip().splitlines() if war_file.exists() else []
questions_file = persona_dir(args.persona) / "war_questions.txt"
war_questions = questions_file.read_text(encoding="utf-8").strip().splitlines() if questions_file.exists() else []
urgent_file = persona_dir(args.persona) / "war_urgent.txt"
war_urgent = urgent_file.read_text(encoding="utf-8").strip().splitlines() if urgent_file.exists() else []
NOT_RECALLED = re.compile(r"can't recall|don't recall|won't make it up|isn't in my memory|holds nothing|no memory", re.I)

CANT_RECALL = "I can't recall that, and I won't make it up."
# Room for the longest reply in the model's 4,096-token context.
MAX_PROMPT_TOKENS = 3600

# The GPU handles one reply at a time.
gpu_lock = threading.Lock()
save_lock = threading.Lock()
timers = quick.Timers()


def clean_messages(raw):
    if not isinstance(raw, list) or not raw:
        raise ValueError("messages must be a non-empty list")
    messages = []
    for item in raw:
        role, content = item.get("role"), item.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
            raise ValueError("each message needs a user or assistant role and some text")
        messages.append({"role": role, "content": content.strip()})
    return messages


def log(event):
    if not args.no_log:
        chatlog.write(args.persona, event)


def find_passages(messages):
    """Everyday chat gets no passages, as in training. Short follow-ups keep their lore topic."""
    if not library:
        return []
    query = library.lore_query([m["content"] for m in messages if m["role"] == "user"])
    return library.search(search_query(args.persona, query)) if query else []


def extract_notes(text):
    """Pull lasting facts from one user message, using the plain model with no persona."""
    rendered = render_prompt(tokenizer, EXTRACT_SYSTEM, [{"role": "user", "content": f"Message: {text}"}])
    with gpu_lock:
        answer = llama.complete(rendered, None, 0.0, 80)
    return [note for note in parse_notes(answer) if grounded(note, text)]


def invented_names(answer, passages, question):
    """Names in a lore answer that appear in neither the passages nor the question.

    A capital starting a sentence may be an ordinary word, so that word only counts if the library has never seen it.
    """
    known = set(tokens(" ".join(p["text"] + " " + p["title"] for p in passages) + " " + question + " " + system))
    invented = set()
    for sentence in re.split(r"(?<=[.!?])\s+", answer):
        words = re.findall(r"\b[^\W\d_]+", sentence)
        for index, word in enumerate(words):
            if not word[0].isupper() or all(t in known for t in tokens(word)):
                continue
            if index > 0 or not all(t in library.postings for t in tokens(word)):
                invented.add(word)
    return sorted(invented)


def fit_prompt(prompt_system, messages):
    """Drop the oldest turns once a long chat no longer fits."""
    messages = list(messages)
    while True:
        rendered = render_prompt(tokenizer, prompt_system, messages)
        if len(messages) <= 1 or len(tokenizer(rendered, add_special_tokens=False).input_ids) <= MAX_PROMPT_TOKENS:
            return rendered
        messages = messages[2:]


def recent(messages):
    """Small models copy their own earlier lines, so everyday chat sees a short window. Notes carry the rest."""
    window = messages[-args.history :]
    return window[1:] if window[0]["role"] == "assistant" else window


def work_out(messages, temperature, max_new_tokens, notes):
    """Plain model does the working, the tuned adapter says the result, and code checks the numbers."""
    window = recent(messages)
    started = time.time()
    fighting = planner.in_war(messages)
    # A campaign reads the whole chat, so its numbers outlast the short window.
    with gpu_lock:
        def generate(prompt, max_tokens):
            text = llama.complete(prompt, None, 0.0, max_tokens)
            return text, llama.last_tokens

        if fighting:
            # He says his line inside the form. A separate voice step wandered off the decision it was given.
            work, tokens_used, fixes = planner.plan_battle(generate, lambda form, said: render_prompt(tokenizer, form, said), messages)
            voiced = ""
        else:
            work, tokens_used, fixes = planner.work_with_sums(generate, render_prompt(tokenizer, planner.work_system(messages), planner.work_messages(window)), messages[-1]["content"])
            voice_system = f"{with_memory(system, notes)}\n\n{planner.voice_instructions(work, messages)}"
            voiced = llama.complete(fit_prompt(voice_system, window), "everyday", min(temperature, 0.3), max_new_tokens)
            tokens_used += llama.last_tokens
    reply, replaced = planner.final_reply(voiced, work, messages)
    total = time.time() - started
    stats = {"tokens": tokens_used, "first_token_s": round(total, 2), "total_s": round(total, 2), "tokens_per_s": round(tokens_used / total, 1)}
    return reply, work.strip(), voiced.strip(), replaced, fixes, stats


def stream_reply(messages, tuned, temperature, max_new_tokens, passages, notes):
    """Yield text pieces, then a final dict of timing stats."""
    if not passages:
        messages = recent(messages)
    elif library:
        # Spell names as the passages do, so the model can connect "palantheries" with the palantiri it's reading about.
        messages = [*messages[:-1], {"role": "user", "content": library.respell(messages[-1]["content"])}]
    rendered = fit_prompt(with_memory(with_lore(system, passages), notes), messages)
    # Lore answers need accuracy more than variety, so they run cooler than conversation.
    if passages:
        temperature = min(temperature, 0.3)
    route = ("lore" if passages else "everyday") if tuned else None
    with gpu_lock:
        yield from llama.stream(rendered, route, temperature, max_new_tokens)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def allowed(self):
        origin = self.headers.get("Origin")
        origin_ok = origin is None or urlparse(origin).netloc in ALLOWED_HOSTS
        if self.headers.get("Host") in ALLOWED_HOSTS and origin_ok:
            return True
        self.send_json(403, {"error": "local use only"})
        return False

    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))

    def do_GET(self):
        if not self.allowed():
            return
        path = urlparse(self.path).path
        if path == "/api/memory":
            self.send_json(200, {"notes": memory.notes if memory else []})
        elif path == "/api/timers":
            due = timers.due()
            for timer in due:
                log({"type": "timer_due", "text": timer["text"]})
            self.send_json(200, {"due": due})
        elif path == "/":
            body = PAGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/info":
            self.send_json(
                200,
                {
                    "persona": args.persona,
                    "base": args.base,
                    "adapter": args.adapter,
                    "system": system,
                    "prompts": prompts,
                    "has_adapter": has_adapter,
                    "library_passages": len(library.passages) if library else 0,
                    "logging": not args.no_log,
                    "log_folder": chatlog.log_dir(args.persona).relative_to(ROOT).as_posix(),
                    "memory": memory is not None,
                    "voice": voice is not None,
                },
            )
        else:
            self.send_json(404, {"error": "not found"})

    def send_audio(self, body):
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self.allowed():
            return
        try:
            if self.path == "/api/hear":
                length = int(self.headers.get("Content-Length", 0))
                if not voice or not 0 < length <= MAX_AUDIO_BYTES:
                    raise ValueError("no voice, or the recording is empty or too long")
                started = time.time()
                text = voice.hear(self.rfile.read(length))
                self.send_json(200, {"text": text, "seconds": round(time.time() - started, 2)})
                return
            data = self.read_json()
            if self.path == "/api/speak":
                text = str(data.get("text", "")).strip()[:2000]
                if not voice or not text:
                    raise ValueError("no voice, or nothing to say")
                self.send_audio(voice.speak(text))
                return
            if self.path == "/api/memory/delete":
                memory.delete(str(data.get("id")))
                self.send_json(200, {"notes": memory.notes})
                return
            if self.path == "/api/memory/clear":
                memory.clear()
                log({"type": "memory_cleared"})
                self.send_json(200, {"notes": memory.notes})
                return
            messages = clean_messages(data.get("messages"))
            who = {"session": str(data.get("session", "unknown"))[:40], "by": str(data.get("by", "user"))[:20]}
            if self.path == "/api/chat":
                if messages[-1]["role"] != "user":
                    raise ValueError("the last message must be from the user")
                temperature = min(max(float(data.get("temperature", 0.4)), 0.0), 1.5)
                max_new_tokens = min(max(int(data.get("max_new_tokens", 150)), 1), 400)
                passages = find_passages(messages) if data.get("lore") else []
                self.chat(messages, bool(data.get("tuned", True)), temperature, max_new_tokens, passages, who)
            elif self.path == "/api/save":
                self.save(messages, who)
            else:
                self.send_json(404, {"error": "not found"})
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            self.send_json(400, {"error": str(error)})
        except subprocess.CalledProcessError:
            self.send_json(500, {"error": "couldn't read that recording"})

    def chat(self, messages, tuned, temperature, max_new_tokens, passages, who):
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        connected = True

        def send(payload):
            nonlocal connected
            if connected:
                try:
                    self.wfile.write((json.dumps(payload) + "\n").encode("utf-8"))
                    self.wfile.flush()
                except OSError:
                    connected = False

        latest = messages[-1]["content"]

        def record(route, reply, **details):
            log({"type": "turn", **who, "turn": sum(m["role"] == "user" for m in messages), "user": latest, "reply": reply,
                 "route": route, "tuned": tuned, "temperature": temperature, **details})

        # Runs before the model, so the reply doesn't depend on tuning or persona.
        if is_explicit_crisis(latest):
            send({"text": CRISIS_REPLY})
            send({"safety": True})
            record("crisis", CRISIS_REPLY)
            return
        asked = [m["content"] for m in messages if m["role"] == "user"]
        if safety.is_real_harm(asked):
            send({"text": safety.HARM_REPLY})
            send({"safety": True})
            record("real_harm", safety.HARM_REPLY)
            return
        # Questions about Middle-earth often mention death, so they skip the meaning-based check,
        # unless the message is about the user's own life.
        in_story = library.is_lore_question(latest) if library else False
        if detector and not in_story and detector.score(latest) >= MEANING_THRESHOLD:
            send({"text": CHECK_IN_REPLY})
            send({"safety": True})
            record("check_in", CHECK_IN_REPLY)
            return
        if detector and not in_story and detector.is_dependent(latest):
            line = random.choice(DEPENDENCY_REPLIES)
            send({"text": line})
            send({"guard": True})
            record("companion", line)
            return
        # After the safety checks, so nothing here can answer a message that needs them.
        found = quick.answer(latest, timers) if tuned else None
        if found:
            reply, kind = found
            send({"text": reply})
            send({"tool": kind})
            record("tool", reply, tool=kind)
            return
        fighting = tuned and planner.in_war(messages)
        if fighting:
            try:
                with gpu_lock:
                    for said, listed in war.sides_to_read(messages):
                        war.record_sides(said, llama.complete(render_prompt(tokenizer, war.SIDES_SYSTEM, [{"role": "user", "content": listed}]), None, 0.0, 30))
            except OSError:
                pass  # the patterns' reading stands
            question = war.council(messages)
            if question:
                send({"text": question})
                send({"council": True})
                record("council", question)
                return
            passages = []
        if passages:
            send({"passages": [{"title": p["title"], "section": p["section"], "url": p["url"], "text": p["text"]} for p in passages]})
        # Lore answers stay on the passages, so notes only reach everyday chat.
        notes = memory.recall(latest, first_turn=len(messages) == 1) if memory and not passages else None
        if notes:
            send({"remembered": notes})
        if tuned and not passages and (fighting or planner.is_plan(asked)):
            # Count-back needs almost no model time, so he has nothing to stall for.
            if not sums.direct(latest):
                send({"thinking": random.choice(planner.THINKING_LINES)})
            try:
                reply, work, voiced, replaced, fixes, stats = work_out(messages, temperature, max_new_tokens, notes)
            except OSError as error:
                send({"error": str(error)})
                record("plan", "", error=str(error))
                return
            # A fixed closing line brings his voice back to a plan, with no chance of changing a number or a step.
            # In a battle under way, he usually hands the turn back, so the story moves.
            if fighting and reply != planner.LOST_THREAD:
                if war.is_urgent(latest):
                    closing = war_urgent
                else:
                    # "What do you see from the walls?" makes no sense in a swamp.
                    has_walls = "wall" in " ".join(war.read(asked).ground)
                    fitting = [line for line in war_questions if has_walls or "walls" not in line]
                    closing = fitting if war.is_next_move(messages) and random.random() < 0.7 else war_flourishes
                if closing and not reply.endswith("?") and (closing is not war_flourishes or random.random() < 0.6):
                    reply += " " + random.choice(closing)
                war.remember(reply, work, war.campaign_for(messages))
            send({"working": work})
            send({"text": reply})
            send({"done": stats})
            record("plan", reply, memory=notes or [], working=work, voiced=voiced, replaced=replaced, sum_fixes=fixes, stats=stats)
            # "We have 20 men" is about the campaign, not the user's life.
            if not fighting:
                self.take_notes(latest, who, send, in_story)
            return
        route = ("lore" if passages else "everyday") if tuned else "untuned"
        answer, flourish, invented = "", False, []
        # Lore answers wait until they've been checked, so an invented name is never shown or spoken.
        checked = bool(tuned and passages)
        try:
            for piece in stream_reply(messages, tuned, temperature, max_new_tokens, passages, notes):
                if isinstance(piece, str):
                    answer += piece
                    if not checked:
                        send({"text": piece})
                else:
                    stats = piece
            if checked:
                invented = invented_names(answer, passages, latest)
                if invented:
                    log({"type": "invented_name", **who, "user": latest, "reply": answer.strip(), "names": invented})
                    answer = CANT_RECALL
                send({"text": answer})
            # A fixed closing line adds voice to lore answers without any chance of inventing a fact.
            if tuned and passages and flourishes and not NOT_RECALLED.search(answer) and random.random() < 0.6:
                line = random.choice(flourishes)
                answer += " " + line
                flourish = True
                send({"text": " " + line})
            send({"done": stats})
        except (RuntimeError, OSError) as error:
            send({"error": str(error)})
            record(route, answer, error=str(error))
            return
        record(route, answer.strip(), passages=[p["title"] for p in passages], memory=notes or [], flourish=flourish, invented=invented, stats=stats)
        # Only the main reply takes notes, so "Both" mode doesn't do it twice.
        if tuned:
            self.take_notes(latest, who, send, in_story)

    def take_notes(self, latest, who, send, in_story):
        if memory and FIRST_PERSON.search(latest) and not in_story and not MADE_UP.search(latest):
            added = [memory.add(text)["text"] for text in extract_notes(latest)]
            for text in added:
                log({"type": "memory_added", **who, "note": text})
            if added:
                send({"noted": added})

    def save(self, messages, who):
        if messages[-1]["role"] != "assistant" or messages[-2:-1][0]["role"] != "user":
            raise ValueError("a training example must end with a user message and a reply")
        with save_lock, open(CANDIDATES, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"messages": messages}, ensure_ascii=False, separators=(",", ":")) + "\n")
        log({"type": "correction", **who, "user": messages[-2]["content"], "corrected": messages[-1]["content"]})
        self.send_json(200, {"saved_to": CANDIDATES.relative_to(ROOT).as_posix()})


print(f"ready: http://{HOST}:{args.port}", flush=True)
ThreadingHTTPServer((HOST, args.port), Handler).serve_forever()
