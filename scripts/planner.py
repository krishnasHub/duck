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
VOICE_NOTE = (
    "You have already worked this out, and the working below is correct. Give the user the answer and the numbers behind it "
    "in one to three short sentences, in your own voice. Keep every number exactly as it is. Don't list the numbers, don't "
    "mention the working, and don't use markdown.\n\n"
)
WORK_TOKENS = 220
MAX_FIXES = 3
WORK_TOKEN_LIMIT = 330
MAX_SPOKEN_WORDS = 60
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


def work_messages(messages):
    """Only what the user said, so the working can't inherit a wrong figure from an earlier reply."""
    said = [m["content"] for m in messages if m["role"] == "user"]
    return [{"role": "user", "content": "\n".join(said)}]


def work_with_sums(generate, prompt, question=""):
    """Write the working, correct the first wrong sum, and let the model carry on from the right number.

    generate(prompt, max_tokens) returns the raw text and how many tokens it took. Stopping at the wrong line matters:
    everything after it was built on the wrong number. Returns the working, the tokens used and the corrections.
    A plain count-back question is answered by code, so it uses no tokens here at all.
    """
    counted = sums.count_back(question)
    if counted:
        return counted, 0, ["counted back by code"]
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
    return clean(parts[-1]) if len(parts) > 1 else ""


def has_new_number(reply, work, messages):
    """Any number in the reply must come from the working or from what the user said."""
    known = numbers_in(work) | numbers_in(" ".join(m["content"] for m in messages if m["role"] == "user"))
    return sorted(numbers_in(reply) - known)


def final_reply(voiced, work, messages):
    """Returns the reply to speak, and why the voiced one was replaced, if it was."""
    found = conclusion(work)
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
