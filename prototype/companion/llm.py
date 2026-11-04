"""LLM backends for DESKTOP development. All are Llama-family only (see models.py).
The on-device runtime is ExecuTorch (android/); these are for prompt/JSON tuning on a PC.
All expose chat(messages) -> str, plus `.family` and `.model_id` (recorded in every plan)."""
import json
import os
import urllib.request

from .models import check_ollama_model, check_gguf

DEFAULT_MODEL = "llama3.2:1b"  # Meta Llama 3.2 1B Instruct (Ollama default tag is the instruct build)


class OllamaLLM:
    family = "llama"

    def __init__(self, model=DEFAULT_MODEL, host="http://localhost:11434", temperature=0.3, num_predict=700,
                 allow_derivative=False):
        self.kind = check_ollama_model(model, allow_derivative)
        self.model, self.host, self.temperature, self.num_predict = model, host, temperature, num_predict
        self.model_id = f"ollama:{model} ({self.kind})"
        self.last_stats = {}

    def chat(self, messages):
        body = json.dumps({"model": self.model, "messages": messages, "stream": False, "format": "json",
                           "options": {"temperature": self.temperature, "num_predict": self.num_predict}}).encode()
        req = urllib.request.Request(self.host + "/api/chat", body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.loads(r.read())
        # Ollama reports eval_count / eval_duration(ns): real decode speed on THIS machine (not the phone).
        self.last_stats = {k: data.get(k) for k in ("eval_count", "eval_duration", "prompt_eval_count",
                                                     "prompt_eval_duration", "total_duration")}
        return data["message"]["content"]


class LlamaCppLLM:
    """llama-cpp-python with a Llama GGUF (architecture + name checked before loading)."""
    family = "llama"

    def __init__(self, gguf_path, temperature=0.3, max_tokens=700, n_ctx=2048, allow_derivative=False):
        self.kind = check_gguf(gguf_path, allow_derivative)
        from llama_cpp import Llama  # pip install llama-cpp-python
        self.llm = Llama(model_path=gguf_path, n_ctx=n_ctx, verbose=False)
        self.temperature, self.max_tokens = temperature, max_tokens
        self.model_id = f"gguf:{os.path.basename(gguf_path)} ({self.kind})"

    def chat(self, messages):
        out = self.llm.create_chat_completion(messages=messages, temperature=self.temperature,
                                              max_tokens=self.max_tokens, response_format={"type": "json_object"})
        return out["choices"][0]["message"]["content"]


def make_llm(backend, model=None, allow_derivative=False):
    if backend == "ollama":
        return OllamaLLM(model or DEFAULT_MODEL, allow_derivative=allow_derivative)
    if backend == "llamacpp":
        if not model:
            raise ValueError("--model must be a path to a Llama .gguf file for the llamacpp backend")
        return LlamaCppLLM(model, allow_derivative=allow_derivative)
    if backend == "mock":
        if os.environ.get("COMPANION_ALLOW_MOCK") != "1":
            raise ValueError("the mock backend is for unit tests only (not a Llama model). "
                             "Set COMPANION_ALLOW_MOCK=1 to run a pipeline smoke test.")
        from .testing import MockLLM
        return MockLLM()
    raise ValueError(f"unknown backend {backend}")
