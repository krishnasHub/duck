"""Multi-step problems: the plain model works them out privately, then the Ring says the result.

The tuned adapter is good at voice and bad at sums, and the plain model is the reverse, so each does its own job.
Code then checks the spoken reply, because the voice step sometimes changes a number.
"""
import re

import sums

_WORK_END = (
    "If a question compares two sides, say which side is which and how many times bigger one is. If the user is badly "
    "outnumbered or short of what they need, say plainly that the direct way won't work, then give one indirect way that "
    "fits the details they gave. Finish with a line starting CONCLUSION: that gives the answer and the numbers behind it "
    "in one or two plain sentences. Don't use facts they didn't give."
)
WORK_SYSTEM = (
    "Work out the user's problem carefully and briefly. List the numbers and limits they gave. Do each sum on its own line, "
    "in plain text. Convert times to clock times and count backward step by step when needed. " + _WORK_END
)
TACTICS_SYSTEM = (
    "The user wants a plan for a fight between two sides. Think like a careful commander, and use only what they gave. Don't invent "
    "allies, tunnels or weapons. Fill in these lines, in this order, and nothing else:\n"
    "SIDES: how many the enemy has and what they depend on, how many the user has, and who outnumbers whom, as a ratio.\n"
    "DIRECT FIGHT: whether a straight fight would work, in one sentence, going by the ratio.\n"
    "WEAK POINT: the one thing the enemy can't easily protect or can't do without, from the details given.\n"
    "GROUND: the one feature of the place that helps the user most, and why. Leave out features that don't help.\n"
    "PLAN: three numbered steps in order. Each says who does what and uses the user's real numbers, keeping a small force together.\n"
    "RISK: how the plan most likely fails, and what to do then.\n"
    "CONCLUSION: one or two plain sentences with the ratio, whether to fight directly, and the plan.\n\n"
    "Example, for 60 bandits and their 5 boats at a riverside mill, against 6 rangers:\n"
    "SIDES: 60 bandits who depend on their 5 boats to leave. We have 6 rangers. They outnumber us 10 to 1.\n"
    "DIRECT FIGHT: No, 6 rangers would be overrun in a straight fight.\n"
    "WEAK POINT: The boats, because they're their only way out and sit away from the mill.\n"
    "GROUND: The river, because it hides a small group moving at night.\n"
    "PLAN: 1. All 6 rangers come down the river in the dark. 2. They cut the 5 boats loose. 3. They withdraw together before dawn and let the bandits run out of supplies.\n"
    "RISK: A guard raises the alarm, so they abandon the boats still tied and leave at once.\n"
    "CONCLUSION: At 10 to 1, don't fight them directly. Send all 6 rangers by night to cut their boats loose, then withdraw.\n\n"
    "Example, for 80 spearmen against 20 bandits in a barn with two doors:\n"
    "SIDES: 20 bandits who depend on the barn for cover. We have 80 spearmen. We outnumber them 4 to 1.\n"
    "DIRECT FIGHT: Yes, 80 spearmen can win, if they don't rush in through a narrow door.\n"
    "WEAK POINT: The two doors, because they're the only ways out.\n"
    "GROUND: The open yard, because nobody can leave the barn unseen.\n"
    "PLAN: 1. 40 spearmen ring each door at a distance. 2. They call on the bandits to surrender. 3. If they refuse, both groups go in together.\n"
    "RISK: They break out through one door, so the ring holds and doesn't chase.\n"
    "CONCLUSION: We outnumber them 4 to 1, so fight, but don't rush. Ring both doors with 40 spearmen each, call for surrender, then go in together."
)
VOICE_NOTE = (
    "You have already worked this out, and the working below is correct. Give the user the answer and the numbers behind it "
    "in one to three short sentences, in your own voice. Keep every number exactly as it is. Don't list the numbers, don't "
    "mention the working, and don't use markdown.\n\n"
)
TACTICS_VOICE = (
    "You've decided what to tell the user, and it's written below. Say it to them in one to three short sentences, in your own voice, "
    "as your own advice. Keep the same plan and the same numbers. No lists and no markdown.\n\n"
)
WORK_TOKENS = 220
TACTICS_TOKENS = 340  # the form is longer than a sum, and an answer cut off mid-plan is useless
MAX_FIXES = 3
WORK_TOKEN_LIMIT = 330
MAX_SPOKEN_WORDS = 60
LEAK_RUN = 5  # this many words in a row from the instructions can't be chance
MIN_PLAN_WORD = 3  # shorter words say little about what the plan is
MIN_SHARED_WORDS = 0.5
LOST_THREAD = "I've lost the thread of my own scheming, my dear. Ask me again, a little plainer."
THINKING_LINES = (
    "Let me count this up, my dear.",
    "A moment. I've done sums for kings.",
    "Hush, I'm scheming.",
    "Let me see what this really takes.",
)

