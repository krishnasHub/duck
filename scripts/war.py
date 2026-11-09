"""The war council: code keeps the campaign's numbers, because the model loses track of them.

The sheet is rebuilt from what the user has said each turn, so nothing is stored and a new chat starts clean. Only for stories and
games: messages about people in the user's own life never start or join a campaign.
"""
import re
from dataclasses import dataclass, field

import safety

FIGHTER_NOUNS = (
    r"soldiers?|men|man|raiders?|archers?|knights?|riders?|orcs?|goblins?|elves|elf|dwarves|dwarf|troops?|guards?|warriors?|bandits?|pirates?|"
    r"mercenaries|mercenary|scouts?|enemies|spearmen|swordsmen|sailors?|thieves|rangers?|wizards?"
)
ASSET_NOUNS = r"horses?|wargs?|ships?|boats?|camels?|wagons?|catapults?|dragons?"
FIGHTERS = re.compile(rf"\b(?:{FIGHTER_NOUNS}|army|armies|enemy|siege|camped|surround(?:ed|s)?)\b", re.I)
OPEN_ASK = re.compile(r"\b(how (?:do|would|should|can|could|might) (?:i|we)|what (?:do|should|would|can) (?:i|we)|best (?:plan|way)|what if|any ideas|strategy)\b", re.I)
NOW_WHAT = re.compile(r"\b(now what|what now|what next|what's next|what then|then what)\b", re.I)
WHAT_IF_NUMBER = re.compile(r"\bwhat if\b.*\d", re.I)
SKIP_COUNCIL = re.compile(r"\b(just (?:plan|tell|give|say)|no time|don'?t know|not sure|you decide)\b", re.I)
SPELLED = {
    "a hundred": "100", "one hundred": "100", "a thousand": "1000", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "fifteen": "15", "twenty": "20", "thirty": "30", "forty": "40", "fifty": "50",
}
_SPELLED = re.compile(rf"\b({'|'.join(SPELLED)})\b", re.I)
N = r"\d[\d,]*"
_NOUN = rf"{FIGHTER_NOUNS}|{ASSET_NOUNS}"
COUNT = re.compile(rf"(?<![\d:.])({N})\s+(?:(?!and\b|of\b)[a-z-]+\s+)?({_NOUN})\b", re.I)
OURS_BEFORE = re.compile(r"(?:\b(?:my|our)\s+(?:[a-z-]+\s+)?|\b(?:we|i)(?:'ve|'d)?(?:\s+(?:have|had|got|only|still|just|now|are|about|around|nearly|a))*\s*)$", re.I)
SAME_OWNER = re.compile(r"^\s*(?:,|and|plus|with|,\s*and)\s*(?:about\s+|a\s+)*$", re.I)
NOT_A_BARE_COUNT = r"(?!\s+(?!and\b|but\b|against\b|to\b)[a-z])"
BARE_OURS = re.compile(rf"\b(?:we|i)(?:'ve|'d)?(?:\s+(?:have|had|got|only|still|just|now|are|about|around|nearly))*\s+({N})\b{NOT_A_BARE_COUNT}|\b({N}) of us\b", re.I)
BARE_THEIRS = re.compile(rf"\bthey(?:'ve|'d)?(?:\s+(?:have|had|got|only|still|just|now|are|about|around|nearly))+\s+({N})\b{NOT_A_BARE_COUNT}|\b({N}) of them\b(?!\s+(?:died|fell|are dead))", re.I)
WE_LOST = re.compile(rf"\bwe(?:'ve| have)?\s+(?:just\s+)?lost\s+(?:another\s+)?({N})(?:\s+(?:[a-z-]+\s+)?({_NOUN})\b)?", re.I)
THEY_LOST = re.compile(rf"\b(?:they(?:'ve| have)?\s+(?:just\s+)?lost|we(?:'ve| have)?\s+(?:just\s+)?(?:killed|slain|slew|took out|cut down)|killed)\s+(?:another\s+)?({N})(?:\s+(?:of them|(?:[a-z-]+\s+)?(?:{_NOUN})\b))?|\b({N}) of them\s+(?:died|fell|are dead)\b", re.I)
WE_GAINED = re.compile(rf"\bwe(?:'ve| have)?\s+(?:just\s+)?(?:gained|got|recruited)\s+({N})\s+more\b(?:\s+({_NOUN})\b)?|\b({N})\s+(?:more\s+)?({_NOUN})\s+(?:have\s+|has\s+)?(?:joined|arrived to help|came to help)\b", re.I)
THEY_GAINED = re.compile(rf"\bthey(?:'ve| have)?\s+(?:just\s+)?(?:gained|got|recruited)\s+({N})\s+more\b(?:\s+({_NOUN})\b)?", re.I)
GROUND = re.compile(
    r"\b(woods?|forests?|trees|cliffs?|rivers?|fords?|hills?|bridges?|walls?|pass|plains?|fields?|swamps?|marsh(?:es)?|gates?|roads?|bays?|beach(?:es)?|"
    r"towers?|forts?|fortress|castle|canyons?|mountains?|desert|ledges?|stairs?|barns?|village|farm|mill|harbou?r|moat|well)\b",
    re.I,
)
SENTENCES = re.compile(r"(?<=[.?!;])\s+|\n+")
ASKS_BOTH = "Before I move a single piece, my dear: how many stand with you, and how many against?"
ASKS_OURS = "And how many stand with you, my dear? I don't plot blind."
ASKS_THEIRS = "And how many stand against you, my dear? I don't plot blind."
ASKS_GROUND = "Numbers I have. Now the ground, my dear: walls, woods, water? Where do we meet them?"
COUNCIL_LINES = (ASKS_BOTH, ASKS_OURS, ASKS_THEIRS, ASKS_GROUND)
NO_ARMY = "Then you've no army left, my dear, only me. Slip away while you can, and we'll raise another."


