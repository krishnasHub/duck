"""Filter the Wikipedia listing down to lore and scholarship, dropping adaptations and merchandise."""
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "lore" / "wikipedia"

EXCLUDE_CATEGORY = (
    "games", "game", "film", "music", "albums", "parodies", "works based", "translations",
    "rings of power", "television", "theatre", "visual art",
)
# Listed in lore categories, but about real-world people, places or adaptations.
EXCLUDE_TITLE = (
    "Ashley Judd", "Shire Country Park", "ElvenQuest", "Isengard (band)", "Tolkien on Film",
    "List of Middle-earth role-playing games", "List of Middle-earth video games",
    "List of accolades received by The Hobbit film series",
    "List of accolades received by The Lord of the Rings film series",
    "List of original characters in The Hobbit film series",
    "List of original characters in The Lord of the Rings film series",
)

kept, dropped = [], []
for line in (OUT / "titles_with_category.tsv").read_text(encoding="utf-8").splitlines():
    title, category = line.split("\t")
    lowered = category.lower()
    bad = any(word in lowered for word in EXCLUDE_CATEGORY) or title in EXCLUDE_TITLE
    (dropped if bad else kept).append((title, category))

(OUT / "titles.txt").write_text("\n".join(title for title, _ in kept) + "\n", encoding="utf-8")
print(f"kept {len(kept)}, dropped {len(dropped)}")
print("\nkept titles that look off-topic:")
suspects = ("film", "game", "album", "band", "musical", "actor", "(tv", "lego", "online", "park")
for title, category in kept:
    if any(word in title.lower() for word in suspects):
        print(f"  {title}  <- {category}")
print("\nfirst category for sample drops:")
for title, category in dropped[::40]:
    print(f"  {title}  <- {category}")
