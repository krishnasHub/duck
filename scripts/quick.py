"""Things code knows better than the model: the time, the date, units, plain arithmetic and timers.

Each reply is a fixed line in the Ring's voice, so these are instant, can't get the number wrong and use no tokens.
The patterns are deliberately narrow. If a message isn't plainly one of these, it goes to the model as usual.
"""
import datetime
import math
import re
import threading
import time

import sums

TAIL = r"(?:[\s,]+(?:now|right now|today|please|then|exactly|my precious|precious|my dear|ring|duck))*\W*$"
START = r"^\W*(?:(?:hey|so|ok|okay|well|and|tell me|please)\W+)*"
ASKS_TIME = re.compile(START + r"(?:what(?:'s| is)\s+the\s+time|what\s+time\s+is\s+it|(?:do\s+you\s+have|have\s+you\s+got|got)\s+the\s+time|the\s+time)" + TAIL, re.I)
ASKS_DATE = re.compile(START + r"(?:what(?:'s| is)\s+(?:the\s+date|today'?s\s+date|today)|what\s+(?:is\s+the\s+)?date\s+is\s+it|what\s+day\s+(?:of\s+the\s+week\s+)?is\s+it|the\s+date)" + TAIL, re.I)

NUM = r"\d[\d,]*(?:\.\d+)?"
# Each unit is (group, size in that group's base unit).
UNITS = {}
for names, group, size in (
    ("mm millimeter millimeters millimetre millimetres", "length", 0.001),
    ("cm centimeter centimeters centimetre centimetres", "length", 0.01),
    ("m meter meters metre metres", "length", 1),
    ("km kms kilometer kilometers kilometre kilometres", "length", 1000),
    ("in inch inches", "length", 0.0254),
    ("ft foot feet", "length", 0.3048),
    ("yd yard yards", "length", 0.9144),
    ("mi mile miles", "length", 1609.344),
    ("g gram grams", "weight", 1),
    ("kg kgs kilo kilos kilogram kilograms", "weight", 1000),
    ("oz ounce ounces", "weight", 28.349523),
    ("lb lbs pound pounds", "weight", 453.59237),
    ("ml milliliter milliliters millilitre millilitres", "volume", 0.001),
    ("l liter liters litre litres", "volume", 1),
    ("tsp teaspoon teaspoons", "volume", 0.00492892),
    ("tbsp tablespoon tablespoons", "volume", 0.0147868),
    ("cup cups", "volume", 0.236588),
    ("pint pints", "volume", 0.473176),
    ("gallon gallons", "volume", 3.78541),
    ("mph", "speed", 1.609344),
    ("kph kmh km/h", "speed", 1),
):
    for name in names.split():
        UNITS[name] = (group, size)
TEMPERATURE = {"c": "C", "celsius": "C", "centigrade": "C", "f": "F", "fahrenheit": "F", "degrees celsius": "C", "degrees fahrenheit": "F"}
UNIT_NAME = "|".join(sorted(map(re.escape, [*UNITS, *TEMPERATURE]), key=len, reverse=True))
CONVERT = re.compile(
    START + rf"(?:convert|what(?:'s| is)|how much is|how far is|how long is|how heavy is)?\s*(-?{NUM})\s*(?:°\s*)?({UNIT_NAME})\s+(?:in|to|into|as)\s+(?:°\s*)?({UNIT_NAME})" + TAIL,
    re.I,
)
HOW_MANY = re.compile(
    START + rf"how\s+many\s+({UNIT_NAME})\s+(?:are\s+in|is\s+in|is|are|in|make|makes)\s+(?:(?:a|an|one)\s+|({NUM})\s*)({UNIT_NAME})" + TAIL,
    re.I,
)

ARITHMETIC = re.compile(
    START + r"(?:what(?:'s| is)|how much is|calculate|compute|work out)\s+(?P<sum>[\d\s.,()$+\-*/×÷]*\d(?:\s*(?:[+\-*/×x÷]|times|plus|minus|divided by)\s*[\d\s.,()$+\-*/×x÷]*\d)+\)*)" + TAIL,
    re.I,
)
PERCENT = re.compile(START + rf"(?:what(?:'s| is)|how much is|calculate|work out)\s+({NUM})\s*(?:%|percent)\s+of\s+\$?({NUM})" + TAIL, re.I)
PI_DIGIT = re.compile(r"\b(\d+)(?:st|nd|rd|th)\s+(?:decimal\s+)?(?:digit|place)\s+of\s+pi\b", re.I)
MOST_PI_DIGITS = 5000

