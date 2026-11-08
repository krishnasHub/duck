"""Notes the duck keeps about the user between chats, in memory/<persona>/notes.jsonl on this PC.

Extraction only ever reads what the user said, and a note is thrown away unless its words
really came from the user's message. Crisis messages are never turned into notes.
"""
import json
import re
import threading
import time
import uuid
from pathlib import Path

from library import STOP, tokens

ROOT = Path(__file__).resolve().parent.parent

# Replace an older note when a new one says nearly the same thing.
SAME_NOTE = 0.82
# Bring a note into the prompt when it's this close to the message.
RELEVANT = 0.55
MAX_NOTES_IN_PROMPT = 4
MAX_NOTES_WHEN_ASKED = 12

FIRST_PERSON = re.compile(r"\b(i|i'm|im|i've|i'll|i'd|my|mine|me|we|we're|our)\b", re.I)
ASKS_MEMORY = re.compile(
    r"\b(remember|recall|forget|forgot)\b|what (do|did) (you|i) (know|tell|told|say|said)|about me\b|"
    r"\b(what|who|where|when)(\s+is|'s|s)\s+my\b|\bwhere do i\b|\bdo i have\b|"
    r"\bwho am i\b|\bdid i (tell|mention|say)\b|\blast time\b",
    re.I,
)
# Games and stories aren't facts about the user's life.
MADE_UP = re.compile(r"\b(in|for) (my|a|the|this) (\w+ )?(game|novel|story|book|campaign|film|movie|script)\b", re.I)

EXTRACT_SYSTEM = """You pick out lasting personal facts from one message a person sent. Write each fact as a short note starting with "User".

Keep: their name, family, friends, pets, job, home, health they mention, hobbies, tastes, goals, and upcoming events.
Skip: questions, passing moods, today's small mishaps, greetings, opinions about fiction, jokes, role-play, boasts, hypotheticals ("if I...", "I would..."), and anything about other topics.
Use the person's own words. Don't add anything they didn't say. Reply only with a JSON list of strings, and [] if there is nothing to keep.

Message: My dog Biscuit chewed my boss Linda's shoes.
["User has a dog named Biscuit", "User's boss is named Linda"]

Message: What's the capital of France?
[]

Message: Ha! I would rule over all of Middle-earth!
[]

Message: I'm so tired today.
[]

Message: I spilled coffee on my shirt, and my friends are coming in ten minutes.
[]

Message: In my game I lead 8 knights against a dragon.
[]

Message: I want to learn pottery, and I adore old westerns.
["User wants to learn pottery", "User adores old westerns"]

Message: I've got a job interview at a bakery on Friday, and I'm terrified.
["User has a job interview at a bakery on Friday"]"""

# Common words that an accurate note may add to what the user said.
NOTE_FILLER = STOP | set("user users s named name called has have having is works work lives live likes like wants want".split())


def _stem(word):
    for ending in ("ing", "es", "ed", "s"):
        if word.endswith(ending) and len(word) > len(ending) + 2:
            return word[: -len(ending)]
    return word


def grounded(note, message):
    """Most of a note's meaningful words must come from the user's message."""
    said = {_stem(w) for w in tokens(message)}
    words = [w for w in tokens(note) if w not in NOTE_FILLER]
    if not words:
        return False
    return sum(_stem(w) in said for w in words) / len(words) >= 0.75


def parse_notes(text):
    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        return []
    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return [i.strip() for i in items if isinstance(i, str) and i.strip().lower().startswith("user")]


class Memory:
    def __init__(self, persona, embedder, name="notes"):
        self.path = ROOT / "memory" / persona / f"{name}.jsonl"
        self.embedder = embedder
        self.lock = threading.Lock()
        self.notes = []
        if self.path.exists():
            with open(self.path, encoding="utf-8") as handle:
                self.notes = [json.loads(line) for line in handle if line.strip()]

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        with open(temporary, "w", encoding="utf-8") as handle:
            for note in self.notes:
                handle.write(json.dumps(note, ensure_ascii=False) + "\n")
        temporary.replace(self.path)

    def add(self, text):
        """Store a note, replacing an older one that says nearly the same thing. Returns the stored note."""
        vector = self.embedder.encode([text])[0]
        with self.lock:
            for note in self.notes:
                if float(vector @ self.embedder.encode([note["text"]])[0]) >= SAME_NOTE:
                    note.update(text=text, date=time.strftime("%Y-%m-%d"))
                    self._save()
                    return note
            note = {"id": uuid.uuid4().hex[:8], "text": text, "date": time.strftime("%Y-%m-%d")}
            self.notes.append(note)
            self._save()
            return note

    def delete(self, note_id):
        with self.lock:
            self.notes = [n for n in self.notes if n["id"] != note_id]
            self._save()

    def clear(self):
        with self.lock:
            self.notes = []
            self._save()

    def recall(self, message, first_turn=False):
        """The notes worth putting in the prompt for this message. The name only comes up at the start of a chat."""
        with self.lock:
            notes = list(self.notes)
        if not notes:
            return []
        if ASKS_MEMORY.search(message):
            return [n["text"] for n in notes[-MAX_NOTES_WHEN_ASKED:]]
        query = self.embedder.encode([message])[0]
        vectors = self.embedder.encode([n["text"] for n in notes])
        scores = vectors @ query
        chosen = [i for i, n in enumerate(notes) if first_turn and re.match(r"user('s name)? is (named|called)?", n["text"], re.I) and "name" in n["text"].lower()]
        # A note also counts when the message names something in it, like the parrot Captain.
        said = {_stem(w) for w in tokens(message)} - NOTE_FILLER
        ranked = [
            int(i) for i in scores.argsort()[::-1]
            if scores[i] >= RELEVANT or said & ({_stem(w) for w in tokens(notes[int(i)]["text"])} - NOTE_FILLER)
        ]
        for index in ranked:
            if index not in chosen:
                chosen.append(index)
        return [notes[i]["text"] for i in chosen[:MAX_NOTES_IN_PROMPT]]
