import json
import unittest

from companion.lang import detect_language, script_ok
from companion.testing import MockLLM
from companion.planner import load_graph, find_gaps, topo_order, pack, list_domains
from companion.roadmap import (build_plan, adapt_plan, extract_json, validate_week, ValidationError,
                               generate_quiz)


class Flaky:
    """Returns garbage first, then valid output (tests retry)."""
    def __init__(self): self.calls, self.inner = 0, MockLLM()
    def chat(self, m):
        self.calls += 1
        return "sure! here you go" if self.calls == 1 else self.inner.chat(m)


class Broken:
    def chat(self, m): raise RuntimeError("model not loaded")


class WrongScript:
    """Always answers in English even when Hindi is requested."""
    def chat(self, m):
        p = json.loads(m[0 if False else -1]["content"]) if m[-1]["role"] == "user" and m[-1]["content"].startswith("{") else {}
        return MockLLM().chat([{"role": "user", "content": json.dumps({**p, "language": "en"})}]) if p else "{}"


class LanguageTests(unittest.TestCase):
    def test_detect(self):
        self.assertEqual(detect_language("Plan my ML career"), "en")
        self.assertEqual(detect_language("मुझे 1 महीने का डेटा साइंस प्लान चाहिए"), "hi")
        self.assertEqual(detect_language("मला एक महिन्याचा डेटा सायन्स प्लॅन पाहिजे"), "mr")
        self.assertEqual(detect_language("எனக்கு ஒரு மாத திட்டம் வேண்டும்"), "ta")
        self.assertEqual(detect_language("నాకు ఒక నెల ప్లాన్ కావాలి"), "te")
        self.assertEqual(detect_language("আমার এক মাসের পরিকল্পনা চাই"), "bn")

    def test_script_ok(self):
        self.assertTrue(script_ok("सप्ताह 1: PyTorch का अध्ययन", "hi"))
        self.assertFalse(script_ok("Week 1: study", "hi"))
        self.assertFalse(script_ok("सप्ताह வாரம்", "hi"))
        self.assertFalse(script_ok("Week 1 सप्ताह", "en"))


class PlannerTests(unittest.TestCase):
    def test_graphs_are_acyclic_and_complete(self):
        for d in list_domains():
            g = load_graph(d)
            ids = {n["id"] for n in g["nodes"]}
            self.assertEqual(set(topo_order(g)), ids)
            for n in g["nodes"]:
                self.assertTrue(set(n["prereqs"]) <= ids)
                self.assertTrue(n["resources"])

    def test_gaps_respect_prereqs(self):
        g = load_graph("ml_engineer")
        gaps = find_gaps(g, ["python_basics"])
        self.assertNotIn("python_basics", gaps)
        self.assertLess(gaps.index("numpy_pandas"), gaps.index("ml_fundamentals"))

    def test_pack_preserves_hours(self):
        q = [{"node": "a", "hours": 12, "revision": False}, {"node": "b", "hours": 3, "revision": False}]
        weeks = pack(q, 5)
        self.assertEqual(len(weeks), 3)
        self.assertAlmostEqual(sum(i["hours"] for w in weeks for i in w["items"]), 15)
        self.assertTrue(all(sum(i["hours"] for i in w["items"]) <= 5.01 for w in weeks))


class ValidationTests(unittest.TestCase):
    def test_extract_json_fences(self):
        self.assertEqual(extract_json('```json\n{"a":1}\n```'), {"a": 1})
        with self.assertRaises(ValidationError): extract_json("no json")

    def test_validate_snaps_resource_and_rescales(self):
        obj = {"title": "t", "milestone": "m",
               "tasks": [{"day": 2, "task": "x", "minutes": 10, "resource": "http://invented"},
                         {"day": 1, "task": "y", "minutes": 10, "resource": "R1"}]}
        out = validate_week(obj, 120, ["R1", "R2"])
        self.assertEqual([t["day"] for t in out["tasks"]], [1, 2])
        self.assertEqual(out["tasks"][1]["resource"], "R1")
        self.assertEqual(sum(t["minutes"] for t in out["tasks"]), 120)

    def test_rejects_bad_schema(self):
        for bad in [{}, {"title": "t", "milestone": "m", "tasks": []},
                    {"title": "t", "milestone": "m", "tasks": [{"day": 9, "task": "x", "minutes": 5}]},
                    {"title": "t", "milestone": "m", "tasks": [{"day": 1, "task": "x", "minutes": -1}]}]:
            with self.assertRaises(ValidationError): validate_week(bad, 60, [])


class PipelineTests(unittest.TestCase):
    def test_plan_english(self):
        p = build_plan(MockLLM(), "ml_engineer", 5, ["python_basics"], "en")
        self.assertTrue(all(w["source"] == "llm" for w in p["weeks"]))
        self.assertEqual(p["skill_gaps"][0], "linear_algebra")

    def test_plan_all_languages_pass_script_check(self):
        for lang in ["hi", "mr", "ta", "te", "bn"]:
            p = build_plan(MockLLM(), "data_analysis", 6, [], lang)
            self.assertTrue(all(w["source"] == "llm" for w in p["weeks"]), lang)

    def test_retry_recovers(self):
        f = Flaky()
        p = build_plan(f, "web_dev", 10, ["html_css", "git_basics", "js_basics", "dom_events", "react_basics",
                                           "node_express", "sql_db"], "en")
        self.assertEqual(p["weeks"][0]["source"], "llm")
        self.assertGreater(f.calls, 1)

    def test_backend_failure_falls_back(self):
        p = build_plan(Broken(), "web_dev", 10, [], "en")
        self.assertTrue(all(w["source"] == "fallback" and w["tasks"] for w in p["weeks"]))

    def test_wrong_language_is_rejected_then_falls_back(self):
        p = build_plan(WrongScript(), "web_dev", 10, [], "hi")
        self.assertTrue(all(w["source"] == "fallback" for w in p["weeks"]))

    def test_adapt_low_score_adds_revision(self):
        llm = MockLLM()
        p = build_plan(llm, "ml_engineer", 5, ["python_basics"], "en")
        total_before = sum(i["hours"] for w in p["weeks"] for i in w["items"])
        p2 = adapt_plan(llm, p, 1, 0.3)
        self.assertEqual(p2["adaptations"][-1]["action"], "revision_added")
        self.assertEqual(p2["weeks"][0]["score"], 0.3)
        self.assertGreater(sum(i["hours"] for w in p2["weeks"] for i in w["items"]), total_before)
        self.assertTrue(any(i["revision"] for i in p2["weeks"][1]["items"]))

    def test_adapt_high_score_shortens_plan(self):
        llm = MockLLM()
        p = build_plan(llm, "ml_engineer", 5, ["python_basics"], "en")
        before = sum(i["hours"] for w in p["weeks"] for i in w["items"])
        p2 = adapt_plan(llm, p, 1, 0.95)
        self.assertEqual(p2["adaptations"][-1]["action"], "accelerated")
        self.assertLess(sum(i["hours"] for w in p2["weeks"] for i in w["items"]), before)

    def test_adapt_mid_score_unchanged(self):
        llm = MockLLM()
        p = build_plan(llm, "ml_engineer", 5, [], "en")
        self.assertEqual(adapt_plan(llm, p, 1, 0.7)["adaptations"][-1]["action"], "unchanged")

    def test_quiz(self):
        self.assertEqual(len(generate_quiz(MockLLM(), "NumPy", "ta", 5)), 5)


if __name__ == "__main__":
    unittest.main()
