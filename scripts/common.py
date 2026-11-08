"""Shared helpers for loading personas and building prompts."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
END_OF_TURN = "<|im_end|>"


def persona_dir(persona):
    return ROOT / "personas" / persona


def base_path(base):
    """Prefer the local copy in models/ so nothing needs the internet."""
    local = ROOT / "models" / base.split("/")[-1]
    return str(local) if local.exists() else base


def load_system(persona):
    return (persona_dir(persona) / "system.txt").read_text(encoding="utf-8").strip()


def load_conversations(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line)["messages"] for line in handle if line.strip()]


def load_rows(path):
    """Read training rows, each with messages and optional lore passages. Missing files are empty."""
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8-sig") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def search_query(persona, text):
    """When a question says "you", search for who the persona is. A persona can set this in search_hint.txt."""
    hint = persona_dir(persona) / "search_hint.txt"
    if hint.exists() and re.search(r"\byou(r|rs|rself)?\b", text, re.I):
        return f"{text} {hint.read_text(encoding='utf-8').strip()}"
    return text


def with_lore(system, passages):
    """Add retrieved passages to the persona prompt."""
    if not passages:
        return system
    block = "\n\n".join(f"[{p['title']}] {p['text']}" for p in passages)
    return (
        f"{system}\n\nLore passages from your memory are below. Use them for facts about Middle-earth. "
        "Never state a lore fact they don't support. If they don't contain the answer, say you can't recall it. "
        "If the question assumes something false, correct it.\n\n" + block
    )


def with_memory(system, notes):
    """Add what the duck remembers about the user. An empty list says so, so it doesn't invent any."""
    if notes is None:
        return system
    if not notes:
        return f"{system}\n\nYou have no notes about the user from earlier chats."
    block = "\n".join(f"- {note}" for note in notes)
    return (
        f"{system}\n\nNotes about the user from earlier chats are below. Bring one up only when it helps with what they "
        f"just said, and never claim to remember anything else about them.\n\n{block}"
    )


def render_prompt(tokenizer, system, messages):
    """Render the exact prompt used at inference, with thinking switched off."""
    return tokenizer.apply_chat_template(
        [{"role": "system", "content": system}, *messages],
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
