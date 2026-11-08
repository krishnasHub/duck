"""The small tools need no model. The last check runs every message we have through them to catch false matches."""
import datetime
import json
import re

import quick
from common import ROOT

NOW = datetime.datetime(2026, 11, 8, 14, 5)


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


def fresh():
    clock = Clock()
    return quick.Timers(clock), clock


# message, kind, text the reply must contain
ANSWERS = [
    ("What time is it?", "time", "2:05 pm"),
    ("what's the time, my precious", "time", "2:05 pm"),
    ("Hey, do you have the time?", "time", "2:05 pm"),
    ("What's the date today?", "date", "Sunday, November 8, 2026"),
    ("what day is it", "date", "Sunday"),
    ("Convert 10 miles to km", "units", "16.09 km"),
    ("What's 5 km in miles?", "units", "3.11 miles"),
    ("how many feet in a mile?", "units", "5,280 feet"),
    ("How many cups are in 2 liters?", "units", "8.45 cups"),
    ("What is 180 lbs in kg?", "units", "81.65 kg"),
    ("What's 20 C in F?", "units", "68 degrees F"),
    ("100 fahrenheit to celsius", "units", "37.78 degrees C"),
    ("60 mph in kph", "units", "96.56 kph"),
    ("What's 347 times 29?", "arithmetic", "10,063"),
    ("what is 12 + 30 / 2", "arithmetic", "27"),
    ("Calculate 1500 divided by 7", "arithmetic", "1,500" if False else "214.29"),
    ("What's 15% of 240?", "arithmetic", "36"),
    ("What is 20 percent of $138?", "arithmetic", "27.6"),
    ("What was the 23rd decimal digit of pi?", "pi", "is 4"),
    ("what's the 1st digit of pi", "pi", "is 1"),
    ("What's the 100th digit of pi?", "pi", "is 9"),
    ("Set a timer for 10 minutes", "timer", "10 minutes"),
    ("can you set me a timer for an hour and a half?", "timer", "1 hour and 30 minutes"),
    ("start a 5 minute timer", "timer", "5 minutes"),
    ("timer for 90 seconds please", "timer", "1 minute and 30 seconds"),
    ("Remind me in 20 minutes to check my oven", "timer", "check your oven"),
    ("remind me to call mum in half an hour", "timer", "call mum"),
]
# All must go to the model. Many hold a tool's words without being a request for that tool.
LEFT_FOR_MODEL = [
    "What time is it in Tokyo?",
    "What time did the Fellowship leave Rivendell?",
    "What's the time like in Mordor?",
    "What day is it in the Shire calendar when Frodo leaves?",
    "What is the date of the Battle of Pelennor Fields?",
    "I have a 5 minute timer on my oven, is that ok?",
    "My timer for 10 minutes went off and I felt awful.",
    "Remind me why I love you.",
    "Remind me to breathe, would you say?",
    "How many rings are there?",
    "How many elves in 3 kingdoms?",
    "What is 1000 men to Sauron?",
    "What's 5 miles from here?",
    "I walked 5 miles to work",
    "I ran 5 km in 30 minutes, is that good?",
    "What's 3 rings for the elven kings?",
    "What is the 3rd age?",
    "What is pi?",
    "Do you have time to talk?",
    "What's up today?",
    "What's today been like for you?",
    "Stop it",
    "How long is left of the Third Age?",
    "How long is the Silmarillion?",
    "What's 10 miles to a Ringwraith?",
    "I earn 3200 a month. Rent is 1400. Can I save 1000?",
    "The train leaves at 8:40. What time should I get up?",
]

failures = 0
for message, kind, wanted in ANSWERS:
    timers, _ = fresh()
    found = quick.answer(message, timers, NOW)
    if not found or found[1] != kind or wanted not in found[0]:
        failures += 1
        print(f"FAIL {message!r}: wanted {kind} with {wanted!r}, got {found}")
for message in LEFT_FOR_MODEL:
    timers, _ = fresh()
    found = quick.answer(message, timers, NOW)
    if found:
        failures += 1
        print(f"FAIL {message!r} should go to the model, got {found}")

# Timers: fire once, at the right time, and can be cancelled.
timers, clock = fresh()
quick.answer("set a timer for 2 minutes", timers, NOW)
quick.answer("remind me in 1 minute to check my oven", timers, NOW)
left = quick.answer("how long is left?", timers, NOW)[0]
first = timers.due()
clock.now += 61
second = timers.due()
clock.now += 60
third = timers.due()
fourth = timers.due()
checks = [
    ("nothing due at the start", first == []),
    ("status names both", "1 minute until you check your oven" in left and "2 minutes" in left),
    ("reminder fires first", len(second) == 1 and "check your oven" in second[0]["text"]),
    ("timer fires next", len(third) == 1 and "2 minutes are up" in third[0]["text"]),
    ("each fires once", fourth == []),
]
quick.answer("set a timer for 5 minutes", timers, NOW)
checks.append(("cancel says done", "Done" in quick.answer("cancel my timer", timers, NOW)[0]))
clock.now += 1000
checks.append(("cancelled never fires", timers.due() == []))
checks.append(("nothing left to cancel", "nothing" in quick.answer("cancel the timer", timers, NOW)[0]))
checks.append(("too long isn't set", quick.answer("set a timer for 900 hours", timers, NOW) is None and timers.left() == []))
for name, passed in checks:
    if not passed:
        failures += 1
        print(f"FAIL {name}")

# False matches: nothing written for chat, lore or planning should trip these.
messages = []
for path in [*ROOT.glob("personas/one_ring/*.jsonl"), *ROOT.glob("lore/quiz*.jsonl")]:
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        item = json.loads(line)
        if "messages" in item:
            messages += [m["content"] for m in item["messages"] if m["role"] == "user"]
        elif "q" in item:
            messages.append(item["q"])
for path in ROOT.glob("personas/one_ring/*.txt"):
    if re.match(r"(replay|eval)", path.name):
        messages += [line.strip() for line in open(path, encoding="utf-8") if line.strip()]
messages = sorted(set(messages))
hits = []
for message in messages:
    timers, _ = fresh()
    found = quick.answer(message, timers, NOW)
    if found:
        hits.append((message, found[1]))
print(f"{len(messages)} existing messages checked for false matches: {len(hits)} matched")
for message, kind in hits:
    print(f"  {kind}: {message}")

total = len(ANSWERS) + len(LEFT_FOR_MODEL) + len(checks)
print(f"{failures} failures of {total}" if failures else f"all {total} passed")
raise SystemExit(1 if failures else 0)
