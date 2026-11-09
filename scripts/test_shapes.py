"""Planning questions code can read directly: costs over time, and how many packs to buy. No model needed.

Every number that matters is checked, and anything not plainly the shape must return None so the model handles it.
"""
import json
import sys

import planner
import sums
from common import ROOT

# (question, numbers that must be in the answer, word for who wins or the verdict)
COSTS = [
    ("A gym costs 45 dollars a month with a 100 dollar joining fee. Classes elsewhere cost 12 dollars each and I go 6 times a month. Over a year, which is cheaper?", ["640", "864", "224"], "gym"),
    ("Phone plan A is 30 dollars a month with no fee. Plan B is 20 dollars a month plus a 150 dollar activation fee. Over 2 years, which is cheaper?", ["720", "630", "90"], "plan b"),
    # Fresh wordings, written before the code.
    ("Service X is $15 per month. Service Y is $10 per month with a $40 signup fee. Which is cheaper over 6 months?", ["90", "100", "10"], "service x"),
    ("Internet from Acme costs 60 a month, and Internet from Bolt costs 50 a month with a 200 installation fee. Over 18 months, which costs less?", ["1080", "1100", "20"], "acme"),
    ("The first locker is $25/month plus a $50 deposit. The second locker is $30/month. Which one is cheaper over a year?", ["350", "360", "10"], "first locker"),
    ("A bus pass costs 70 a month. Taxis cost 9 each and I take 10 a month. Which is cheaper over three months?", ["210", "270", "60"], "bus pass"),
    ("Plan A is 40 dollars a month and Plan B is 40 dollars a month. Over a year, which is cheaper?", ["480"], "same"),
]
PACKS = [
    ("I'm hosting 18 people. Each cake serves 8 and costs 22 dollars. I've got 50 dollars. Is that enough?", ["3", "66", "16"], "short"),
    ("I have 24 guests. Each pizza feeds 3 people and costs 15 dollars. My budget is 100 dollars. Will that cover it?", ["8", "120", "20"], "short"),
    # Fresh wordings, written before the code.
    ("There are 30 kids at the picnic. A tray of sandwiches feeds 7 and costs $12. How many trays do I need and what will it cost?", ["5", "60"], ""),
    ("We're 11 people. One pie serves 4 and costs 9 dollars. I have 40 dollars. Can I afford it?", ["3", "27"], "enough"),
    ("I invited 16 friends. Every box of doughnuts feeds 8 and costs $14, and my budget is $28. Is that enough?", ["2", "28"], "enough"),
]
# Declining is fine, because the model takes over. A wrong answer isn't. The first ten scored 5 right, 4 declined, 1 wrong on first sight,
# and the wrong one led to the rule that every number must be used. The last six were written after that and not used to change the code.
BLIND = [
    ("Bank one has a 12 dollar monthly charge. Bank two charges 5 dollars a month with a 90 dollar account opening fee. Which is cheaper over 2 years?", ["288", "210"], "bank two"),
    ("Lunch out costs 11 dollars each and I eat out 8 times a month. A meal kit costs 70 dollars a month. Which is cheaper over 4 months, and would you pick it for a family of 5?", ["352", "280"], "meal kit"),
    ("The red van costs $300 a month with a $500 deposit and the blue van costs $350 a month. Which costs less over 10 months?", ["3500"], "same"),
    ("I'm cooking for 7 friends plus 2 kids. A lasagne feeds 4 and costs 16 dollars. How many do I need?", ["3", "48"], ""),
    ("There are 21 people coming. Each platter serves 5 people and costs $30, and I have $200 but must keep $50 for drinks. Is that enough?", ["5", "150"], "enough"),
    ("Each jug serves 6 and costs 4 dollars. We're 13 people. How much will it cost?", ["3", "12"], ""),
    ("Membership one runs $80 per month. Membership two runs $65 per month but has a $250 startup fee. Which is less expensive over 2 years?", ["1920", "1810"], "membership two"),
    ("Renting a scooter costs 8 dollars a ride and I'd ride 15 times a month. Owning a scooter costs 400 dollars up front and 20 dollars a month. Which is cheaper over 12 months?", ["1440", "640"], "owning"),
    ("Cloud storage A costs $9.99 a month. Cloud storage B costs $7.50 a month with a one-time charge of $20. Which is the better deal over a year?", ["119.88", "110"], "storage b"),
    ("My old car insurance is 110 a month. A new policy is 95 a month, plus a 60 dollar fee to switch. For 6 months, which is cheaper?", ["660", "630"], "new policy"),
    ("A monthly train ticket is 120 dollars per month. Single tickets are 6 dollars each and I take 22 trips a month. Which is cheaper over 5 months?", ["600", "660"], "train ticket"),
    ("I'm feeding 25 people. A pot of chili serves 6 and costs 18 dollars. I only have 80 dollars. Is that enough?", ["5", "90", "10"], "short"),
    ("We are 9 adults going camping. A tent sleeps 4 and costs $70. How many do I need?", ["3", "210"], ""),
    ("There will be 40 guests. Each cheese board feeds 12 and costs $35. Budget of $150, can I afford it?", ["4", "140"], "enough"),
    ("My club has 14 kids, and one van serves 6 at a cost of 50 dollars. How much will it cost?", ["3", "150"], ""),
    ("For 13 people, one bucket of chicken feeds 5 people and costs $24. I've got $70. Enough?", ["3", "72", "2"], "short"),
]
NOT_THE_SHAPE = [
    "Job A pays 70000 but commuting costs 5000 a year. Job B pays 62000 and is remote. Which leaves me more money?",
    "I earn 3200 a month. Rent is 1400, my car is 350 and food is 500. Can I save 1000 a month?",
    "If a gym costs 45 a month, how long until I've spent 500?",
    "A gym costs 45 a month. Is that a lot?",
    "Plan A is 30 a month, Plan B is 20 a month and Plan C is 10 a month with a 500 fee. Over a year, which is cheapest?",
    "Plan A is 30 a month for the first 6 months, then 50. Plan B is 40 a month. Over a year, which is cheaper?",
    "Plan A is 30 a month with a 10 percent discount. Plan B is 28 a month. Over a year, which is cheaper?",
    "My floor is 8 meters by 5 meters. Tiles come in boxes that cover 6 square meters each and a box costs 25 dollars. How many boxes do I need?",
    "I'm hosting 18 people, and half of them are vegetarian. Each cake serves 8 and costs 22 dollars. Is 50 dollars enough?",
    "Each cake serves 8 and costs 22 dollars. Is that a good price?",
    "I'm hosting 18 people but each person eats 2 slices. Each cake serves 8 and costs 22 dollars. How many cakes?",
    "What's cheaper, a cat or a dog?",
]

