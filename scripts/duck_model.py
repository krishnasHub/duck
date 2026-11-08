"""Load the base model with an everyday adapter and a lore adapter, chosen for each reply."""
import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

from common import ROOT, base_path


def load(persona, base, everyday=None, lore=None):
    """Returns tokenizer and model. Pass "none" to disable_adapter-style use via set_mode."""
    tokenizer = AutoTokenizer.from_pretrained(base_path(base))
    model = AutoModelForCausalLM.from_pretrained(base_path(base), dtype=torch.bfloat16, device_map={"": 0})
    paths = {}
    for name, folder in (("everyday", everyday), ("lore", lore)):
        if folder and (ROOT / "runs" / persona / folder).exists():
            paths[name] = ROOT / "runs" / persona / folder
    for index, (name, path) in enumerate(paths.items()):
        if index == 0:
            model = PeftModel.from_pretrained(model, path, adapter_name=name)
        else:
            model.load_adapter(path, adapter_name=name)
    model.eval()
    return tokenizer, model, set(paths)


def generate(model, adapters, mode, **settings):
    """mode is everyday, lore or none. It falls back to the plain model if that adapter isn't loaded."""
    if mode in adapters:
        model.set_adapter(mode)
        return model.generate(**settings)
    if adapters:
        with model.disable_adapter():
            return model.generate(**settings)
    return model.generate(**settings)
