"""One regression test per defect found in the M0 audit (see AUDIT.md)."""
import math
import signal
import unittest

from companion.planner import pack, validate_hours
from companion.roadmap import build_plan, adapt_plan, generate_quiz, validate_week, ValidationError
from companion.testing import MockLLM


class Hang(Exception):
    pass


def _alarm(*_):
    raise Hang("took >3s (infinite loop?)")


class RegressionTests(unittest.TestCase):
    def setUp(self):
        signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(3)

    def tearDown(self):
        signal.alarm(0)

    # D1: pack() looped forever when weekly_hours <= 0
    def test_zero_and_negative_hours_rejected_not_hung(self):
        q = [{"node": "a", "hours": 5, "revision": False}]
        for bad in (0, -1, float("nan"), float("inf"), "5", True, None, 101):
            with self.assertRaises(ValueError, msg=repr(bad)):
                pack(q, bad)
        self.assertEqual(validate_hours(5), 5.0)

    def test_build_plan_rejects_bad_hours(self):
        with self.assertRaises(ValueError):
            build_plan(MockLLM(), "web_dev", 0, [], "en")

    # D2: unknown skill ids were silently ignored
    def test_unknown_known_ids_rejected(self):
        with self.assertRaisesRegex(ValueError, "nonsense"):
            build_plan(MockLLM(), "web_dev", 5, ["nonsense"], "en")

    def test_unknown_language_and_domain_rejected(self):
        with self.assertRaises(ValueError):
            build_plan(MockLLM(), "web_dev", 5, [], "fr")
        with self.assertRaises(ValueError):
            build_plan(MockLLM(), "astrology", 5, [], "en")

    # D3: knowing everything produced an empty plan and a confusing adapt crash
    def test_all_known_is_complete_state(self):
        from companion.planner import load_graph
        ids = [n["id"] for n in load_graph("web_dev")["nodes"]]
        p = build_plan(MockLLM(), "web_dev", 5, ids, "en")
        self.assertEqual((p["status"], p["weeks"]), ("complete", []))
        with self.assertRaisesRegex(ValueError, "no weeks"):
            adapt_plan(MockLLM(), p, 1, 0.5)

    # D4: adapt accepted any score (5, nan) and out-of-order / repeated weeks
    def test_adapt_rejects_bad_scores(self):
        p = build_plan(MockLLM(), "web_dev", 5, [], "en")
        for bad in (5, -0.1, float("nan"), True, "0.5"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                adapt_plan(MockLLM(), p, 1, bad)

    def test_adapt_must_be_sequential_and_once(self):
        llm = MockLLM()
        p = build_plan(llm, "web_dev", 5, [], "en")
        with self.assertRaisesRegex(ValueError, "earlier weeks"):
            adapt_plan(llm, p, 2, 0.7)
        p = adapt_plan(llm, p, 1, 0.7)
        with self.assertRaisesRegex(ValueError, "already has"):
            adapt_plan(llm, p, 1, 0.7)
        p = adapt_plan(llm, p, 2, 0.7)  # in order is fine
        self.assertEqual([w["score"] for w in p["weeks"][:2]], [0.7, 0.7])

    def test_adapting_preserves_earlier_scores(self):
        llm = MockLLM()
        p = adapt_plan(llm, adapt_plan(llm, build_plan(llm, "ml_engineer", 5, [], "en"), 1, 0.9), 2, 0.2)
        self.assertEqual([w.get("score") for w in p["weeks"][:3]], [0.9, 0.2, None])

    # D5: infinite minutes escaped as a raw ValueError (skipping the retry path)
    def test_infinite_minutes_is_validation_error(self):
        obj = {"title": "t", "milestone": "m",
               "tasks": [{"day": 1, "task": "x", "minutes": float("inf"), "resource": "r"}]}
        with self.assertRaises(ValidationError):
            validate_week(obj, 60, ["r"])
        self.assertTrue(math.isinf(float("inf")))

    # D6: quiz generation leaked raw backend exceptions
    def test_quiz_backend_error_is_clean(self):
        class Down:
            def chat(self, m):
                raise RuntimeError("server down")
        with self.assertRaisesRegex(ValidationError, "backend error"):
            generate_quiz(Down(), "x", "en")

    # D7: provenance of every plan is recorded
    def test_plan_records_model(self):
        self.assertIn("MOCK", build_plan(MockLLM(), "web_dev", 5, [], "en")["generated_by"])

    # D8: the mock must not be handed out unless explicitly allowed
    def test_mock_backend_is_gated(self):
        import os
        from companion.llm import make_llm
        os.environ.pop("COMPANION_ALLOW_MOCK", None)
        with self.assertRaisesRegex(ValueError, "unit tests only"):
            make_llm("mock")
        os.environ["COMPANION_ALLOW_MOCK"] = "1"
        try:
            self.assertEqual(make_llm("mock").family, "mock")
        finally:
            del os.environ["COMPANION_ALLOW_MOCK"]


if __name__ == "__main__":
    unittest.main()