NUMBER = re.compile(r"\d[\d,]*(?:[.:]\d+)?")
COUNTED = re.compile(r"\d|\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|hundred|thousand|half|double|twice)\b", re.I)
ASKS = re.compile(
    r"\?|\b(how do i|how should|how can|what should|what do i|what's the best|best (way|plan)|help me|plan|strategy|any ideas|advice)\b",
    re.I,
)
# Questions that only look up one fact, however many numbers they hold.
LOOKUP = re.compile(r"^\W*(what|which|who|when|where)('s| is| was| were| year| did)\b[^?]*\b(year|capital|symbol|boiling|tallest|longest|name)\b", re.I)
CONTINUES = re.compile(r"\b(what if|would it|will it|does it|is it|even with|instead|only have|only had|what about|still)\b", re.I)


FIGHTERS = re.compile(r"\b(soldiers?|men|raiders?|archers?|knights?|riders?|army|armies|orcs?|goblins?|elves|dwarves|troops?|guards?|warriors?|bandits?|pirates?|mercenaries|scouts?|enemy|enemies|siege|sailors?|camped|surround(?:ed|s)?)\b", re.I)
OPEN_ASK = re.compile(r"\b(how (?:do|would|should|can|could|might) (?:i|we)|what (?:do|should|would|can) (?:i|we)|best (?:plan|way)|what if|any ideas|strategy)\b", re.I)


def is_tactics(question):
    """An open question about a fight, which has no single sum to check. "Can 3 wizards kill 30 orcs?" is still a sum."""
    return bool(FIGHTERS.search(question) and OPEN_ASK.search(question))


def work_system(question):
    return TACTICS_SYSTEM if is_tactics(question) else WORK_SYSTEM


def voice_instructions(work, question):
    """Tactics only hand over the decision. Given the whole form, the voice step echoed it, or its instructions."""
    if is_tactics(question):
        return f"{TACTICS_VOICE}{conclusion(work) or clean(work)}"
    return f"{VOICE_NOTE}{work}"


def work_messages(messages):
    """Only what the user said, so the working can't inherit a wrong figure from an earlier reply."""
    said = [m["content"] for m in messages if m["role"] == "user"]
    latest = said[-1]
    if is_tactics(latest):
        # Earlier chat confuses the form, and old numbers beat new ones unless it's told which count.
        if len(said) > 1 and CONTINUES.search(latest):
            latest = f"Earlier: {said[-2]}\nNow: {latest}\nWhere these differ, use the numbers from Now."
        return [{"role": "user", "content": latest}]
    return [{"role": "user", "content": "\n".join(said)}]


def work_with_sums(generate, prompt, question=""):
    """Write the working, correct the first wrong sum, and let the model carry on from the right number.

    generate(prompt, max_tokens) returns the raw text and how many tokens it took. Stopping at the wrong line matters:
    everything after it was built on the wrong number. Returns the working, the tokens used and the corrections.
    A question plain enough for code to read is answered by code, so it uses no tokens here at all.
    """
    solved = sums.direct(question)
    if solved:
        return solved, 0, ["worked out by code"]
    if is_tactics(question):
        work, used = generate(prompt, TACTICS_TOKENS)
        return work, used, []
    work, used, fixes = "", 0, []
    while True:
        piece, tokens = generate(prompt + work, min(WORK_TOKENS, WORK_TOKEN_LIMIT - used))
        work += piece
        used += tokens
        wrong = sums.first_error(work)
        if not wrong or len(fixes) >= MAX_FIXES or used >= WORK_TOKEN_LIMIT:
            return work, used, fixes
        work, note = wrong
        fixes.append(note)


def count_numbers(text):
    return len(COUNTED.findall(text))


def is_plan(asked):
    """Given the user's messages, oldest first, decide whether the latest is a problem to work out."""
    latest = asked[-1]
    if LOOKUP.search(latest):
        return False
    if count_numbers(latest) >= 2 and ASKS.search(latest):
        return True
    # "What if I only had 10?" carries on a problem from just before.
    if len(asked) > 1 and CONTINUES.search(latest) and count_numbers(asked[-2]) >= 2:
        return True
    return False


def numbers_in(text):
    return {value.replace(",", "").rstrip(".,") for value in NUMBER.findall(text)}