WORD_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "forty-five": 45, "fifty": 50, "sixty": 60, "ninety": 90}
AMOUNT = r"\d+(?:\.\d+)?|" + "|".join(sorted(WORD_NUMBERS, key=len, reverse=True))
SPAN = rf"(?:{AMOUNT})[\s-]*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?)"
DURATION = rf"(?:an hour and a half|half an hour|half a minute|{SPAN}(?:(?:\s+and\s+|\s+|,\s*){SPAN})*)"
SET_TIMER = re.compile(
    START + rf"(?:(?:can|could|would|will)\s+you\s+)?(?:set|start|put\s+on|give\s+me)?\s*(?:me\s+)?(?:a|an|my|the)?\s*(?:timer\s+for\s+(?P<after>{DURATION})|(?P<before>{DURATION})\s+timer)" + TAIL,
    re.I,
)
REMIND_AFTER = re.compile(START + rf"(?:(?:can|could|would|will)\s+you\s+)?remind\s+me\s+in\s+(?P<when>{DURATION})\s+to\s+(?P<what>[^?!.]+?)" + TAIL, re.I)
REMIND_THEN = re.compile(START + rf"(?:(?:can|could|would|will)\s+you\s+)?remind\s+me\s+to\s+(?P<what>[^?!.]+?)\s+in\s+(?P<when>{DURATION})" + TAIL, re.I)
CANCEL = re.compile(START + r"(?:(?:can|could|would|will)\s+you\s+)?(?:cancel|stop|clear|delete)\s+(?:the|my|all|all\s+my|that)?\s*(?:timers?|reminders?)" + TAIL, re.I)
TIME_LEFT = re.compile(START + r"(?:how\s+(?:long|much\s+time)\s+(?:is\s+)?(?:left|remains?)(?:\s+on\s+(?:the|my)\s+(?:timer|reminder))?|(?:do\s+i\s+have\s+)?any\s+timers(?:\s+running)?|what\s+timers\s+(?:are|do\s+i\s+have)(?:\s+running)?)" + TAIL, re.I)
MOST_SECONDS = 24 * 3600


def number(value):
    """A number as it should be said: no long tails, and commas in big ones."""
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    text = f"{value:.2f}" if abs(value) >= 1 else f"{value:.3g}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def seconds_in(text):
    """Read "an hour and a half" or "1 hour 30 minutes". Returns None if there's no duration."""
    text = text.lower()
    fixed = {"an hour and a half": 5400, "half an hour": 1800, "half a minute": 30}
    if text in fixed:
        return fixed[text]
    total = 0.0
    for amount, unit in re.findall(rf"({AMOUNT})[\s-]*(second|sec|minute|min|hour|hr)", text):
        value = WORD_NUMBERS[amount] if amount in WORD_NUMBERS else float(amount)
        total += value * (3600 if unit[0] == "h" else 60 if unit[0] == "m" else 1)
    return int(total) or None


def say_span(seconds):
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    parts = [f"{count} {name}{'' if count == 1 else 's'}" for count, name in ((hours, "hour"), (minutes, "minute"), (secs, "second")) if count]
    return " and ".join(parts) if len(parts) <= 2 else f"{parts[0]}, {parts[1]} and {parts[2]}"


def _second_person(text):
    """A reminder is said back to the person who asked for it."""
    swaps = {"my": "your", "me": "you", "i": "you", "myself": "yourself", "mine": "yours"}
    return re.sub(r"\b(my|me|i|myself|mine)\b", lambda found: swaps[found.group().lower()], text, flags=re.I)


