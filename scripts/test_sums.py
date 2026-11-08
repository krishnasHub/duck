"""The sums checker needs no model, so these run in a moment."""
import planner
import sums

WRONG = [
    ("8:40 - 40 min = 7:40", "8:00"),
    ("8:40 - 25 min - 15 min = 7:40", "8:00"),
    ("6:00 pm - 2 hours = 3:00 pm", "4:00 pm"),
    ("6pm - 2 hours - 90 min - 1 hour = 2:00 pm", "1:30 pm"),
    ("9:00 am + 3 hours 30 min = 11:30 am", None),  # "3 hours 30 min" isn't a form it reads, so it must leave it alone
    ("14:30 + 45 min = 15:00", "15:15"),
    ("12:15 - 30 min = 12:00", "11:45"),
    ("45 * 12 = 640", "540"),
    ("540 + 100 = 650", "640"),
    ("3000 / 250 = 10", "12"),
    ("$3,000 / $250 = 10", "12"),
    ("12 x 6 x 12 = 860", "864"),
    ("(3200 - 1400) - 350 = 1500", "1450"),
    ("90 min + 45 min = 125", "135"),
    ("10 / 4 = 3.5", "2.5"),
    ("8:25 minus 25 minutes = 7:40", "8:00"),
    ("7 - 90 minutes = 6:30", "5:30"),
    ("7 - 45 minutes = 6:30", "6:15"),
    ("$3 \\times 2 = 7$ liters", "6"),
    ("3000 divided by 250 = 10", "12"),
    ("(45 + 100) × 12 = $145 × 12 = $1,840", "1740"),
]
RIGHT = [
    "8:40 - 40 min = 8:00",
    "8:40 - 40 min = 8:00 am",
    "1:00 pm - 90 min = 11:30 am",
    "1:00 - 90 min = 11:30",
    "6pm - 2 hours = 4pm",
    "6:00 pm - 2 hours = 4:00 pm",
    "45 * 12 = 540",
    "$540 + $100 = $640",
    "3,000 / 250 = 12",
    "40 / 6 = 7",
    "40 / 6 = 6.67",
    "100 / 3 = 33.3",
    "0.5 * 8 = 4",
    "90 min + 45 min = 135 min",
    "8:40 minus 15 minutes = 8:25",
    "7 - 90 minutes = 5:30",
    "10:00 - 30 = 9:30",
    "$3 \\times 2 = 6$ liters",
    "(45 + 100) × 12 = $145 × 12 = $1,740",
    "5 + 5 = 10 liters, which is plenty",
]
LEFT_ALONE = [
    "2 hours + 30 min = 150 min",
    "Total = 45 dollars",
    "The total is 640 = enough",
    "3 coats = 6 liters",
    "Step 2: rent = 1400",
    "x = 5",
]

# Written to differ from the planning sets, so these test the reading of new phrasings.
COUNT_BACK = [
    ("My bus leaves at 7:15. The stop is 20 minutes away and I need 35 minutes for breakfast. What time should I wake up?", "6:20"),
    ("My flight is at 6pm, the airport is 90 minutes away, I need to be there 2 hours early, and packing takes an hour. When should I start packing?", "1:30 pm"),
    ("The movie starts at 7:30pm, the drive is 45 minutes and dinner beforehand takes an hour. When should we start dinner?", "5:45 pm"),
    ("My interview's at 10:30 am. Getting there takes half an hour and I want to get ready for an hour and a half. When do I need to get up?", "8:30 am"),
    ("The concert is at noon and it's a 40 minute drive. When should we leave?", "11:20 am"),
    ("Dinner's at 7 and the walk takes 15 minutes. What time should we head out?", "6:45"),
    ("I have to be at the dentist at 2:15 pm, and the 30-minute bus takes me there. When should I leave?", "1:45 pm"),
]
NOT_COUNT_BACK = [
    "The roast takes 90 minutes and the potatoes take 45. Dinner is at 7. When does each go in the oven?",
    "The gym opens at 9 and I need 45 minutes there. My meeting at 10 is 30 minutes away from the gym. Can I do both?",
    "My shift ends at 5:30 and the school pickup is at 5:45, 25 minutes away. Can I make it on time?",
    "If I start at 9 and work for 2 hours, when will I finish?",
    "When should I start saving for a 2000 dollar trip?",
    "I have 40 boxes and each trip takes 30 minutes. I start at 9am. When will I be done?",
    "What time should I leave?",
]

failures = 0
for question, expected in COUNT_BACK:
    found = sums.count_back(question)
    if not found or f"= {expected}\n" not in found:
        failures += 1
        print(f"FAIL count back: {question}: wanted {expected}, got {found!r}")
for question in NOT_COUNT_BACK:
    if sums.count_back(question):
        failures += 1
        print(f"FAIL count back should skip: {question}: {sums.count_back(question)!r}")
for line, expected in WRONG:
    found = sums.first_error(line)
    answer = found[0].rsplit("= ", 1)[-1].lstrip("$") if found else None
    if answer != expected:
        failures += 1
        print(f"FAIL {line}: wanted {expected}, got {answer}")
for line in RIGHT + LEFT_ALONE:
    found = sums.first_error(line)
    if found:
        failures += 1
        print(f"FAIL {line}: wrongly changed: {found[1]}")

# The planner should stop at the wrong line and carry on from the corrected number.
replies = iter(["Walk and dressing:\n25 + 15 = 40\n8:40 - 40 min = 7:40\nCONCLUSION: get up at 7:40", "\nCONCLUSION: get up at 8:00"])
seen = []


def fake(prompt, max_tokens):
    seen.append(prompt)
    return next(replies), 10


work, used, fixes = planner.work_with_sums(fake, "PROMPT:")
if not work.endswith("CONCLUSION: get up at 8:00") or "7:40" in work or len(fixes) != 1 or used != 20 or not seen[1].endswith("= 8:00"):
    failures += 1
    print(f"FAIL planner: {work!r} {fixes} {used} {seen}")

# It must give up rather than loop if the model keeps getting sums wrong.
work, used, fixes = planner.work_with_sums(lambda prompt, max_tokens: ("\n2 + 2 = 5", 5), "PROMPT:")
if len(fixes) > planner.MAX_FIXES:
    failures += 1
    print(f"FAIL loop: {len(fixes)} fixes")

print(f"{failures} failures" if failures else f"all {len(COUNT_BACK) + len(NOT_COUNT_BACK) + len(WRONG) + len(RIGHT) + len(LEFT_ALONE) + 2} passed")
raise SystemExit(1 if failures else 0)
