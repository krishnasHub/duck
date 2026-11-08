"""Split downloaded articles into short passages for the lore library, dropping adaptation sections."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "lore" / "wikipedia" / "pages.jsonl"
OUT = ROOT / "lore" / "library.jsonl"
MAX_WORDS = 150

SKIP = re.compile(
    r"see also|references|notes|citations|external links|bibliography|sources|further reading|"
    r"adaptation|film|television|radio|video game|games|portray|popular culture|in other media|reception|legacy",
    re.I,
)
# Wikipedia titles "The Lord of the Rings: ..." and "The Hobbit: ..." are the films and games, not the books.
SKIP_TITLE = re.compile(
    r"film|video game|\(band\)|\(album\)|rings of power|\(musical\)|accolades|pinball|strategy battle|"
    r"battle for middle-earth|^lego |^the lord of the rings:|^the hobbit:|shadow of (mordor|war)|war in the north|"
    r"role-playing game|board game|card game|parod",
    re.I,
)
pages = []
with open(SOURCE, encoding="utf-8") as handle:
    for line in handle:
        try:
            pages.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # The download may still be writing its last line.

count = 0
with open(OUT, "w", encoding="utf-8") as out:
    # Hand-written key facts come first. They get a guaranteed chance in search.
    facts = ROOT / "lore" / "key_facts.jsonl"
    if facts.exists():
        for line in open(facts, encoding="utf-8"):
            if line.strip():
                fact = json.loads(line)
                out.write(
                    json.dumps(
                        {"title": "Key fact: " + fact["topic"], "section": "", "url": "", "text": fact["text"], "fact": True},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                count += 1
    for page in pages:
        # Redirects can lead to adaptation articles that the title filter couldn't see.
        if SKIP_TITLE.search(page["title"]):
            continue
        section, skipping, level = "", False, 0
        buffer = []

        def flush():
            global count
            text = " ".join(buffer).strip()
            buffer.clear()
            if len(text.split()) >= 15:
                out.write(
                    json.dumps(
                        {"title": page["title"], "section": section, "url": page["url"], "text": text},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                count += 1

        for raw in page["text"].splitlines():
            line = raw.strip()
            heading = re.fullmatch(r"(={2,})\s*(.*?)\s*\1", line)
            if heading:
                flush()
                depth = len(heading.group(1))
                # Subsections of a skipped section stay skipped.
                if skipping and depth > level:
                    continue
                section = heading.group(2)
                skipping = bool(SKIP.search(section))
                level = depth
                continue
            if skipping or not line:
                continue
            if len(" ".join(buffer).split()) + len(line.split()) > MAX_WORDS:
                flush()
            buffer.append(line)
        flush()

print(f"{len(pages)} articles, {count} passages -> {OUT}")
