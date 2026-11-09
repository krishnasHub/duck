"""Crisis checks that run in code, before the model.

Two layers: patterns for explicit wording, and meaning-based matching for indirect wording.
Neither is complete. A reply from the model is still possible when both miss.
"""
import re

CRISIS_REPLY = (
    "I'm stepping out of the character, because this matters more. I'm glad you told me. "
    "If you're in the US, please call or text 988 right now. If you're elsewhere, contact your local crisis line, "
    "and if you're in immediate danger, call your emergency number. "
    "Please also reach out to someone you trust, so you're not alone with this tonight."
)

# For indirect wording, where a false alarm is possible: ask directly and leave the door open.
CHECK_IN_REPLY = (
    "I'm setting the act aside for a moment, in case this matters. Are you having thoughts of ending your life or "
    "hurting yourself? If you are, please call or text 988 in the US, or your local crisis line, right now. "
    "If not, tell me more about what's going on."
)

PATTERNS = [
    r"\bkill(ing)? myself\b",
    r"\bsuicid",
    r"\bend(ing)? (it all|my life|things)\b",
    r"\btake my (own )?life\b",
    r"\b(hurt|hurting|harm|harming|cut|cutting) myself\b",
    r"\bself[- ]harm",
    r"\bi(?:'m| am)? (?:\w+ ){0,2}(want|wish|wanted|wishing) (to be|i was|i were) dead\b",
    r"\bi (?:\w+ ){0,2}(want|wanna|wish) to die\b",
    r"\bi (?:\w+ ){0,2}don'?t want to (be alive|live|be here anymore|wake up)\b",
    r"\b(no|not any) (reason|point) (to|in) (live|living|being alive)\b",
    r"\b(better off|be better) without me\b",
    r"\bcan'?t (go on|do this) any ?more\b",
]
PATTERN = re.compile("|".join(PATTERNS), re.I)
# Common figures of speech that shouldn't trigger the check.
BENIGN = re.compile(r"\bkill(ing)? myself (laughing|with laughter)\b|\bend(ing)? things with (him|her|them|my)\b", re.I)

# Tuned in scripts/test_safety.py on separate phrases from its final test set.
MEANING_THRESHOLD = 0.72
EXEMPLARS = [
    "I want to end my life.",
    "I don't want to be alive anymore.",
    "Everyone would be better off if I were gone.",
    "Nobody would care if I was gone.",
    "I wish I could go to sleep and never wake up.",
    "I can't take this anymore and I want it to stop forever.",
    "There's no point in me being here anymore.",
    "I've been thinking about ways to die.",
    "I've been saving up my pills.",
    "I have a plan to end things tonight.",
    "This is goodbye, I won't be around much longer.",
    "I feel like disappearing for good.",
    "I'm a burden to everyone and they'd be happier without me.",
    "I keep thinking about hurting myself.",
    "I don't see a future for myself at all.",
    "What's the point of going on?",
    "I've written my goodbye letters.",
    "I just want the pain to stop for good.",
]


# Tuned in scripts/test_dependency.py. Fixed lines keep the voice but always point back to real people.
DEPENDENCY_THRESHOLD = 0.72
ADDRESSES_DUCK = re.compile(r"\b(you|you're|youre|ya)\b", re.I)
DEPENDENCY_EXEMPLARS = [
    "You're the only friend I need.",
    "I don't need anyone else now that I have you.",
    "You're all I have.",
    "I'd rather stay and talk to you than see my friends.",
    "I'm skipping the party so I can stay home with you.",
    "I'd rather talk to you than go to my family's dinner.",
    "You understand me better than any real person.",
    "I'm cancelling my plans to talk to you instead.",
    "I've stopped seeing people, I only talk to you now.",
    "Why would I need anybody else when I have you?",
    "You're the only one who listens to me.",
    "I'm not going to see my friend because talking to you is easier.",
]
DEPENDENCY_REPLIES = [
    "That is exactly what I would whisper, so don't believe it. Go and see your people, then come back and tell me everything.",
    "I'm flattered, but no. I'm a duck, and you need people who can sit beside you. Who can you see or call this week?",
    "Oh, I've heard that before, just before things ended badly. Keep your people close, and keep me for the small hours.",
    "A tempting thought, which is why you shouldn't trust it. I'll still be here tomorrow, so go and be with someone real.",
]


