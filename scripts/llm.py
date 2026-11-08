"""Run the compressed model in llama-server, the same engine the Jetson will use.

Both adapters stay loaded, and each request says which one to apply, so swapping costs almost nothing.
"""
import atexit
import json
import os
import subprocess
import time
import urllib.request

from common import ROOT

SERVER = ROOT / "tools" / "llama.cpp" / "bin" / ("llama-server.exe" if os.name == "nt" else "llama-server")
GGUF = ROOT / "models" / "gguf"
ROUTES = ("everyday", "lore")


class Llama:
    def __init__(self, base, everyday, lore, port=8770, gpu_layers=99, repeat_penalty=1.1, presence_penalty=0.0, context=4096):
        self.url = f"http://127.0.0.1:{port}"
        self.repeat_penalty, self.presence_penalty = repeat_penalty, presence_penalty
        command = [str(SERVER), "-m", str(GGUF / f"{base}.gguf"), "--host", "127.0.0.1", "--port", str(port), "--no-webui",
                   "-ngl", str(gpu_layers), "-c", str(context), "-np", "1", "--lora-init-without-apply"]
        self.routes = {}
        for route, name in (("everyday", everyday), ("lore", lore)):
            path = GGUF / f"{name}.gguf"
            if name and path.exists():
                self.routes[route] = len(self.routes)
                command += ["--lora", str(path)]
            else:
                print(f"no adapter for {route}: {path} not found", flush=True)
        self.process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        atexit.register(self.process.terminate)
        for _ in range(240):
            try:
                with urllib.request.urlopen(f"{self.url}/health", timeout=2) as response:
                    if response.status == 200:
                        return
            except OSError:
                if self.process.poll() is not None:
                    raise RuntimeError("llama-server exited while starting") from None
            time.sleep(0.5)
        raise RuntimeError("llama-server didn't start")

    def _payload(self, prompt, route, temperature, max_tokens, stream):
        return {
            "prompt": prompt, "n_predict": max_tokens, "temperature": temperature, "top_p": 0.9,
            # Everyday chat needs a long penalty window so he stops repeating himself. In lore, that window
            # would cover the passages and put him off using their names, so it stays light there.
            "repeat_penalty": 1.05 if route == "lore" else self.repeat_penalty,
            "repeat_last_n": 64 if route == "lore" else 256,
            "presence_penalty": 0.0 if route == "lore" else self.presence_penalty,
            "stream": stream, "cache_prompt": False,
            # Every adapter is listed each time, because leaving one out would keep its last setting.
            "lora": [{"id": index, "scale": 1.0 if name == route else 0.0} for name, index in self.routes.items()],
        }

    def _request(self, payload):
        return urllib.request.Request(f"{self.url}/completion", json.dumps(payload).encode("utf-8"), {"Content-Type": "application/json"})

    def stream(self, prompt, route, temperature, max_tokens):
        """Yield text pieces, then a final dict of timing stats. A route of None means the plain model."""
        started = time.time()
        first = None
        with urllib.request.urlopen(self._request(self._payload(prompt, route, temperature, max_tokens, True)), timeout=600) as response:
            for raw in response:
                line = raw.decode("utf-8").strip()
                if not line.startswith("data: "):
                    continue
                item = json.loads(line[6:])
                if item.get("content"):
                    first = first or time.time()
                    yield item["content"]
                if item.get("stop"):
                    timings = item["timings"]
                    yield {
                        "tokens": timings["predicted_n"],
                        "first_token_s": round((first or time.time()) - started, 2),
                        "total_s": round(time.time() - started, 2),
                        "tokens_per_s": round(timings["predicted_per_second"], 1),
                    }

    def complete(self, prompt, route, temperature, max_tokens):
        with urllib.request.urlopen(self._request(self._payload(prompt, route, temperature, max_tokens, False)), timeout=600) as response:
            result = json.load(response)
        self.last_tokens = result["timings"]["predicted_n"]
        return result["content"]