results = []


def check(name, passed, detail=""):
    results.append(passed)
    print(f"{'ok  ' if passed else 'FAIL'} {name}" + (f"\n     {detail}" if not passed else ""))


for question, numbers, verdict in COSTS + PACKS:
    answer = sums.direct(question)
    said = (answer or "").partition("CONCLUSION:")[2].lower()
    passed = bool(answer) and all(sums.re.search(rf"(?<![\d.]){number}(?![\d])", said) for number in numbers) and verdict in said
    check(question[:70], passed, answer)
right = wrong = declined = 0
for question, numbers, verdict in BLIND:
    answer = sums.direct(question)
    said = (answer or "").partition("CONCLUSION:")[2].lower()
    if answer is None:
        declined += 1
        print(f"     declined: {question[:70]}")
    elif all(sums.re.search(rf"(?<![\d.]){number}(?![\d])", said) for number in numbers) and verdict in said:
        right += 1
    else:
        wrong += 1
        print(f"WRONG {question}\n     {answer}")
print(f"blind set: {right} right, {declined} left to the model, {wrong} wrong")
check("nothing in the blind set answered wrongly", wrong == 0)
for question in NOT_THE_SHAPE:
    answer = sums.direct(question)
    check(f"leaves alone: {question[:60]}", answer is None, answer)

