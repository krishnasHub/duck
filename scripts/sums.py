"""Check the sums in the planner's working with real arithmetic, because the model is unreliable at it.

Only arithmetic and clock times. Whether the sums are the right ones to do is still up to the model.
"""
import ast
import math
import operator
import re

UNIT = r"(?:am|pm|a\.m\.|p\.m\.|minutes?|mins?|hours?|hrs?)"
NUMBER = r"\d[\d,]*(?:[.:]\d+)?"
TERM = rf"\$?\(*\s*\$?{NUMBER}\s*{UNIT}?\s*\)*"
OPERATOR = r"(?:[-+*/×x÷–−]|\\times|\\div|\btimes\b|\bminus\b|\bplus\b|\bdivided by\b)"
# Two or more terms, an equals sign, then the claimed answer. If an operator follows, as in "(45 + 100) * 12 = 145 * 12 = 1740",
# the "answer" is only a middle step, so it's skipped and the later part gets checked instead.
SUM = re.compile(
    rf"(?<![\w:.,])(?P<left>{TERM}(?:\s*{OPERATOR}\s*{TERM})+)\s*=\s*\$?(?P<right>{NUMBER}(?:\s*{UNIT})?)(?![\d:])(?!\s*{OPERATOR}\s*\$?\(*\d)",
    re.I,
)
TERM_PARTS = re.compile(rf"([-+–−]?)\s*\$?(\d+(?::\d+)?(?:\.\d+)?)\s*({UNIT})?", re.I)
WORDS = (("\\times", "*"), ("\\div", "/"), ("divided by", "/"), ("times", "*"), ("minus", "-"), ("plus", "+"))


def symbols(text):
    """Turn spoken operators into symbols."""
    for word, symbol in WORDS:
        text = re.sub(re.escape(word), symbol, text, flags=re.I)
    return text
BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
MINUTES_PER = {"m": 1, "h": 60}
TWELVE_HOURS = 12 * 60
DAY = 24 * 60