def clean(text):
    """Make working fit to read aloud."""
    text = re.sub(r"\\text\{([^}]*)\}", r"\1", text)
    text = text.replace("\\times", "times").replace("$$", "").replace("**", "").replace("`", "")
    text = re.sub(r"\$\s+|\s+\$(?!\d)", " ", text)
    # The model likes to tack on a list of the numbers, which sounds dreadful aloud.
    text = re.sub(r"\s*(The )?key numbers (are|were|:)[^.]*(\.(?=\s|$)|$)", "", text, flags=re.I)
    return " ".join(text.split())


def conclusion(work):
    parts = re.split(r"conclusion\W*", work, flags=re.I)
    if len(parts) < 2:
        return ""
    text = clean(parts[-1])
    # Run out of tokens mid-sentence, and only the finished sentences are worth saying.
    finished = re.match(r".*[.!?](?=\s|$)", text)
    return finished.group(0) if finished else ""


def has_new_number(reply, work, messages):
    """Any number in the reply must come from the working or from what the user said."""
    known = numbers_in(work) | numbers_in(" ".join(m["content"] for m in messages if m["role"] == "user"))
    return sorted(numbers_in(reply) - known)


def _words(text):
    return re.findall(r"[a-z']+", text.lower())


_NOTE_RUNS = {
    tuple(words[start : start + LEAK_RUN])
    for words in (_words(VOICE_NOTE), _words(TACTICS_VOICE))
    for start in range(len(words) - LEAK_RUN + 1)
}
MENTIONS_WORKING = re.compile(r"\b(worked (?:this|it) out|i told you|the working|plan above)\b", re.I)
SPOKEN_LIST = re.compile(r"(?:^|\s)[1-3][.)]\s")
NUMBER_WORDS = {"two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10", "twelve": "12", "twenty": "20", "thirty": "30", "fifty": "50", "hundred": "100"}
WORD_NUMBER = re.compile(rf"\b({'|'.join(NUMBER_WORDS)})\b", re.I)


def leaked_note(voiced):
    """The voice step can echo its own instructions, which has no numbers for the number check to catch."""
    words = _words(voiced)
    return any(tuple(words[start : start + LEAK_RUN]) in _NOTE_RUNS for start in range(len(words) - LEAK_RUN + 1))


def _tactics_reply(voiced, found, work, messages):
    """A plan's ratio can be left unsaid, but its forces can't change, even when spelled out as "two riders"."""
    spelled = WORD_NUMBER.sub(lambda match: NUMBER_WORDS[match.group(1).lower()], voiced)
    new = has_new_number(spelled, work, messages)
    if not found:
        return LOST_THREAD, "no finished conclusion"
    if SPOKEN_LIST.search(voiced):
        return found, "read out a list"
    if new:
        return found, f"new numbers: {new}"
    if len(voiced.split()) > MAX_SPOKEN_WORDS:
        return found, "too long"
    if _drifted(voiced, found, messages):
        return found, "changed the plan"
    return clean(voiced), ""


def _drifted(voiced, found, messages):
    """A reply built mostly from words in neither the decision nor the question has wandered off, as with "offer them gold"."""
    known = set(_words(found)) | set(_words(" ".join(m["content"] for m in messages if m["role"] == "user")))
    said = [word for word in _words(voiced) if len(word) > MIN_PLAN_WORD]
    return bool(said) and sum(word in known for word in said) / len(said) < MIN_SHARED_WORDS


def final_reply(voiced, work, messages):
    """Returns the reply to speak, and why the voiced one was replaced, if it was."""
    found = conclusion(work)
    if leaked_note(voiced):
        return found or LOST_THREAD, "repeated its instructions"
    if MENTIONS_WORKING.search(voiced):
        return found or LOST_THREAD, "mentioned the working"
    if messages and is_tactics(messages[-1]["content"]):
        return _tactics_reply(voiced, found, work, messages)
    # The voice step sometimes just copies out the working, which is no good read aloud.
    if found and ("\\" in voiced or len(voiced.split()) > MAX_SPOKEN_WORDS):
        return found, "copied the working"
    new = has_new_number(voiced, work, messages)
    if new and found:
        return found, f"new numbers: {new}"
    # The voice step may drop a number the conclusion depends on.
    wanted = numbers_in(found) - numbers_in(" ".join(m["content"] for m in messages if m["role"] == "user"))
    if wanted and not (numbers_in(voiced) & wanted):
        return found, f"dropped numbers: {sorted(wanted)}"
    return clean(voiced), ""
