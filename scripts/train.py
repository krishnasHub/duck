"""Fine-tune a persona with LoRA. Every assistant turn becomes one training example."""
import argparse
import json
import math
import random
import time

import torch
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer

from common import END_OF_TURN, ROOT, base_path, load_rows, load_system, persona_dir, render_prompt, with_lore, with_memory

parser = argparse.ArgumentParser()
parser.add_argument("--persona", default="gandalf")
parser.add_argument("--base", default="Qwen/Qwen3-4B")
parser.add_argument("--epochs", type=int, default=6)
parser.add_argument("--lr", type=float, default=2e-4)
parser.add_argument("--batch", type=int, default=4)
parser.add_argument("--rank", type=int, default=16)
parser.add_argument("--seed", type=int, default=7)
parser.add_argument("--data", choices=("all", "lore", "everyday"), default="all")
parser.add_argument("--name", default="adapter", help="folder name for this version in runs/<persona>")
parser.add_argument("--smoke", action="store_true", help="tiny run that only proves the pipeline works")
args = parser.parse_args()

random.seed(args.seed)
torch.manual_seed(args.seed)

tokenizer = AutoTokenizer.from_pretrained(base_path(args.base))
system = load_system(args.persona)


pool_file = persona_dir(args.persona) / "memory_pool.txt"
memory_pool = pool_file.read_text(encoding="utf-8").splitlines() if pool_file.exists() else []


def make_examples(*paths):
    examples = []
    rows = [row for path in paths for row in load_rows(path)]
    for row in rows:
        messages = row["messages"]
        row_system = with_lore(system, row.get("passages"))
        # Everyday replies see notes about the user, as on the page. Rows with no notes of their own
        # sometimes get unrelated ones, so the model learns to leave them out unless they matter.
        if not row.get("passages") and args.data != "lore":
            notes = row.get("memory")
            if notes is None:
                notes = random.sample(memory_pool, random.randint(1, 4)) if memory_pool and random.random() < 0.35 else []
            row_system = with_memory(row_system, notes)
        for index, message in enumerate(messages):
            if message["role"] != "assistant":
                continue
            prompt = render_prompt(tokenizer, row_system, messages[:index])
            prompt_ids = tokenizer(prompt, add_special_tokens=False).input_ids
            target_ids = tokenizer(message["content"] + END_OF_TURN, add_special_tokens=False).input_ids
            # Only the reply is learned; the prompt is context and is masked with -100.
            examples.append(
                {"input_ids": prompt_ids + target_ids, "labels": [-100] * len(prompt_ids) + target_ids}
            )
    return examples


folder = persona_dir(args.persona)
LORE_FILES = ("train_lore", "train_no_answer", "val_lore")


def data_files(prefix):
    files = sorted(folder.glob(f"{prefix}*.jsonl"))
    if args.data == "lore":
        return [path for path in files if path.stem in LORE_FILES]
    if args.data == "everyday":
        return [path for path in files if path.stem not in LORE_FILES]
    return files


train_examples = make_examples(*data_files("train"))
val_examples = make_examples(*data_files("val"))
if args.smoke:
    train_examples, val_examples = train_examples[:8], val_examples[:2]
    args.epochs = 1
print(f"train examples: {len(train_examples)}  val examples: {len(val_examples)}")


def batches(examples, shuffle):
    order = list(range(len(examples)))
    if shuffle:
        random.shuffle(order)
    for start in range(0, len(order), args.batch):
        chunk = [examples[i] for i in order[start : start + args.batch]]
        longest = max(len(e["input_ids"]) for e in chunk)
        pad = tokenizer.pad_token_id
        yield {
            "input_ids": torch.tensor([e["input_ids"] + [pad] * (longest - len(e["input_ids"])) for e in chunk]),
            "attention_mask": torch.tensor(
                [[1] * len(e["input_ids"]) + [0] * (longest - len(e["input_ids"])) for e in chunk]
            ),
            "labels": torch.tensor([e["labels"] + [-100] * (longest - len(e["labels"])) for e in chunk]),
        }


model = AutoModelForCausalLM.from_pretrained(base_path(args.base), dtype=torch.bfloat16, device_map={"": 0})
# Lore prompts are long, so trade some speed for memory. Spilling past 24 GB is far slower.
model.config.use_cache = False
model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
model.enable_input_require_grads()
model = get_peft_model(
    model,
    LoraConfig(
        r=args.rank,
        lora_alpha=args.rank * 2,
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        task_type="CAUSAL_LM",
    ),
)
model.print_trainable_parameters()

trainable = [p for p in model.parameters() if p.requires_grad]
optimizer = torch.optim.AdamW(trainable, lr=args.lr, weight_decay=0.01)
total_steps = args.epochs * math.ceil(len(train_examples) / args.batch)
scheduler = torch.optim.lr_scheduler.LambdaLR(
    optimizer, lambda step: min((step + 1) / 5, 0.5 * (1 + math.cos(math.pi * step / total_steps)))
)


def evaluate():
    model.eval()
    total, tokens = 0.0, 0
    with torch.no_grad():
        for batch in batches(val_examples, shuffle=False):
            batch = {key: value.cuda() for key, value in batch.items()}
            count = (batch["labels"][:, 1:] != -100).sum().item()
            total += model(**batch).loss.item() * count
            tokens += count
    model.train()
    return total / tokens


run_dir = ROOT / "runs" / args.persona
name = "smoke" if args.smoke else args.name
adapter_dir = run_dir / name
run_dir.mkdir(parents=True, exist_ok=True)
metrics = open(run_dir / f"metrics_{name}.jsonl", "w", encoding="utf-8")


def record(entry):
    print(json.dumps(entry), flush=True)
    metrics.write(json.dumps(entry) + "\n")
    metrics.flush()


best = evaluate()
record({"epoch": 0, "val_loss": round(best, 4), "note": "before training"})
model.save_pretrained(adapter_dir)
best_epoch = 0
started = time.time()

model.train()
for epoch in range(1, args.epochs + 1):
    running, seen = 0.0, 0
    for batch in batches(train_examples, shuffle=True):
        batch = {key: value.cuda() for key, value in batch.items()}
        loss = model(**batch).loss
        loss.backward()
        torch.nn.utils.clip_grad_norm_(trainable, 1.0)
        optimizer.step()
        scheduler.step()
        optimizer.zero_grad()
        running += loss.item()
        seen += 1
    val_loss = evaluate()
    record(
        {
            "epoch": epoch,
            "train_loss": round(running / seen, 4),
            "val_loss": round(val_loss, 4),
            "seconds": round(time.time() - started),
        }
    )
    if val_loss < best:
        best, best_epoch = val_loss, epoch
        model.save_pretrained(adapter_dir)

record(
    {
        "best_epoch": best_epoch,
        "best_val_loss": round(best, 4),
        "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2),
    }
)
print(f"saved best adapter to {adapter_dir}")
