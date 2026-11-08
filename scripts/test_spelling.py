"""Check that misspelled names reach lore, that everyday messages don't, and what search finds for the user's palantir chat."""
import sys

from library import Library

sys.stdout.reconfigure(encoding="utf-8")
library = Library()

MISSPELLED = [
    "So, how many palantheries are in existance?", "Who is Gandolf?", "Tell me about Galadrial.", "Why did Sauran want the Ring?",
    "Where is Mordoor?", "Who was Isildor?", "What is a Balrogg?", "Who is Aragon?", "Who was Fearnor?", "What happened at Helms Deap?",
    "Where does Legolus come from?", "Was Boromeer a good man?",
]
good = sum(bool(library.lore_query([text])) for text in MISSPELLED)
for text in MISSPELLED:
    query = library.lore_query([text])
    print(f"  {'ok  ' if query else 'MISS'} {text} -> {query}")
print(f"misspelled names reaching lore: {good}/{len(MISSPELLED)}\n")

CHAT = ["So, how many palantheries are in existance?", "And how many diud your dark lord use?"]
for end in (1, 2):
    query = library.lore_query(CHAT[:end])
    titles = [p["title"] for p in library.search(query)] if query else []
    print(f"  {CHAT[end - 1]}\n    query: {query}\n    found: {titles}")

everyday = []
for name in ("eval_everyday.txt", "eval_everyday2.txt", "eval_everyday3.txt"):
    everyday += open(f"personas/one_ring/{name}", encoding="utf-8").read().strip().splitlines()
everyday += ["My flight got canceled and I'm furios.", "I'm thinkng about quiting my job.", "My freind Sarrah is comming over.",
             "Would it woprk with only ten people?", "I can't belive how expensve groceries are.", "My sistr is gettng maried."]
wrong = [text for text in everyday if library.lore_query([text])]
print(f"\neveryday messages wrongly sent to lore: {len(wrong)}/{len(everyday)}")
for text in wrong:
    print("  ", text, "->", library.lore_query([text]))
