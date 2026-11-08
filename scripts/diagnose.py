"""Check the prompt, weight types, token alignment and raw model loss."""
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from common import END_OF_TURN, base_path, load_conversations, load_system, persona_dir, render_prompt

BASE = "Qwen/Qwen3-4B"
tokenizer = AutoTokenizer.from_pretrained(base_path(BASE))
system = load_system("gandalf")
messages = load_conversations(persona_dir("gandalf") / "val.jsonl")[0]

prompt = render_prompt(tokenizer, system, messages[:1])
print("PROMPT TAIL:", repr(prompt[-90:]))
print("pad:", repr(tokenizer.pad_token), tokenizer.pad_token_id, "eos:", repr(tokenizer.eos_token), tokenizer.eos_token_id)
print("end of turn id:", tokenizer.convert_tokens_to_ids(END_OF_TURN))

model = AutoModelForCausalLM.from_pretrained(base_path(BASE), dtype=torch.bfloat16, device_map={"": 0})
model.eval()
print("dtypes:", {str(p.dtype) for p in model.parameters()})
print("allocated after load GB:", round(torch.cuda.memory_allocated() / 1e9, 2))
print("tied embeddings:", model.get_output_embeddings().weight is model.get_input_embeddings().weight)
print("lm_head abs mean:", model.get_output_embeddings().weight.float().abs().mean().item())

prompt_ids = tokenizer(prompt, add_special_tokens=False).input_ids
target_ids = tokenizer(messages[1]["content"] + END_OF_TURN, add_special_tokens=False).input_ids
ids = torch.tensor([prompt_ids + target_ids]).cuda()
labels = torch.tensor([[-100] * len(prompt_ids) + target_ids]).cuda()

with torch.no_grad():
    out = model(input_ids=ids, labels=labels)
    log_probs = torch.log_softmax(out.logits.float(), dim=-1)
print("reported loss:", round(out.loss.item(), 4))
print("logits has nan:", bool(torch.isnan(out.logits.float()).any()))

start = len(prompt_ids)
per_token = [-log_probs[0, i - 1, ids[0, i]].item() for i in range(start, ids.shape[1])]
print("manual shifted loss:", round(sum(per_token) / len(per_token), 4))
for i, value in zip(range(start, start + 8), per_token):
    top = log_probs[0, i - 1].argmax().item()
    print(f"  target {tokenizer.decode(ids[0, i])!r:14} nll={value:6.2f}  top prediction {tokenizer.decode(top)!r}")

general = "The capital of France is Paris, and it is known for the Eiffel Tower."
ids2 = tokenizer(general, return_tensors="pt").input_ids.cuda()
with torch.no_grad():
    print("plain English sentence loss:", round(model(input_ids=ids2, labels=ids2).loss.item(), 4))

inputs = tokenizer(prompt, return_tensors="pt", add_special_tokens=False).to("cuda")
with torch.no_grad():
    generated = model.generate(**inputs, max_new_tokens=50, do_sample=False)
print("GENERATED:", repr(tokenizer.decode(generated[0][inputs.input_ids.shape[1] :], skip_special_tokens=False)))