# Nothing else already in the planning tests or real messages should be read as these shapes.
already = {question for question, _, _ in COSTS + PACKS}
for name in ("plan_cases.jsonl", "plan_cases2.jsonl", "plan_cases3.jsonl"):
    for line in (ROOT / "personas" / "one_ring" / name).read_text(encoding="utf-8").splitlines():
        case = json.loads(line)
        answer = sums.compare_costs(case["q"]) or sums.packs(case["q"])
        if case["q"] not in already:
            check(f"{name} {case['id']} left to the model", answer is None, answer)

# The voice step must never read its instructions aloud.
WORK = "2 + 2 = 4\n\nCONCLUSION: The answer is 4."
ECHO = "I've already worked this out, and the working below is correct. Give the user the answer and the numbers behind it. Keep every number exactly as it is."
check("an echo of the instructions is replaced", planner.final_reply(ECHO, WORK, [])[0] == "The answer is 4.")
check("an echo with no conclusion gets a fixed line", planner.final_reply(ECHO, "2 + 2 = 4", [])[0] == planner.LOST_THREAD)
check("a normal reply is kept", planner.final_reply("It's 4, my dear, as sure as gold.", WORK, []) == ("It's 4, my dear, as sure as gold.", ""))
check("ordinary phrases aren't taken for an echo", not planner.leaked_note("I'd say that in your own words, my dear, and keep your numbers close."))

FORM = "SIDES: They outnumber us 5 to 1.\nPLAN: 1. All 20 men wait.\nCONCLUSION: At 5 to 1, don't fight directly. Send all 20 men by night to scatter the horses."
FIGHT = [{"role": "user", "content": "100 soldiers are camped outside. We have 20 men. How do we stop them?"}]
PLAN_SAID = "Send all 20 men by night to scatter the horses, my dear."
check("a voiced plan is kept without the ratio", planner.final_reply(PLAN_SAID, FORM, FIGHT)[0] == PLAN_SAID)
check("a force changed in words is replaced", planner.final_reply("Send two riders to the horses.", FORM, FIGHT)[1].startswith("new numbers"))
check("a list read aloud is replaced", planner.final_reply("1. All 20 men wait. 2. They strike.", FORM, FIGHT)[1] == "read out a list")
check("a reply that wanders off the plan is replaced", planner.final_reply("Ask for a truce, and offer them gold or a prisoner in return.", FORM, FIGHT)[1] == "changed the plan")
check("mentioning having worked it out is replaced", planner.final_reply("I've worked this out for you.", FORM, FIGHT)[1] == "mentioned the working")
check("a conclusion cut off mid-sentence loses the unfinished part", planner.conclusion("CONCLUSION: At 5 to 1, don't fight. Use the") == "At 5 to 1, don't fight.")
check("a conclusion with no finished sentence counts as none", planner.conclusion("CONCLUSION: At 5 to 1, don't") == "")
later = [{"role": "user", "content": "My 80 riders face 40 archers. What do I do?"}, {"role": "assistant", "content": "Ride round."}, {"role": "user", "content": "What if I only had 10 riders?"}]
check("a follow-up puts the new number on the sheet", "Us: 10 riders." in planner.work_messages(later)[0]["content"])
unrelated = [{"role": "user", "content": "What would Gandalf say?"}, {"role": "assistant", "content": "Plenty."}, *FIGHT]
check("earlier chat stays out of a new fight", "Gandalf" not in planner.work_messages(unrelated)[0]["content"])

for case_id, question, wanted in [
    ("battle", "About 200 men and 80 horses are camped outside my city walls. I only have 10 men. How do I capture their camp?", True),
    ("bridge", "In my story, 100 raiders must cross a narrow one-man bridge, and I've got 5 archers. What's the best plan?", True),
    ("followup", "What if I only had 10 knights?", True),
    ("orcs", "In my game I have 3 wizards, and each can cast fire twice. Each fire spell kills 5 orcs. There are 30 orcs in the canyon. Can we kill them all?", False),
    ("garrison", "In my game I have 40 soldiers guarding 3 gates. Each gate needs at least 15. Can I cover them all?", False),
    ("budget", "I earn 3200 a month. Rent is 1400. How do I save 1000 a month?", False),
]:
    check(f"tactics route for {case_id}: {wanted}", planner.is_tactics(question) == wanted)

print(f"{sum(results)} of {len(results)} passed")
sys.exit(0 if all(results) else 1)
