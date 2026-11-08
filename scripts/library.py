"""Lore search: keywords for exact names, plus embeddings for meaning. Results are merged by rank."""
import difflib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIBRARY = ROOT / "lore" / "library.jsonl"
EMBEDDINGS = ROOT / "lore" / "library_embeddings.npy"
EMBEDDER = ROOT / "models" / "bge-small-en-v1.5"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
STOP = set(
    "a an and are as at be but by did do does for from had has have he her his how i in is it its me my of on or "
    "she that the their them they this to was were what when where which who whom why will with you your".split()
)


# From scripts/router_test.py: catches most lore questions with few everyday ones.
ROUTER_THRESHOLD = 0.65
FACT_THRESHOLD = 0.6
OUT_OF_WORLD = re.compile(
    r"Tolkien|scholar|critic|comment|Shippey|Flieger|Kocher|Letters|publish|edition|novel|author|reader|essay|journal|"
    r"Beowulf|Christian|medieval|Old English|Norse|film|Jackson|translat|illustrat|philolog|chapter|narrative|writes|wrote",
    re.I,
)
FOLLOW_UP = re.compile(r"\b(he|him|his|she|her|hers|they|them|their|it|its|that|those|this|these|there|then)\b", re.I)
# Talk about the user's own plans or fantasies, which is conversation even when it names Middle-earth.
# "I want to know why Gandalf..." is still a lore question, so it's left out.
PERSONAL = re.compile(
    r"\b(i would|i'd|i will|i'll|i shall|i'm going to|i am going to|i'm gonna|i could|i might|if i|what if i|when i|"
    r"should i|can i|could i|how do i|i have|i've got|i only have|we have|my (men|army|city|plan|enemy|enemies|friend|boss|"
    r"life|job|wife|husband|partner|dog|cat|family)|i(?: really)? wanna|i(?: really)? want(?! to (know|hear|learn|understand)))\b",
    re.I,
)
# Calling the duck by its title ("go on, calculate it, one true ring!") is talking to it, not asking about the artefact.
ADDRESSED = re.compile(
    r",\s*(o\s+|oh\s+|my\s+)?(the\s+)?(one\s+)?(true\s+)?(ring|precious)\W*$|"
    r"\byour (favou?rite|opinion|thoughts|view)\b|\bwhat do you think\b|\bdo you (like|love|prefer|miss|enjoy|want)\b",
    re.I,
)
MAX_FOLLOW_UP_WORDS = 14
# "And how many did Sauron use?" names someone new but counts the thing asked about before.
FOLLOW_UP_NUMBER = re.compile(r"^\W*(and\s+)?how many\s+(did|do|does|were|was|are|is|has|had|have)\b", re.I)
# How the user might refer to the Ring's maker when talking to the Ring.
MAKER = re.compile(r"\byour (dark lord|master|maker|creator|lord)\b", re.I)
# How close a misheard or mistyped word must be to a name. It must also start with the same three letters.
SPELLING_MATCH = 0.72
# A word in this many passages is really used in the articles, so it isn't a misspelling.
RARE_WORD_PASSAGES = 3
# Real-world names that the articles mention but that don't make a question about Middle-earth.
NOT_LORE_NAMES = set(
    "american british england english europe france french german germany google january february march april may june "
    "july august september october november december monday tuesday wednesday thursday friday saturday sunday "
    "christian christmas america oxford london paris japan japanese china italy spain russia tom".split()
)
# Words in article titles that are ordinary English, so they don't mark a question as lore.
GENERIC_TITLE_WORDS = set(
    "about after against ages among animals armies armour battle before book books castle characters classical cultural "
    "death decline dreams early england english evil fall father fight friend friends great heroism history home house "
    "illustrating impact influences journey journeys king kings land languages last letters life light list lost mother "
    "music names narrative nature north objects people places poem poems power race realms rings road ruler rulers "
    "sea season short song songs story stories tales themes time tower town tree trees water weapons world writing".split()
)


# Other names people use, mapped to the name the articles mostly use.
ALIASES = {
    "mithrandir": "Gandalf", "olorin": "Gandalf", "stormcrow": "Gandalf", "tharkun": "Gandalf", "incanus": "Gandalf",
    "strider": "Aragorn", "elessar": "Aragorn", "thorongil": "Aragorn", "estel": "Aragorn", "dunadan": "Aragorn",
    "sharkey": "Saruman", "curunir": "Saruman",
    "annatar": "Sauron", "gorthaur": "Sauron", "mairon": "Sauron", "necromancer": "Sauron",
    "melkor": "Morgoth", "bauglir": "Morgoth",
    "smeagol": "Gollum", "turambar": "Túrin", "mormegil": "Túrin",
    "merry": "Meriadoc Brandybuck", "pippin": "Peregrin Took", "sam": "Samwise Gamgee",
    "tinuviel": "Lúthien", "undomiel": "Arwen", "evenstar": "Arwen",
    "ringwraith": "Nazgûl", "ringwraiths": "Nazgûl", "khazad": "Moria", "wormtongue": "Gríma",
    "dimholt": "Paths of the Dead", "ilúvatar": "Eru", "iluvatar": "Eru",
}


