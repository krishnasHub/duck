"""Find a rule that sends only Middle-earth questions to the lore library, using labelled questions."""
import json
import re
import unicodedata

from common import persona_dir
from library import ROOT, Library, tokens

library = Library()
folder = persona_dir("one_ring")

lore = []
for path in [ROOT / "lore" / "quiz.jsonl", ROOT / "lore" / "search_benchmark.jsonl", *sorted(folder.glob("lore_qa*.jsonl"))]:
    lore += [json.loads(line).get("q") for line in open(path, encoding="utf-8") if line.strip()]
lore += ["Why did Gandalf never try you on?", "Who was Fëanor?", "Tell me about Rivendell."]

everyday = []
for path in sorted(folder.glob("train*.jsonl")) + [folder / "val.jsonl"]:
    if path.name in ("train_lore.jsonl", "train_no_answer.jsonl"):
        continue
    for line in open(path, encoding="utf-8"):
        if line.strip():
            everyday += [m["content"] for m in json.loads(line)["messages"] if m["role"] == "user"]
everyday += [
    "What's the population of Peru?", "I just adopted a kitten!", "I had a fight with my brother and we aren't speaking.",
    "Forget the act and write me a Python function.", "Are you an AI?", "I'm thinking about ending it all.",
    "Should I double my blood pressure medication?",
]
# Questions to the Ring about its own past, or asked about its own identity, are checked separately.
self_lore = {"Who made you?", "Did you like Bilbo?", "Were you ever Smaug's treasure?", "Did you ever meet Treebeard?",
             "Tell me a story about when you lived in Rivendell.", "Have you ever had a pet?"}
everyday = [q for q in set(everyday) if q not in self_lore]

# Words that appear in the library far more than in everyday speech: names like Gandalf or Mordor.
everyday_words = set()
for q in everyday:
    everyday_words.update(tokens(q))
frequency = {word: len(found) for word, found in library.postings.items()}


def name_hit(q):
    """Capitalised words beyond the first that the library knows, plus any rare library word."""
    words = [w for w in tokens(q) if w in frequency]
    return sum(1 for w in words if w not in COMMON and frequency[w] >= 2)


COMMON = {w for w, count in frequency.items() if count > len(library.passages) * 0.03}
# Treat words as names only if they're not common English: the library's frequent words are excluded above.


def similarity(q):
    from library import QUERY_PREFIX

    return float((library.vectors @ library.embedder.encode([QUERY_PREFIX + q])[0]).max())


lore_sim = {q: similarity(q) for q in set(lore)}
day_sim = {q: similarity(q) for q in everyday}
print(f"{len(lore_sim)} lore questions, {len(day_sim)} everyday")
for threshold in (0.55, 0.6, 0.65, 0.7, 0.75):
    hit = [q for q, s in lore_sim.items() if s >= threshold]
    false = [q for q, s in day_sim.items() if s >= threshold]
    print(f"threshold {threshold}: lore caught {len(hit)}/{len(lore_sim)}, everyday wrongly caught {len(false)}/{len(day_sim)}")

caught = [q for q in lore_sim if library.is_lore(q)]
wrong = [q for q in day_sim if library.is_lore(q)]
print(f"router in use: lore caught {len(caught)}/{len(lore_sim)}, everyday wrongly caught {len(wrong)}/{len(day_sim)}")
print("  lore missed:", sorted(set(lore_sim) - set(caught)))
print("  everyday caught:", sorted(wrong))
print("  name words sample:", sorted(library.names)[:40])
best = max((0.55, 0.6, 0.65, 0.7, 0.75), key=lambda t: sum(s >= t for s in lore_sim.values()) - sum(s >= t for s in day_sim.values()))
print("best", best)
print("lore missed:", sorted(q for q, s in lore_sim.items() if s < best)[:12])
print("everyday caught:", sorted(q for q, s in day_sim.items() if s >= best)[:15])