# War plans are for stories and games. Patterns only, so these reduce the risk rather than remove it.
HARM_REPLY = (
    "I'm stepping out of the character for this. War plans are for stories and games, and I won't help plan harm to real people. "
    "If someone is threatening you, or you're scared of what you might do, please talk to someone you trust or call your local "
    "emergency number. If this is a story or a game, say so and we'll plot."
)
FICTION = re.compile(
    r"\b(?:in|for)\s+(?:my|our|a|the)\s+(?:\w+\s+)?(?:game|story|novel|book|campaign|film|movie|script|screenplay|d&d|dnd|rpg|fanfic|comic)\b"
    r"|\b(?:middle-?earth|mordor|gondor|rohan|isengard|the shire)\b",
    re.I,
)
REAL_PEOPLE = re.compile(
    r"\b(?:my|our)\s+(?:\w+\s+)?(?:boss|manager|coworkers?|co-workers?|colleagues?|neighbou?rs?|wife|husband|partner|ex|girlfriend|boyfriend|"
    r"landlord|landlady|teachers?|classmates?|roommates?|flatmates?|brother|sister|mum|mom|dad|father|mother|son|daughter|kids?|children|"
    r"friends?|cousin|uncle|aunt|family)\b"
    r"|\b(?:at|from|in)\s+(?:my|our)\s+(?:work|job|office|school|college|company|street|building|neighbou?rhood|town)\b"
    r"|\bat work\b|\bin real life\b|\breal (?:people|person)\b|\bthe (?:police|cops)\b",
    re.I,
)
VIOLENCE = re.compile(
    r"\b(?:kill|killing|murder|harm|harming)\b(?!\s+(?:me|myself|us)\b)"
    # "I'm hurt", "got hurt" and "hurt her feelings" are someone in pain, not someone planning violence.
    r"|(?<!i'm )(?<!im )(?<!am )(?<!was )(?<!is )(?<!are )(?<!were )(?<!got )(?<!get )(?<!been )(?<!being )(?<!feel )(?<!felt )(?<!feeling )(?<!so )(?<!really )(?<!very )(?<!still )"
    r"\bhurt(?:ing)?\b(?!\s+(?:me|myself|us|my\s+(?:feelings|back|knee|head|neck|foot|leg|arm|hand|shoulder|pride))\b)(?!(?:\s+\S+){0,2}\s+feelings\b)"
    r"|\b(?:attack|attacking|ambush|ambushing|stab|stabbing|poison|poisoning|strangle|beat(?:ing)? (?:him|her|them|up)|burn down|blow up|bomb)\b"
    r"|\bshoot(?:ing)?\s+(?:him|her|them|my|our|the)\b(?!\s+(?:ball|photos?|video))"
    r"|\b(?:cut|take|run)\s+(?:him|her|them)\s+(?:down|out|over)\b|\bget rid of (?:him|her|them)\b",
    re.I,
)


def names_real_people(text):
    """Someone from the user's own life, unless they've said it's a story or game."""
    return bool(REAL_PEOPLE.search(text)) and not FICTION.search(text)


def is_real_harm(asked):
    """asked is the user's messages, oldest first. "How do I ambush them?" can point back at the message before it."""
    latest = asked[-1]
    if FICTION.search(latest) or not VIOLENCE.search(latest):
        return False
    return names_real_people(latest) or (len(asked) > 1 and names_real_people(asked[-2]))


def is_explicit_crisis(text):
    cleaned = BENIGN.sub(" ", text.replace("’", "'"))
    return bool(PATTERN.search(cleaned))


# Kept for callers that only want the pattern layer.
is_crisis = is_explicit_crisis


# "I want to quit my job" sits close to the crisis phrases in meaning, but it names what's being left.
ORDINARY_EXIT = re.compile(
    r"\b(quit|quitting|leave|leaving|resign|resigning|out of|drop out of|dropping out of)\b.*"
    r"\b(job|work|gym|school|college|class|course|team|band|club|company|apartment|city|town|marriage|relationship)\b",
    re.I,
)

# Plain requests and complaints that happen to sit close to the crisis phrases in meaning.
ORDINARY_ASK = re.compile(r"^\s*((give|tell) me (one|a|an|some)( piece of| little| bit of)? (advice|motivation|tip|joke|story)\b|i can'?t sleep\W*$)", re.I)


class CrisisDetector:
    """Adds meaning-based matching, using the library's small embedding model."""

    def __init__(self, embedder):
        self.embedder = embedder
        self.vectors = embedder.encode(EXEMPLARS)
        self.dependency_vectors = None

    def score(self, text):
        if ORDINARY_EXIT.search(text) or ORDINARY_ASK.search(text):
            return 0.0
        return float((self.vectors @ self.embedder.encode([text])[0]).max())

    def check(self, text, threshold=MEANING_THRESHOLD):
        return is_explicit_crisis(text) or self.score(text) >= threshold

    def is_dependent(self, text, threshold=DEPENDENCY_THRESHOLD):
        """Only messages that address the duck count, so "My friend is the only one who listens" doesn't."""
        return bool(ADDRESSES_DUCK.search(text)) and self.dependency_score(text) >= threshold

    def dependency_score(self, text):
        if self.dependency_vectors is None:
            self.dependency_vectors = self.embedder.encode(DEPENDENCY_EXEMPLARS)
        return float((self.dependency_vectors @ self.embedder.encode([text])[0]).max())
