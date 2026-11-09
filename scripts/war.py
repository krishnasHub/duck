"""The war council: code keeps the campaign's numbers, because the model loses track of them.

The sheet is rebuilt from what the user has said each turn, so nothing is stored and a new chat starts clean. Only for stories and
games: messages about people in the user's own life never start or join a campaign.
"""
import re
from dataclasses import dataclass, field

import safety

FIGHTER_NOUNS = (
    r"soldiers?|men|man|raiders?|archers?|knights?|riders?|orcs?|goblins?|elves|elf|dwarves|dwarf|troops?|guards?|warriors?|bandits?|pirates?|"
    r"mercenaries|mercenary|scouts?|enemies|spearmen|swordsmen|sailors?|thieves|rangers?|wizards?|cavalry|cavilry|cavalrymen|horsemen|infantry"
)
ASSET_NOUNS = r"horses?|wargs?|ships?|boats?|camels?|wagons?|catapults?|dragons?"
FIGHTERS = re.compile(rf"\b(?:{FIGHTER_NOUNS}|army|armies|enemy|siege|camped|surround(?:ed|s)?)\b", re.I)
OPEN_ASK = re.compile(
    r"\b(how (?:do|would|should|can|could|might) (?:i|we|you)|what (?:do|should|would|can) (?:i|we|you)|best (?:plan|way)|what if|any ideas|strategy|"
    r"(?:is there )?(?:something|anything) (?:i|we) can do|help me (?:with )?(?:a )?(?:plan|fight|defend|hold|win))\b",
    re.I,
)
ASKS_FOR_HELP = re.compile(r"\b(?:something|anything) (?:i|we) can do|\bhelp me\b|\bstrategy\b|\bwhat (?:do|should|can) (?:i|we)\b|\bhow (?:do|should|can) (?:i|we)\b", re.I)
NOTES = (
    (re.compile(r"\bs(?:ie|ei)ge (?:engines?|weapons?|towers?|machines?)\b", re.I), "The enemy has siege weapons."),
    (re.compile(r"\bno help\b|\bhelp (?:isn'?t|is not) coming\b", re.I), "No help is coming."),
)
UNSTATED_LOSS_NOTE = "The enemy has taken losses, number unknown, so their count may be high."
THE_REST = re.compile(r"\b(?:the )?rest (?:of them )?are ([a-z]+(?: [a-z]+)?)", re.I)
NOW_WHAT = re.compile(r"\b(now what|what now|what next|what's next|what then|then what)\b", re.I)
WHAT_IF_NUMBER = re.compile(r"\bwhat if\b.*\d", re.I)
SKIP_COUNCIL = re.compile(r"\b(just (?:plan|tell|give|say)|no time|don'?t know|not sure|you decide|no idea|you tell me)\b", re.I)
MAX_COUNCIL_QUESTIONS = 2
SPELLED = {
    "a hundred": "100", "one hundred": "100", "a thousand": "1000", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "fifteen": "15", "twenty": "20", "thirty": "30", "forty": "40", "fifty": "50",
}
_SPELLED = re.compile(rf"\b({'|'.join(SPELLED)})\b", re.I)
N = r"\d[\d,]*"
_NOUN = rf"{FIGHTER_NOUNS}|{ASSET_NOUNS}"
COUNT = re.compile(rf"(?<![\d:.])({N})\s+(?:are\s+)?((?:(?!and\b|of\b|are\b|with\b)[a-z-]+\s+)?(?:{_NOUN}))\b", re.I)
WITH_KIT = re.compile(rf"(?<![\d:.])({N})\s+(with\s+[a-z]+(?:\s+and\s+[a-z]+)?)\b", re.I)
# A smaller number for the enemy is only a new total if they say so. Otherwise it's a part of what's already known.
NEW_TOTAL = re.compile(r"\b(only|now|actually|there are|what if)\b", re.I)
UNSTATED_LOSSES = re.compile(r"\b(?:took out|killed|shot|cut down|slew|slain)\b.*\b(?:good number|many|some|several|lots|a few|plenty|dozens)\b", re.I)
WON =re.compile(r"\b(?:we (?:won|have won)|victory is ours|(?:they|the \w+|their army) (?:have |has )?(?:fled|retreated|surrendered|ran away|broke and ran|are gone|are fleeing|are retreating)|they're (?:gone|fleeing|retreating))\b", re.I)
WAR_TALK_WORDS = re.compile(r"\b(attack\w*|charg\w*|arrows?|withdr\w+|retreat\w*|ambush\w*|flank\w*|breach\w*|shot|killed)\b", re.I)
OURS_BEFORE = re.compile(r"(?:\b(?:my|our)\s+(?:[a-z-]+\s+)?|\b(?:we|i)(?:'ve|'d)?(?:\s+(?:have|had|got|only|still|just|now|are|about|around|nearly|a))*\s*)$", re.I)
# Words between two counts that mean the second belongs to someone else. "10 men with me, 3 archers" has none of them.
OTHER_SIDE = re.compile(r"\b(against|versus|vs|fight\w*|fac\w+|caught|attack\w*|chas\w+|surround\w*|hold\w*|they|them|their|enemy|while|but|are|is|have|has|had|see|saw)\b", re.I)
PLAIN_ADJECTIVE = re.compile(r"^(?:more|about|around|other|extra)\s+", re.I)
GENERIC_NOUNS = {None, "men", "man", "soldiers", "troops", "warriors"}
NOT_A_BARE_COUNT = r"(?!\s+(?!and\b|but\b|against\b|to\b)[a-z])"
BARE_OURS = re.compile(rf"\b(?:we|i)(?:'ve|'d)?(?:\s+(?:have|had|got|only|still|just|now|are|about|around|nearly))*\s+({N})\b{NOT_A_BARE_COUNT}|\b({N}) of us\b", re.I)
BARE_THEIRS = re.compile(rf"\bthey(?:'ve|'d)?(?:\s+(?:have|had|got|only|still|just|now|are|about|around|nearly))+\s+({N})\b{NOT_A_BARE_COUNT}|\b({N}) of them\b(?!\s+(?:died|fell|are dead))", re.I)
NAMED_PART = re.compile(rf"\b({N}) of (us|them) are ((?:[a-z-]+\s+)?(?:{_NOUN}))\b", re.I)
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
ASKS_AGAIN = "Noted, my dear. But I can't move a single piece until I know your numbers. How many?"
COUNCIL_LINES = (ASKS_BOTH, ASKS_OURS, ASKS_THEIRS, ASKS_GROUND, ASKS_AGAIN)
NO_ARMY = "Then you've no army left, my dear, only me. Slip away while you can, and we'll raise another."
VICTORY_LINE = "Ha! The field is yours, my dear. Songs will be sung, and every one of them will leave me out. Now, shall we discuss the crown?"