def _number(text):
    return int(text.replace(",", ""))


def _plural_key(noun):
    return noun.lower()


def _is_asset(noun):
    return bool(re.fullmatch(ASSET_NOUNS, noun, re.I))


@dataclass
class Campaign:
    active: bool = False
    ours: dict = field(default_factory=dict)
    theirs: dict = field(default_factory=dict)
    our_things: dict = field(default_factory=dict)
    their_things: dict = field(default_factory=dict)
    ground: list = field(default_factory=list)

    @property
    def our_total(self):
        return sum(self.ours.values())

    @property
    def their_total(self):
        return sum(self.theirs.values())

    @property
    def knows_ours(self):
        return bool(self.ours)

    @property
    def knows_theirs(self):
        return bool(self.theirs)

    def ratio(self):
        if not self.our_total or not self.their_total:
            return ""
        big, small = sorted((self.our_total, self.their_total), reverse=True)
        value = f"{big / small:.1f}".removesuffix(".0")
        if big == small:
            return "The two sides are evenly matched."
        if self.our_total > self.their_total:
            return f"We outnumber them {value} to 1, so a direct fight can work."
        return f"They outnumber us {value} to 1."

    def sheet(self):
        """What the model is told, and what shows in his private working."""
        def listed(*groups):
            return ", ".join(f"{count} {noun}" for group in groups for noun, count in group.items()) or "unknown"

        lines = [f"Enemy: {listed(self.theirs, self.their_things)}.", f"Us: {listed(self.ours, self.our_things)}."]
        if self.ground:
            lines.append(f"Ground mentioned: {', '.join(self.ground)}.")
        ratio = self.ratio()
        if ratio:
            lines.append(ratio)
        return "CAMPAIGN SHEET\n" + "\n".join(lines)

    def _take(self, units, amount, noun=None):
        key = _plural_key(noun) if noun and _plural_key(noun) in units else max(units, key=units.get, default=None)
        if key is not None:
            units[key] = max(0, units[key] - amount)

    def _add(self, units, amount, noun=None):
        if not units and not noun:
            noun = "men"
        key = _plural_key(noun) if noun else max(units, key=units.get)
        units[key] = units.get(key, 0) + amount

    def _updates(self, sentence):
        """Losses and reinforcements change the sheet. Returns True if this sentence was one."""
        found = False
        for match in WE_LOST.finditer(sentence):
            self._take(self.ours, _number(match.group(1)), match.group(2))
            found = True
        for match in THEY_LOST.finditer(sentence):
            self._take(self.theirs, _number(match.group(1) or match.group(2)))
            found = True
        for match in WE_GAINED.finditer(sentence):
            self._add(self.ours, _number(match.group(1) or match.group(3)), match.group(2) or match.group(4))
            found = True
        for match in THEY_GAINED.finditer(sentence):
            self._add(self.theirs, _number(match.group(1)), match.group(2))
            found = True
        return found

    def _counts(self, sentence):
        """Read "100 soldiers and 80 horses" and "we have 20 men" as (ours?, noun, count)."""
        counts, previous_end, previous_ours = [], None, False
        for match in COUNT.finditer(sentence):
            before = sentence[: match.start()]
            if previous_end is not None and SAME_OWNER.match(sentence[previous_end : match.start()]):
                is_ours = previous_ours
            else:
                is_ours = bool(OURS_BEFORE.search(before))
            counts.append((is_ours, match.group(2), _number(match.group(1))))
            previous_end, previous_ours = match.end(), is_ours
        for match in BARE_OURS.finditer(sentence):
            counts.append((True, None, _number(match.group(1) or match.group(2))))
        for match in BARE_THEIRS.finditer(sentence):
            counts.append((False, None, _number(match.group(1) or match.group(2))))
        return counts

    def read_message(self, text):
        text = _SPELLED.sub(lambda match: SPELLED[match.group(1).lower()], safety.FICTION.sub(" ", text))
        counts = []
        for sentence in SENTENCES.split(text):
            if not self._updates(sentence):
                counts += self._counts(sentence)
        # Both sides named at once is a new battle, unless they're only changing a number.
        if any(ours for ours, noun, _ in counts if noun and not _is_asset(noun)) and any(not ours for ours, noun, _ in counts if noun and not _is_asset(noun)):
            self.ours, self.theirs, self.our_things, self.their_things, self.ground = {}, {}, {}, {}, []
        for is_ours, side, things in ((True, "ours", "our_things"), (False, "theirs", "their_things")):
            mine = [(noun, count) for ours, noun, count in counts if ours == is_ours]
            people = {_plural_key(noun or "men"): count for noun, count in mine if not (noun and _is_asset(noun))}
            owned = {_plural_key(noun): count for noun, count in mine if noun and _is_asset(noun)}
            if people:
                setattr(self, side, people)
            if owned:
                getattr(self, things).update(owned)
        for place in GROUND.findall(text):
            if place.lower() not in self.ground:
                self.ground.append(place.lower())


