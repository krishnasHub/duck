"""Download a base model into models/ so later runs work with no internet."""
import argparse
import time
from pathlib import Path

from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parent.parent

parser = argparse.ArgumentParser()
parser.add_argument("--repo", default="Qwen/Qwen3-4B")
parser.add_argument("--attempts", type=int, default=8)
args = parser.parse_args()

target = ROOT / "models" / args.repo.split("/")[-1]

for attempt in range(1, args.attempts + 1):
    try:
        snapshot_download(args.repo, local_dir=target)
        print(f"OK: {target}")
        break
    except Exception as error:
        print(f"attempt {attempt} failed: {type(error).__name__}: {error}", flush=True)
        if attempt == args.attempts:
            raise
        time.sleep(10 * attempt)