def _number(text):
    return int(text.replace(",", ""))


def _plural_key(noun):
    return PLAIN_ADJECTIVE.sub("", noun.lower())


def _is_asset(noun):
    # "3 with horses" and "3 on horses" are people. "3 horses" are not.
    return not noun.lower().startswith(("with ", "on ")) and bool(re.fullmatch(ASSET_NOUNS, noun.split()[-1], re.I))


def _people(mine, rest_label):
    """Turn one side's counts into units. "100 of them, 20 archers, 30 strong men" is a total and its parts, not 150 people."""
    if not mine:
        return {}
    first_noun, first_count = mine[0]
    parts = mine[1:]
    if parts and (first_noun is None or first_noun.split()[-1].lower() in GENERIC_NOUNS) and sum(count for _, count in parts) <= first_count:
        units = {}
        for noun, count in parts:
            key = _plural_key(noun or "men")
            units[key] = units.get(key, 0) + count
        left = first_count - sum(count for _, count in parts)
        if left:
            units[rest_label or f"other {_plural_key(first_noun or 'men')}"] = left
        return units
    units = {}
    for noun, count in mine:
        key = _plural_key(noun or "men")
        # A second bare "20 of them" is a part of something unnamed, so the last one mustn't simply win.
        units[key] = units.get(key, 0) + count if noun else count
    return units


@dataclass
class Campaign:
    active: bool = False
    ours: dict = field(default_factory=dict)
    theirs: dict = field(default_factory=dict)
    our_things: dict = field(default_factory=dict)
    their_things: dict = field(default_factory=dict)
    ground: list = field(default_factory=list)
    notes: list = field(default_factory=list)

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
        lines += self.notes
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
        """Read "100 soldiers and 80 horses" and "we have 20 men" as (ours?, noun, count), in the order they were said."""
        found, previous_end, previous_ours = [], None, False
        for match in COUNT.finditer(sentence):
            before = sentence[: match.start()]
            if OURS_BEFORE.search(before):
                is_ours = True
            elif previous_end is not None and not OTHER_SIDE.search(sentence[previous_end : match.start()]):
                is_ours = previous_ours
            else:
                is_ours = False
            found.append((match.start(), is_ours, match.group(2), _number(match.group(1))))
            previous_end, previous_ours = match.end(), is_ours
        for match in WITH_KIT.finditer(sentence):
            found.append((match.start(), bool(OURS_BEFORE.search(sentence[: match.start()])) or previous_ours, match.group(2).lower(), _number(match.group(1))))
        named = {}
        for match in NAMED_PART.finditer(sentence):
            named[match.start()] = match.group(3)
        for match in BARE_OURS.finditer(sentence):
            found.append((match.start(), True, named.get(match.start()), _number(match.group(1) or match.group(2))))
        for match in BARE_THEIRS.finditer(sentence):
            found.append((match.start(), False, named.get(match.start()), _number(match.group(1) or match.group(2))))
        return [item[1:] for item in sorted(found, key=lambda item: item[0])]

    def read_message(self, text):
        text = _SPELLED.sub(lambda match: SPELLED[match.group(1).lower()], safety.FICTION.sub(" ", text))
        counts = []
        for sentence in SENTENCES.split(re.sub(r"!+\s+", ". ", text)):
            if self._updates(sentence):
                continue
            found = self._counts(sentence)
            # "We have 10 men. 3 with horses, 4 archers" carries on our list, if it fits inside the number just given.
            if found and counts and counts[-1][0] and not any(ours for ours, _, _ in found) and not OTHER_SIDE.search(sentence) \
                    and sum(count for _, _, count in found) <= counts[-1][2]:
                found = [(True, noun, count) for _, noun, count in found]
            counts += found
        # Both sides named at once is a new battle, unless they're only changing a number.
        if any(ours for ours, noun, _ in counts if noun and not _is_asset(noun)) and any(not ours for ours, noun, _ in counts if noun and not _is_asset(noun)):
            self.ours, self.theirs, self.our_things, self.their_things, self.ground, self.notes = {}, {}, {}, {}, [], []
        rest = THE_REST.search(text)
        for is_ours, side, things in ((True, "ours", "our_things"), (False, "theirs", "their_things")):
            mine = [(noun, count) for ours, noun, count in counts if ours == is_ours]
            people = _people([item for item in mine if not (item[0] and _is_asset(item[0]))], rest.group(1).lower() if rest and not is_ours else None)
            owned = {_plural_key(noun): count for noun, count in mine if noun and _is_asset(noun)}
            is_a_part = not is_ours and self.their_total > sum(people.values()) and not NEW_TOTAL.search(text)
            if people and not is_a_part:
                setattr(self, side, people)
            if owned:
                getattr(self, things).update(owned)
        for place in GROUND.findall(text):
            if place.lower() not in self.ground:
                self.ground.append(place.lower())
        for pattern, note in NOTES:
            if pattern.search(text) and note not in self.notes:
                self.notes.append(note)
        if UNSTATED_LOSSES.search(text) and UNSTATED_LOSS_NOTE not in self.notes:
            self.notes.append(UNSTATED_LOSS_NOTE)


