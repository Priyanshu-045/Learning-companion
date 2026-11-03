"""LLM backends. All expose chat(messages) -> str (messages = [{'role','content'}])."""
import json
import urllib.request

from .lang import LANG_NAMES


class OllamaLLM:
    """Desktop testing with a local Ollama server (https://ollama.com). NOT the on-device runtime."""

    def __init__(self, model="llama3.2:1b", host="http://localhost:11434", temperature=0.3, num_predict=700):
        self.model, self.host, self.temperature, self.num_predict = model, host, temperature, num_predict

    def chat(self, messages):
        body = json.dumps({"model": self.model, "messages": messages, "stream": False, "format": "json",
                           "options": {"temperature": self.temperature, "num_predict": self.num_predict}}).encode()
        req = urllib.request.Request(self.host + "/api/chat", body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())["message"]["content"]


class LlamaCppLLM:
    """Desktop testing with llama-cpp-python and any GGUF file: pip install llama-cpp-python"""

    def __init__(self, gguf_path, temperature=0.3, max_tokens=700, n_ctx=2048):
        from llama_cpp import Llama
        self.llm = Llama(model_path=gguf_path, n_ctx=n_ctx, verbose=False)
        self.temperature, self.max_tokens = temperature, max_tokens

    def chat(self, messages):
        out = self.llm.create_chat_completion(messages=messages, temperature=self.temperature,
                                              max_tokens=self.max_tokens, response_format={"type": "json_object"})
        return out["choices"][0]["message"]["content"]


# Words used by the mock so regional-language demos pass the script check (NOT real translation).
_MOCK_WORDS = {"en": ("Week", "Study", "Goal"), "hi": ("सप्ताह", "अध्ययन", "लक्ष्य"),
               "mr": ("आठवडा", "अभ्यास", "ध्येय"), "ta": ("வாரம்", "கற்றல்", "இலக்கு"),
               "te": ("వారం", "అభ్యాసం", "లక్ష్యం"), "bn": ("সপ্তাহ", "অধ্যয়ন", "লক্ষ্য")}


class MockLLM:
    """Rule-based stand-in so the whole pipeline runs with no model. Reads the JSON payload
    in the last user message and returns schema-valid JSON."""

    def chat(self, messages):
        first_user = next((m["content"] for m in messages if m["role"] == "user"), "{}")
        p = json.loads(first_user)
        week_w, study_w, goal_w = _MOCK_WORDS[p.get("language", "en")]
        if p.get("task") == "fill_week":
            tasks, day = [], 1
            for f in p["focus"]:
                total = f["hours"] * 60
                sessions = max(1, -(-int(total) // 60))
                for _ in range(sessions):
                    label = f["name"] + (" (revision)" if f["revision"] else "")
                    tasks.append({"day": day, "task": f"{study_w}: {label}", "minutes": int(total / sessions),
                                  "resource": p["allowed_resources"][0]})
                    day = day % 5 + 1
            names = ", ".join(f["name"] for f in p["focus"])
            return json.dumps({"title": f"{week_w} {p['week']}: {names}", "tasks": tasks,
                               "milestone": f"{goal_w}: {names}"}, ensure_ascii=False)
        if "topic" in p:
            qs = [{"q": f"{study_w} {p['topic']} #{i + 1}?", "options": ["A", "B", "C", "D"], "answer_index": i % 4}
                  for i in range(p.get("count", 5))]
            return json.dumps({"questions": qs}, ensure_ascii=False)
        return "{}"


def make_llm(backend, model=None):
    if backend == "mock":
        return MockLLM()
    if backend == "ollama":
        return OllamaLLM(model or "llama3.2:1b")
    if backend == "llamacpp":
        if not model:
            raise ValueError("--model must be a path to a .gguf file for the llamacpp backend")
        return LlamaCppLLM(model)
    raise ValueError(f"unknown backend {backend}")
