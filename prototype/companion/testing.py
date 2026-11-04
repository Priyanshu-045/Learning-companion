"""TEST-ONLY helpers. MockLLM is NOT a Llama model and must never serve the final pipeline."""
import json

# Words so regional-language tests pass the script check (NOT real translation).
_MOCK_WORDS = {"en": ("Week", "Study", "Goal"), "hi": ("सप्ताह", "अध्ययन", "लक्ष्य"),
               "mr": ("आठवडा", "अभ्यास", "ध्येय"), "ta": ("வாரம்", "கற்றல்", "இலக்கு"),
               "te": ("వారం", "అభ్యాసం", "లక్ష్యం"), "bn": ("সপ্তাহ", "অধ্যয়ন", "লক্ষ্য")}


class MockLLM:
    family = "mock"
    model_id = "MOCK (not a Llama model; pipeline tests only)"

    def chat(self, messages):
        first_user = next((m["content"] for m in messages if m["role"] == "user"), "{}")
        try:
            p = json.loads(first_user)
        except json.JSONDecodeError:
            return "{}"
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
            return json.dumps({"title": f"{week_w} {p['week']}: {names}", "milestone": f"{goal_w}: {names}",
                               "tasks": tasks}, ensure_ascii=False)
        if "topic" in p:
            qs = [{"q": f"{study_w} {p['topic']} #{i + 1}?", "options": ["A", "B", "C", "D"], "answer_index": i % 4}
                  for i in range(p.get("count", 5))]
            return json.dumps({"questions": qs}, ensure_ascii=False)
        return "{}"