# Middle-earth words the articles often write in lowercase, so the capitals rule above misses them.
LORE_WORDS = {"palantir", "palantiri", "palantirs", "silmaril", "silmarils", "mithril", "lembas", "athelas", "balrog", "balrogs"}


def tokens(text):
    """Lowercase and strip accents, so Fëanor and Feanor match."""
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return [word for word in re.findall(r"[a-z0-9]+", plain) if word not in STOP]


class Embedder:
    """Small embedding model, run on the CPU so it doesn't compete with the language model for the GPU."""

    def __init__(self, device="cpu"):
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.torch, self.device = torch, device
        self.tokenizer = AutoTokenizer.from_pretrained(EMBEDDER)
        self.model = AutoModel.from_pretrained(EMBEDDER).to(device).eval()

    def encode(self, texts):
        batch = self.tokenizer(texts, padding=True, truncation=True, max_length=512, return_tensors="pt").to(self.device)
        with self.torch.no_grad():
            pooled = self.model(**batch).last_hidden_state[:, 0]
        return self.torch.nn.functional.normalize(pooled, dim=1).float().cpu().numpy()


class Library:
    def __init__(self, path=LIBRARY, k1=1.5, b=0.75):
        self.passages = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
        self.k1, self.b = k1, b
        self.postings = defaultdict(list)
        self.lengths = []
        for index, passage in enumerate(self.passages):
            # Title words count extra, since a page about Isildur should win for "Isildur".
            words = tokens(passage["text"]) + tokens(passage["title"]) * 3
            self.lengths.append(len(words))
            for word, count in Counter(words).items():
                self.postings[word].append((index, count))
        self.average = sum(self.lengths) / max(len(self.lengths), 1)

        self.names = None
        self.english = None
        self.vectors, self.embedder = None, None
        if EMBEDDINGS.exists() and EMBEDDER.exists():
            import numpy

            vectors = numpy.load(EMBEDDINGS)
            if len(vectors) == len(self.passages):
                self.vectors, self.embedder = vectors, Embedder()

    def respell(self, text):
        """Replace misspelled words with the closest Middle-earth name, so "Galadrial" finds Galadriel.

        A word stays as it is if it's ordinary English, or if it looks more like a misspelling of an English word.
        """
        self._load_names()
        if self.english is None:
            vocabulary = EMBEDDER / "vocab.txt"
            words = vocabulary.read_text(encoding="utf-8").split() if vocabulary.exists() else []
            self.english = {w for w in words if w.isalpha() and len(w) >= 4} - self.names

        def closeness(word, options):
            found = difflib.get_close_matches(word, options, n=1, cutoff=SPELLING_MATCH)
            return (difflib.SequenceMatcher(None, word, found[0]).ratio(), found[0]) if found else (0.0, None)

        def fix(match):
            word = match.group(0)
            found = tokens(word)
            if len(found) != 1 or len(found[0]) < 5 or found[0] in self.names or found[0] in self.english:
                return word
            # The vocabulary lists "tire" but not always "tiring".
            stem = re.sub(r"(ing|ed|es|s|ly|er)$", "", found[0])
            if stem in self.english or stem + "e" in self.english:
                return word
            if len(self.postings.get(found[0], [])) >= RARE_WORD_PASSAGES:
                return word
            start = found[0][:3]
            name_score, name = closeness(found[0], [n for n in self.names if n.startswith(start)])
            english_score, _ = closeness(found[0], [w for w in self.english if w.startswith(start)])
            return name if name and name_score > english_score else word

        return re.sub(r"[^\W\d_]+", fix, text)

    def _load_names(self):
        if self.names is None:
            # A name is a word that the articles always capitalise, like Shadowfax or Eöl, and never write in lowercase.
            # Skip passages about scholarship, so a scholar's first name like Linda doesn't count as lore.
            capitalised, lowercase = Counter(), set()
            for passage in self.passages:
                in_world = not OUT_OF_WORLD.search(passage["text"])
                for word in re.findall(r"(?<=[a-z,;] )[^\W\d_]+", passage["text"]):
                    if word[0].isupper() and not in_world:
                        continue
                    if word[0].isupper():
                        capitalised.update(tokens(word))
                    else:
                        lowercase.update(tokens(word))
            self.names = {w for w, count in capitalised.items() if count >= 2 and w not in lowercase and len(w) > 2}
            self.names -= GENERIC_TITLE_WORDS | NOT_LORE_NAMES
            # "merry" and "sam" are ordinary words or everyday names, so these two aliases don't trigger lore alone.
            self.names |= set(ALIASES) - {"merry", "sam"}
            self.names |= LORE_WORDS

    def is_lore(self, query):
        """Decide whether a question is about Middle-earth: it names something, or it means something close."""
        self._load_names()
        query = MAKER.sub("Sauron", self.respell(query))
        if set(tokens(query)) & self.names:
            return True
        if self.vectors is None:
            return False
        return float((self.vectors @ self.embedder.encode([QUERY_PREFIX + query])[0]).max()) >= ROUTER_THRESHOLD

    def is_personal(self, text):
        return bool(PERSONAL.search(text) or ADDRESSED.search(text))

    def is_lore_question(self, text):
        return self.is_lore(text) and not self.is_personal(text)

    def lore_query(self, asked):
        """Given the user's messages, oldest first, return text to search for, or None if this is conversation.

        A short follow-up like "his sons?" keeps the topic of the latest lore question within the last three messages.
        """
        asked = [MAKER.sub("Sauron", self.respell(text)) for text in asked]
        latest = asked[-1]
        if self.is_personal(latest):
            return None
        # "Your dark lord" alone doesn't say which topic, so a follow-up still carries the earlier question.
        if self.is_lore(latest) and not (len(asked) > 1 and FOLLOW_UP_NUMBER.search(latest)):
            return latest
        # A follow-up asks something. "It's about the budget." is just talk.
        if "?" not in latest or len(latest.split()) > MAX_FOLLOW_UP_WORDS:
            return latest if self.is_lore(latest) else None
        if not FOLLOW_UP.search(latest) and not FOLLOW_UP_NUMBER.search(latest):
            return None
        for earlier in reversed(asked[-4:-1]):
            if self.is_lore_question(earlier):
                # "It" after talk of the Ring means the Ring. The rest of that question would only pull search off course.
                if re.search(r"\bring\b", earlier, re.I) and re.search(r"\b(it|its)\b", latest, re.I):
                    return f"{latest} One Ring"
                return f"{earlier} {latest}"
        return latest if self.is_lore(latest) else None

    def keyword_ranking(self, query, limit):
        scores = defaultdict(float)
        total = len(self.passages)
        for word in set(tokens(query)):
            found = self.postings.get(word, [])
            idf = math.log(1 + (total - len(found) + 0.5) / (len(found) + 0.5))
            for index, count in found:
                norm = count + self.k1 * (1 - self.b + self.b * self.lengths[index] / self.average)
                scores[index] += idf * count * (self.k1 + 1) / norm
        return sorted(scores, key=scores.get, reverse=True)[:limit]

    def meaning_ranking(self, query, limit):
        similarity = self.vectors @ self.embedder.encode([QUERY_PREFIX + query])[0]
        return similarity.argsort()[::-1][:limit].tolist()

    def search(self, query, top=4, per_title=2, mode="hybrid", pool=40):
        """mode is keyword, meaning or hybrid. Hybrid falls back to keywords without embeddings."""
        extra = [ALIASES[word] for word in tokens(query) if word in ALIASES]
        if extra:
            query = f"{query} {' '.join(extra)}"
        if mode != "keyword" and self.vectors is None:
            mode = "keyword"
        rankings = []
        if mode in ("keyword", "hybrid"):
            rankings.append((1, self.keyword_ranking(query, pool)))
        if mode in ("meaning", "hybrid"):
            rankings.append((1, self.meaning_ranking(query, pool)))
        # A key fact that closely matches gets its own slot, on top of the search results.
        results, used, seen = [], Counter(), set()
        fact_slots = 0
        if mode == "hybrid" and self.vectors is not None:
            facts = [i for i, p in enumerate(self.passages) if p.get("fact")]
            if facts:
                scores = self.vectors[facts] @ self.embedder.encode([QUERY_PREFIX + query])[0]
                best = int(scores.argmax())
                if scores[best] >= FACT_THRESHOLD:
                    results.append(self.passages[facts[best]])
                    seen.add(facts[best])
                    fact_slots = 1
        limit = top + fact_slots
        # Take turns: each method keeps its best results, so one can't bury what only the other finds.
        positions = [0] * len(rankings)
        while len(results) < limit and any(p < len(r) for p, (_, r) in zip(positions, rankings)):
            for which, (_, ranking) in enumerate(rankings):
                while positions[which] < len(ranking):
                    index = ranking[positions[which]]
                    positions[which] += 1
                    passage = self.passages[index]
                    if index not in seen and used[passage["title"]] < per_title:
                        seen.add(index)
                        used[passage["title"]] += 1
                        results.append(passage)
                        break
                if len(results) == limit:
                    break
        return results