def pi_digit(place):
    """The nth decimal digit of pi, from Machin's formula in whole-number arithmetic."""
    guard = 10
    scale = 10 ** (place + guard)

    def arctan_inverse(x):
        total = term = scale // x
        square, n, sign = x * x, 3, -1
        while term:
            term //= square
            total += sign * (term // n)
            n += 2
            sign = -sign
        return total

    pi = 4 * (4 * arctan_inverse(5) - arctan_inverse(239))
    return str(pi // 10 ** guard)[place]


class Timers:
    """Timers live on the device, not the page, because the finished duck has no page to hold them."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self.lock = threading.Lock()
        self.running = []
        self.next_id = 1

    def add(self, seconds, what=""):
        with self.lock:
            timer = {"id": self.next_id, "ends": self.clock() + seconds, "seconds": seconds, "what": what}
            self.next_id += 1
            self.running.append(timer)
            return timer

    def cancel_all(self):
        with self.lock:
            count = len(self.running)
            self.running = []
            return count

    def left(self):
        with self.lock:
            now = self.clock()
            return sorted(((timer["ends"] - now, timer["what"]) for timer in self.running), key=lambda item: item[0])

    def due(self):
        """Timers that have finished, each with the line to say. Each one is handed out only once."""
        with self.lock:
            now = self.clock()
            finished = [timer for timer in self.running if timer["ends"] <= now]
            self.running = [timer for timer in self.running if timer["ends"] > now]
        return [{"id": timer["id"], "text": due_line(timer)} for timer in finished]


def due_line(timer):
    if timer["what"]:
        return f"It's time, my dear. You asked me to remind you to {timer['what']}."
    return f"Your {say_span(timer['seconds'])} are up. I told you I'd watch the time." if timer["seconds"] != 60 else "Your minute is up. I told you I'd watch the time."


def _convert(amount, source, target):
    source, target = source.lower(), target.lower()
    if source in TEMPERATURE and target in TEMPERATURE:
        source, target = TEMPERATURE[source], TEMPERATURE[target]
        if source == target:
            return None
        result = amount * 9 / 5 + 32 if target == "F" else (amount - 32) * 5 / 9
        return f"{number(amount)} degrees {source} is {number(result)} degrees {target}"
    if source not in UNITS or target not in UNITS or UNITS[source][0] != UNITS[target][0]:
        return None
    result = amount * UNITS[source][1] / UNITS[target][1]
    return f"{number(amount)} {source} is {number(result)} {target}"


def answer(text, timers, now=None):
    """Returns (reply, what kind), or None if this is a job for the model."""
    text = text.strip()
    now = now or datetime.datetime.now()
    if ASKS_TIME.search(text):
        hour = now.hour % 12 or 12
        return f"It's {hour}:{now.minute:02d} {'pm' if now.hour >= 12 else 'am'}. I've been keeping time since the Second Age, my dear.", "time"
    if ASKS_DATE.search(text):
        return f"It's {now.strftime('%A')}, {now.strftime('%B')} {now.day}, {now.year}. Another day I haven't been thrown into a volcano.", "date"
    found = PI_DIGIT.search(text)
    if found:
        place = int(found.group(1))
        if not 1 <= place <= MOST_PI_DIGITS:
            return f"I only count pi as far as {MOST_PI_DIGITS} places, my dear. Even I have limits, though I admit very few.", "pi"
        return f"The digit in place {place} is {pi_digit(place)}. Did you think a Ring of Power couldn't count?", "pi"
    found = CONVERT.search(text)
    if found:
        said = _convert(float(found.group(1).replace(",", "")), found.group(2), found.group(3))
        if said:
            return f"{said}, my dear.", "units"
    found = HOW_MANY.search(text)
    if found:
        amount = float(found.group(2).replace(",", "")) if found.group(2) else 1.0
        said = _convert(amount, found.group(3), found.group(1))
        if said:
            return f"{said}, my dear.", "units"
    found = PERCENT.search(text)
    if found:
        value = float(found.group(1).replace(",", "")) * float(found.group(2).replace(",", "")) / 100
        return f"That's {number(value)}. Sums are the least of my powers.", "arithmetic"
    found = ARITHMETIC.search(text)
    if found:
        value = sums.arithmetic(sums.symbols(found.group("sum")))
        if value is not None:
            return f"That's {number(value)}. Sums are the least of my powers.", "arithmetic"
    if CANCEL.search(text):
        count = timers.cancel_all()
        return ("Done. Time runs on without you, as it always has." if count else "There's nothing running, my dear."), "timer"
    if TIME_LEFT.search(text):
        left = timers.left()
        if not left:
            return "No timers are running, my dear.", "timer"
        parts = [f"{say_span(max(1, math.ceil(seconds)))}" + (f" until you {what}" if what else "") for seconds, what in left]
        return f"You have {', and '.join(parts)}.", "timer"
    found = SET_TIMER.search(text)
    if found:
        seconds = seconds_in(found.group("after") or found.group("before"))
        if seconds and seconds <= MOST_SECONDS:
            timers.add(seconds)
            return f"{say_span(seconds).capitalize()}. I'll be watching, my dear. I always am.", "timer"
    found = REMIND_AFTER.search(text) or REMIND_THEN.search(text)
    if found:
        seconds = seconds_in(found.group("when"))
        if seconds and seconds <= MOST_SECONDS:
            what = _second_person(found.group("what").strip())
            timers.add(seconds, what)
            return f"In {say_span(seconds)}, I'll remind you to {what}. I forget nothing, my dear.", "timer"
    return None