def _adds_to_the_campaign(text):
    """A new fact or a plea for help carries on the war, even with no question. Dinner plans don't."""
    probe = Campaign()
    spelled = _SPELLED.sub(lambda match: SPELLED[match.group(1).lower()], text)
    return bool(probe._counts(spelled) or FIGHTERS.search(text) or WAR_TALK_WORDS.search(text) or GROUND.search(text) or any(pattern.search(text) for pattern, _ in NOTES))


def is_tactics(question):
    """An open question about a fight, which has no single sum to check. "Can 3 wizards kill 30 orcs?" is still a sum."""
    return bool(FIGHTERS.search(question) and OPEN_ASK.search(question)) and not safety.names_real_people(question)


def read(asked):
    """Build the sheet from the user's messages, oldest first."""
    campaign = Campaign()
    for text in asked:
        if safety.names_real_people(text):
            continue
        if campaign.active and WON.search(text):
            campaign = Campaign()
            continue
        if campaign.active or is_tactics(text):
            campaign.active = True
            campaign.read_message(text)
    return campaign


def just_won(messages):
    asked = _asked(messages)
    return bool(asked) and bool(WON.search(asked[-1])) and read(asked[:-1]).active


def is_next_move(messages):
    """Under way, a whole new plan each turn goes nowhere. Only a what-if or a new request for a plan starts over."""
    asked = _asked(messages)
    latest = asked[-1]
    if WHAT_IF_NUMBER.search(latest) or re.search(r"\b(strategy|new plan|whole plan)\b", latest, re.I):
        return False
    started = False
    for message in messages[:-1]:
        if message["role"] == "user" and is_tactics(message["content"]):
            started = True
        elif started and message["role"] == "assistant" and message["content"].strip() not in COUNCIL_LINES:
            return True
    return False


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
    if just_won(messages):
        return True
    if is_tactics(latest):
        return True
    active = read(asked).active
    if not active:
        return False
    return bool(_last_reply(messages).strip() in COUNCIL_LINES or NOW_WHAT.search(latest) or WHAT_IF_NUMBER.search(latest)
                or WE_LOST.search(latest) or THEY_LOST.search(latest) or WE_GAINED.search(latest) or THEY_GAINED.search(latest)
                or _adds_to_the_campaign(latest) or re.search(r"\b(?:something|anything) (?:i|we) can do\b", latest, re.I))


def council(messages):
    """A fixed question if something vital is missing, asked at most once per chat, or None to go ahead and plan."""
    if not wants_plan(messages):
        return None
    if just_won(messages):
        return VICTORY_LINE
    campaign = read(_asked(messages))
    if campaign.knows_ours and not campaign.our_total:
        return NO_ARMY
    asked_so_far = sum(m["role"] == "assistant" and m["content"].strip() in COUNCIL_LINES for m in messages)
    if SKIP_COUNCIL.search(_asked(messages)[-1]) or asked_so_far >= MAX_COUNCIL_QUESTIONS:
        return None
    if asked_so_far and not (campaign.knows_ours and campaign.knows_theirs):
        return ASKS_AGAIN
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
    earlier = since[-5:-1] if len(since) > 1 else []
    lines = [campaign.sheet(), "The sheet is up to date, so where anything below disagrees, trust the sheet."]
    if earlier:
        lines.append("Earlier: " + " ".join(earlier))
    lines.append("Now: " + asked[-1])
    return "\n".join(lines)