def _evaluate(node):
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in BINARY:
        return BINARY[type(node.op)](_evaluate(node.left), _evaluate(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_evaluate(node.operand)
    raise ValueError("not arithmetic")


def arithmetic(expression):
    """Work out plain arithmetic safely, without eval. Returns None if it isn't arithmetic."""
    text = expression.replace(",", "").replace("$", "")
    for symbol, python in (("×", "*"), ("x", "*"), ("X", "*"), ("÷", "/"), ("–", "-"), ("−", "-")):
        text = text.replace(symbol, python)
    try:
        return float(_evaluate(ast.parse(text.strip(), mode="eval")))
    except (ValueError, SyntaxError, ZeroDivisionError):
        return None


def _clock_minutes(value, meridian):
    hours, _, minutes = value.partition(":")
    total = int(hours) * 60 + int(minutes or 0)
    if meridian:
        total = total % TWELVE_HOURS + (TWELVE_HOURS if meridian.startswith("p") else 0)
    return total


def _meridian(unit):
    unit = (unit or "").lower().replace(".", "")
    return unit if unit in ("am", "pm") else ""


def format_clock(total, meridian, twenty_four):
    if twenty_four:
        total %= DAY
        return f"{total // 60}:{total % 60:02d}"
    total %= DAY
    hour = total // 60 % 12 or 12
    text = f"{hour}:{total % 60:02d}"
    if meridian:
        text += " pm" if total >= TWELVE_HOURS else " am"
    return text


def clock(left, right_is_clock=False):
    """Work out "8:40 - 25 min - 15 min". Returns (minutes, has am/pm, 24-hour), or None if this isn't a clock sum.

    "7 - 90 minutes = 5:30" starts from a bare hour, which only counts because the answer is a clock time.
    """
    terms = TERM_PARTS.findall(left)
    if len(terms) < 2 or "(" in left or re.search(r"[*/×x÷]", re.sub(UNIT, "", left, flags=re.I)):
        return None
    _, first, first_unit = terms[0]
    meridian = _meridian(first_unit)
    if ":" not in first and not meridian and not (right_is_clock and not first_unit and "." not in first and int(first) <= 24):
        return None
    if "." in first or (first_unit and not meridian):
        return None
    total = _clock_minutes(first, meridian)
    hours = int(first.partition(":")[0])
    twenty_four = not meridian and (hours > 12 or hours == 0)
    for sign, value, unit in terms[1:]:
        unit = unit.lower()
        if unit.startswith("h"):
            minutes = float(value) * 60
        elif unit.startswith("m") or not unit:
            minutes = float(value)
        else:
            return None
        total += -minutes if sign in ("-", "–", "−") else minutes
    return int(round(total)), bool(meridian), twenty_four


def _same_units(left):
    """"40 min * 3" is fine as plain numbers. "2 hours + 30 min" isn't, so it's left alone."""
    kinds = {unit[0].lower() for unit in re.findall(UNIT, left, re.I) if not _meridian(unit)}
    return len(kinds) <= 1


def check(left, right):
    """Returns the right answer as text if the claimed one is wrong, or None if it's right or can't be checked."""
    left = symbols(left)
    right_match = re.match(rf"({NUMBER})\s*({UNIT})?", right, re.I)
    claimed, right_unit = right_match.group(1), right_match.group(2)
    timed = clock(left, ":" in claimed or bool(_meridian(right_unit)))
    if timed:
        total, has_meridian, twenty_four = timed
        claimed_clock = re.fullmatch(r"\d+(?::\d+)?", claimed)
        if not claimed_clock:
            return format_clock(total, has_meridian, twenty_four)
        right_meridian = _meridian(right_unit)
        said = _clock_minutes(claimed, right_meridian)
        # Compare on a 12-hour face unless both sides say which half of the day they mean.
        span = DAY if (has_meridian and right_meridian) or twenty_four else TWELVE_HOURS
        if (said - total) % span == 0:
            return None
        return format_clock(total, has_meridian, twenty_four)
    if ":" in left or ":" in claimed or not _same_units(left):
        return None
    plain = re.sub(UNIT, "", left, flags=re.I)
    value = arithmetic(plain)
    if value is None:
        return None
    said = float(claimed.replace(",", ""))
    decimals = len(claimed.partition(".")[2])
    if abs(said - value) <= 0.5 * 10 ** -decimals + 1e-9:
        return None
    # "40 / 6 = 7" rounds up to a whole trip, which is often what the model means.
    if not decimals and not value.is_integer() and said in (math.floor(value), math.ceil(value)):
        return None
    return f"{int(value)}" if value.is_integer() else f"{value:.2f}".rstrip("0")


COUNT_BACK_ASKS = re.compile(r"\b(?:when|what time)\b[^?]*\b(get up|wake|leave|set off|head out|start|begin)\b[^?]*\?", re.I)
COUNT_FORWARD = re.compile(r"\b(?:when|what time)\b[^?]*\b(finish|done|end|arrive|get there|get back|be back|be home)\b", re.I)
# "Each" or "per" means the steps don't simply follow one another: both dishes finish together, or a step repeats.
NOT_IN_A_ROW = re.compile(r"\b(each|every|per|both|at the same time|while|meanwhile|if)\b", re.I)
CLOCK_TIME = re.compile(r"\b(\d{1,2}:\d{2}\s*(?:am|pm|a\.m\.|p\.m\.)?|\d{1,2}\s*(?:am|pm|a\.m\.|p\.m\.)|noon|midnight)(?![\w-])|\bat (\d{1,2})\b(?![:\d]|\s*(?:minutes?|mins?|hours?|hrs?))", re.I)
DURATION = re.compile(
    r"\b(an hour and a half|half an hour|half hour|a quarter of an hour|an? hour|\d+(?:\.\d+)?\s*(?:-\s*)?(?:hours?|hrs?|minutes?|mins?))\b", re.I
)
PHRASES = {"an hour and a half": 90, "half an hour": 30, "half hour": 30, "a quarter of an hour": 15, "an hour": 60, "a hour": 60}
VERBS = {"get up": "get up", "wake": "get up", "leave": "leave", "set off": "leave", "head out": "leave", "start": "start", "begin": "start"}


def _duration_minutes(text):
    text = text.lower()
    if text in PHRASES:
        return PHRASES[text]
    amount = float(re.match(r"[\d.]+", text).group())
    return int(amount * 60) if "h" in text else int(amount)


def count_back(question):
    """Answer "my bus is at 7:15, the walk is 20 minutes and breakfast takes 35, when do I get up?" with no model at all.

    The model's mistakes here are in the setup: it adds instead of subtracting, or misreads a duration. Code can read this
    kind of question directly. Returns the working as text, or None if the question isn't plainly this shape.
    """
    asked = COUNT_BACK_ASKS.search(question)
    if not asked or COUNT_FORWARD.search(question) or NOT_IN_A_ROW.search(question):
        return None
    times = CLOCK_TIME.findall(DURATION.sub(" ", question))
    durations = [_duration_minutes(found) for found in DURATION.findall(question)]
    if len(times) != 1 or not durations:
        return None
    deadline = (times[0][0] or times[0][1]).lower().replace(".", "").replace(" ", "")
    deadline = {"noon": "12pm", "midnight": "12am"}.get(deadline, deadline)
    left = re.sub(r"(am|pm)$", r" \1", deadline) + "".join(f" - {minutes} min" for minutes in durations)
    timed = clock(left, True)
    if not timed:
        return None
    answer = format_clock(*timed)
    verb = VERBS[asked.group(1).lower()]
    return f"{left} = {answer}\n\nCONCLUSION: You need to {verb} by {answer}."


MONEY = r"(\$\s*)?(\d[\d,]*(?:\.\d+)?)(\s*(?:dollars?|bucks?))?"
COST_ASKS = re.compile(r"\b(cheaper|costs? less|less expensive|better deal)\b", re.I)
# Prices that change, percentages and a third option all need real thought, so they're left to the model.
COST_TRICKY = re.compile(r"%|\b(percent|discount|first \d+|then|after \d+|until|how long|if|cheapest|free)\b", re.I)
WORD_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12}
PERIOD = re.compile(r"\b(?:over|for|across|in)\s+(?:the next\s+)?(\d+|an?|one|two|three|four|five|six|seven|eight|nine|ten|twelve)\s+(year|month)s?\b", re.I)
CLAUSES = re.compile(r"(?<=[.?!])\s+|,?\s+(?:and|while|whereas|but)\s+(?=(?:[Pp]lan|[Oo]ption|[Tt]he|[Aa]n?|[Mm]y|[A-Z][a-z]+)\s)")
OPTION_NAME = re.compile(r"^\W*(?:the\s+|an?\s+|my\s+)?(.+?)\s+(?:is|are|costs?|charges?|runs?|would be)\b", re.I)
PER_MONTH = re.compile(rf"{MONEY}\s*(?:a|per|every|each)?\s*/?\s*month(?:ly)?\b|{MONEY}\s+monthly\b", re.I)
PER_ITEM = re.compile(rf"{MONEY}\s+(?:each|per\s+(?!month)\w+|a\s+(?:class|visit|ride|trip|session))\b", re.I)
TIMES_A_MONTH = re.compile(r"\b(\d+)(?:\s+times)?\s+(?:a|per|every|each)\s+month\b", re.I)
ONE_OFF = re.compile(rf"{MONEY}\s+(?:[\w-]+\s+){{0,2}}?(?:fee|deposit|up\s?front|one-?time)\b|\b(?:fee|charge|deposit)\s+of\s+{MONEY}", re.I)
PACK = re.compile(r"\b(?:each|a|an|one|every)\s+((?:[a-z]+\s+of\s+)?[a-z]+)\s+(?:serves|feeds)\s+(\d+)(?:\s+(?:people|guests|kids|friends))?", re.I)
PACK_COST = re.compile(rf"\bcosts?\s+{MONEY}", re.I)
HEADCOUNT = re.compile(r"\b(\d+)\s+(people|guests|friends|kids|children|adults)\b", re.I)
SO_MANY_OF_US = re.compile(r"\bwe(?:'re| are)\s+(\d+)\b", re.I)
BUDGET = re.compile(rf"\b(?:budget\s+(?:is|of)|i(?:'ve|\s+have)?\s+got|i\s+have|only\s+have)\s+{MONEY}(?![\d,.]*\d)(?!\s+(?:people|guests|friends|kids|children|adults)\b)", re.I)
PACK_ASKS = re.compile(r"\b(enough|afford|cover|how many|what will it cost|how much)\b", re.I)
PACK_TRICKY = re.compile(r"%|\b(half|twice|slices?|per person|each person|vegetarians?|plus|including|if|meters?|percent)\b", re.I)


def _amount(match):
    """A pattern with MONEY in it may use either copy. Returns the first number found."""
    for group in match.groups():
        if group and group[0].isdigit():
            return float(group.replace(",", ""))
    return None


def _all_used(question, used):
    """Every number in the question must have a place in the sum. One left over means it was misread, so code should stay out of it."""
    found = {float(value.replace(",", "")) for value in re.findall(r"\d[\d,]*(?:\.\d+)?", question)}
    return found <= {float(value) for value in used}


def _plain(value):
    return f"{value:,.2f}".rstrip("0").rstrip(".").replace(",", "")


def _money_style(question):
    if "$" in question:
        return lambda value: f"${_plain(value)}"
    if re.search(r"\b(dollars?|bucks?)\b", question, re.I):
        return lambda value: f"{_plain(value)} dollars"
    return _plain


def _cost_option(clause):
    """Read "A gym costs 45 a month with a 100 fee" as name, monthly cost and one-off cost, leaving None for what isn't there."""
    named = OPTION_NAME.match(clause)
    monthly_text = None
    each = PER_ITEM.search(clause)
    times = TIMES_A_MONTH.search(clause)
    monthly = PER_MONTH.search(clause)
    used = []
    if each and times:
        monthly_cost = _amount(each) * int(times.group(1))
        monthly_text = f"{_plain(_amount(each))} x {times.group(1)}"
        used += [_amount(each), int(times.group(1))]
    elif monthly and not re.search(r"\btimes\b", monthly.group(0), re.I):
        monthly_cost = _amount(monthly)
        used.append(monthly_cost)
    else:
        monthly_cost = None
    fee = ONE_OFF.search(clause)
    if fee:
        used.append(_amount(fee))
    return {
        "name": named.group(1) if named else None,
        "monthly": monthly_cost,
        "monthly_text": monthly_text,
        "fee": _amount(fee) if fee else None,
        "used": used,
    }


def compare_costs(question):
    """Answer "45 a month with a 100 fee, or 12 each six times a month: which is cheaper over a year?" with no model.

    The model's mistakes here are in the setup, such as leaving out the fee. Returns the working, or None if this isn't plainly two options.
    """
    if not COST_ASKS.search(question) or COST_TRICKY.search(question):
        return None
    period = PERIOD.search(question)
    if not period:
        return None
    amount = period.group(1).lower()
    months = (int(amount) if amount.isdigit() else WORD_NUMBERS[amount]) * (12 if period.group(2).lower() == "year" else 1)
    options = []
    for clause in CLAUSES.split(question):
        if COST_ASKS.search(clause):
            continue
        found = _cost_option(clause)
        if found["monthly"] is not None and found["name"]:
            options.append(found)
        elif options and (found["monthly"] is not None or found["fee"] is not None):
            # "and I go 6 times a month" or "and a 100 dollar fee" belongs to the option before it.
            if found["monthly"] is not None or options[-1]["fee"] is not None:
                return None
            options[-1]["fee"] = found["fee"]
            options[-1]["used"] += found["used"]
    if len(options) != 2:
        return None
    if not _all_used(question, [int(amount) if amount.isdigit() else 0, *options[0]["used"], *options[1]["used"]]):
        return None
    money = _money_style(question)
    lines, totals = [], []
    for option in options:
        fee = option["fee"] or 0
        total = fee + option["monthly"] * months
        totals.append(total)
        recurring = option["monthly_text"] or _plain(option["monthly"])
        lines.append(f"{option['name']}: {_plain(fee)} + {recurring} x {months} = {_plain(total)}")
    names = [option["name"][0].lower() + option["name"][1:] for option in options]
    spans = f"over {months} months"
    if totals[0] == totals[1]:
        ending = f"They both come to the same, {money(totals[0])} {spans}."
    else:
        winner = 0 if totals[0] < totals[1] else 1
        ending = (f"{names[winner]} is cheaper {spans}: {money(totals[winner])} against {money(totals[1 - winner])} for {names[1 - winner]}, "
                  f"a saving of {money(abs(totals[0] - totals[1]))}.")
        ending = ending[0].upper() + ending[1:]
    return "\n".join(lines) + f"\n\nCONCLUSION: {ending}"


def packs(question):
    """Answer "18 people, each cake serves 8 and costs 22, I've got 50: is that enough?" with no model. Otherwise None."""
    if not PACK_ASKS.search(question) or PACK_TRICKY.search(question):
        return None
    pack = PACK.search(question)
    if not pack or len(PACK.findall(question)) != 1:
        return None
    rest = question[: pack.start()] + " " + question[pack.end():]
    cost = PACK_COST.search(rest)
    heads = HEADCOUNT.findall(rest)
    counts = [int(found[0]) for found in heads] or [int(found) for found in SO_MANY_OF_US.findall(rest)]
    if not cost or len(counts) != 1:
        return None
    people = counts[0]
    serves = int(pack.group(2))
    price = _amount(cost)
    needed = -(-people // serves)
    total = needed * price
    name = pack.group(1).lower()
    plural = re.sub(r"^(\w+)", r"\1s", name) if " of " in name else f"{name}s"
    money = _money_style(question)
    count = f"{needed} {name if needed == 1 else plural}"
    working = f"{people} / {serves} = {needed} when rounded up\n{needed} x {_plain(price)} = {_plain(total)}"
    budgets = BUDGET.findall(rest)
    if len(budgets) > 1:
        return None
    if not _all_used(question, [people, serves, price, *(budget[1].replace(",", "") for budget in budgets)]):
        return None
    if not budgets:
        return f"{working}\n\nCONCLUSION: You need {count}, which costs {money(total)}."
    budget = float(budgets[0][1].replace(",", ""))
    if total <= budget:
        ending = f"Yes, {money(budget)} is enough: {count} costs {money(total)}."
    else:
        ending = f"No, {money(budget)} is short by {money(total - budget)}: you need {count}, which costs {money(total)}."
    return f"{working}\n\nCONCLUSION: {ending}"


def direct(question):
    """Any planning question plain enough for code to answer by itself, or None."""
    return count_back(question) or compare_costs(question) or packs(question)


def first_error(work):
    """Find the first wrong sum. Returns (working up to and including the corrected answer, a note), or None."""
    for match in SUM.finditer(work):
        answer = check(match.group("left"), match.group("right"))
        if answer is not None:
            note = f"{' '.join(match.group('left').split())} = {match.group('right')} corrected to {answer}"
            start = match.start("right")
            return f"{work[:start]}{answer}", note
    return None