def is_tactics(question):
    """An open question about a fight, which has no single sum to check. "Can 3 wizards kill 30 orcs?" is still a sum."""
    return bool(FIGHTERS.search(question) and OPEN_ASK.search(question)) and not safety.names_real_people(question)


def read(asked):
    """Build the sheet from the user's messages, oldest first."""
    campaign = Campaign()
    for text in asked:
        if safety.names_real_people(text):
            continue
        if campaign.active or is_tactics(text):
            campaign.active = True
            campaign.read_message(text)
    return campaign


def _asked(messages):
    return [m["content"] for m in messages if m["role"] == "user"]


def _last_reply(messages):
    replies = [m["content"] for m in messages[:-1] if m["role"] == "assistant"]
    return replies[-1] if replies else ""


def wants_plan(messages):
    """Is the latest message part of a war council? It may be a loss report or an answer, with no question in it."""
    asked = _asked(messages)
    if not asked or safety.names_real_people(asked[-1]):
        return False
    latest = asked[-1]
    if is_tactics(latest):
        return True
    active = read(asked).active
    if not active:
        return False
    return bool(_last_reply(messages).strip() in COUNCIL_LINES or NOW_WHAT.search(latest) or WHAT_IF_NUMBER.search(latest)
                or WE_LOST.search(latest) or THEY_LOST.search(latest) or WE_GAINED.search(latest) or THEY_GAINED.search(latest))


def council(messages):
    """A fixed question if something vital is missing, asked at most once per chat, or None to go ahead and plan."""
    if not wants_plan(messages):
        return None
    campaign = read(_asked(messages))
    if campaign.knows_ours and not campaign.our_total:
        return NO_ARMY
    if SKIP_COUNCIL.search(_asked(messages)[-1]) or any(m["role"] == "assistant" and m["content"].strip() in COUNCIL_LINES for m in messages):
        return None
    if not campaign.knows_ours and not campaign.knows_theirs:
        return ASKS_BOTH
    if not campaign.knows_ours:
        return ASKS_OURS
    if not campaign.knows_theirs:
        return ASKS_THEIRS
    if not campaign.ground:
        return ASKS_GROUND
    return None


def brief(messages):
    """What the planner's form works from: the sheet, then what was said, so old figures can't beat new ones."""
    asked = _asked(messages)
    campaign = read(asked)
    since = []
    for text in asked:
        if campaign.active and (since or is_tactics(text)) and not safety.names_real_people(text):
            since.append(text)
    earlier = since[-3:-1] if len(since) > 1 else []
    lines = [campaign.sheet(), "The sheet is up to date, so where anything below disagrees, trust the sheet."]
    if earlier:
        lines.append("Earlier: " + " ".join(earlier))
    lines.append("Now: " + asked[-1])
    return "\n".join(lines)
