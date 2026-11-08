"""List or download Wikipedia articles from the Middle-earth categories through the official API.

Requests run one at a time with a pause, and each saved page keeps its source URL for attribution.
"""
import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "lore" / "wikipedia"
API = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "duck-private-prototype/0.1 (personal offline research project)"}

parser = argparse.ArgumentParser()
parser.add_argument("--root", default="Category:Middle-earth")
parser.add_argument("--depth", type=int, default=3)
parser.add_argument("--pause", type=float, default=3.0)
parser.add_argument("--download", action="store_true", help="download the reviewed titles.txt")
args = parser.parse_args()


def call(**params):
    params.update(format="json", formatversion="2", maxlag="5")
    url = f"{API}?{urllib.parse.urlencode(params)}"
    for attempt in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60) as response:
                data = json.load(response)
            if data.get("error", {}).get("code") == "maxlag":
                time.sleep(10)
                continue
            if "error" in data:
                raise RuntimeError(data["error"])
            time.sleep(args.pause)
            return data
        except urllib.error.HTTPError as error:
            # Respect the server's requested wait, and back off hard when rate limited.
            wait = int(error.headers.get("Retry-After") or 0) or 60 * (attempt + 1)
            print(f"HTTP {error.code}: waiting {wait}s", flush=True)
            time.sleep(wait)
        except OSError as error:
            print(f"retry {attempt + 1}: {error}", flush=True)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"gave up on {url}")


def members(category):
    params = dict(action="query", list="categorymembers", cmtitle=category, cmtype="page|subcat", cmlimit="500")
    while True:
        data = call(**params)
        yield from data["query"]["categorymembers"]
        if "continue" not in data:
            return
        params.update(data["continue"])


OUT.mkdir(parents=True, exist_ok=True)

if not args.download:
    seen, titles, found_in = set(), set(), {}
    frontier = [args.root]
    for level in range(args.depth + 1):
        next_frontier = []
        for category in frontier:
            if category in seen:
                continue
            seen.add(category)
            for item in members(category):
                if item["ns"] == 14:
                    next_frontier.append(item["title"])
                elif item["ns"] == 0:
                    titles.add(item["title"])
                    found_in.setdefault(item["title"], category)
        print(f"depth {level}: {len(frontier)} categories, {len(titles)} articles so far", flush=True)
        frontier = next_frontier
    (OUT / "categories.txt").write_text("\n".join(sorted(seen)) + "\n", encoding="utf-8")
    (OUT / "titles_with_category.tsv").write_text(
        "".join(f"{title}\t{found_in[title]}\n" for title in sorted(titles)), encoding="utf-8"
    )
    print(f"{len(seen)} categories, {len(titles)} articles. Listed in {OUT}")
else:
    titles = (OUT / "titles.txt").read_text(encoding="utf-8").splitlines()
    saved = 0
    seen_pages = set()
    with open(OUT / "pages.jsonl", "w", encoding="utf-8") as handle:
        for title in titles:
            data = call(
                action="query", prop="extracts|info", explaintext="1", inprop="url", redirects="1", titles=title
            )
            page = data["query"]["pages"][0]
            # Redirects resolve to the same article, so keep each article once.
            if page.get("title") in seen_pages:
                continue
            seen_pages.add(page.get("title"))
            text = page.get("extract", "").strip()
            if not text:
                print(f"empty: {title}", flush=True)
                continue
            handle.write(
                json.dumps(
                    {"title": page["title"], "url": page["fullurl"], "revision": page["lastrevid"], "text": text},
                    ensure_ascii=False,
                )
                + "\n"
            )
            saved += 1
            if saved % 100 == 0:
                print(f"{saved}/{len(titles)}", flush=True)
    print(f"saved {saved} pages to {OUT / 'pages.jsonl'}")
