import math
import unittest

from companion.lang import LANG_NAMES, script_ok
from companion.planner import load_graph
from companion.roadmap import (
    ValidationError,
    extract_json,
    parse_minutes,
    validate_week,
    template_week,
    fill_week,
    build_plan,
)
from companion.testing import MockLLM


class DoubleFlaky:
    """Always returns malformed output to test fallback attempt counting."""
    def __init__(self):
        self.calls = 0

    def chat(self, m):
        self.calls += 1
        return "not valid json at all"


class MockWithSentMessages:
    """Captures messages received on chat calls."""
    def __init__(self):
        self.calls = []
        self.inner = MockLLM()

    def chat(self, messages):
        self.calls.append(list(messages))
        if len(self.calls) == 1:
            return "{\"title\": \"t\", \"tasks\": []}"  # Invalid: tasks is empty
        return self.inner.chat(messages)


class MinutesParsingTests(unittest.TestCase):
    def test_numeric_inputs(self):
        self.assertEqual(parse_minutes(60), 60.0)
        self.assertEqual(parse_minutes(45.5), 45.5)

    def test_minute_string_formats(self):
        self.assertEqual(parse_minutes("60"), 60.0)
        self.assertEqual(parse_minutes("60 mins"), 60.0)
        self.assertEqual(parse_minutes("60 min"), 60.0)
        self.assertEqual(parse_minutes("60 minutes"), 60.0)
        self.assertEqual(parse_minutes("45m"), 45.0)

    def test_hour_string_formats(self):
        self.assertEqual(parse_minutes("1.5 hours"), 90.0)
        self.assertEqual(parse_minutes("1 hour"), 60.0)
        self.assertEqual(parse_minutes("2 hrs"), 120.0)
        self.assertEqual(parse_minutes("0.5 hr"), 30.0)
        self.assertEqual(parse_minutes("2.5h"), 150.0)

    def test_invalid_and_ambiguous_rejected(self):
        bad_cases = [
            "60-90 mins",
            "about 60 mins",
            "fast",
            "0 mins",
            "0 hours",
            "0",
            "-10",
            "-1.5 hours",
            "",
            "   ",
            True,
            False,
            None,
            float("inf"),
            float("-inf"),
            float("nan"),
            [],
            {},
        ]
        for bad in bad_cases:
            with self.assertRaises(ValidationError, msg=f"Failed to reject: {bad!r}"):
                parse_minutes(bad)


    def test_day_validation_rejects_and_does_not_clamp(self):
        # Day must be 1-7. Day 0, 8, 9, -1 must be rejected, not clamped.
        for bad_day in [0, 8, 9, -1, 100]:
            obj = {
                "title": "Week 1",
                "milestone": "Do something",
                "tasks": [{"day": bad_day, "task": "Study", "minutes": 60, "resource": "R1"}]
            }
            with self.assertRaises(ValidationError, msg=f"Day {bad_day} should be rejected"):
                validate_week(obj, 60, ["R1"])

        # Valid string day "3" is accepted as 3
        obj = {
            "title": "Week 1",
            "milestone": "Do something",
            "tasks": [{"day": "3", "task": "Study", "minutes": 60, "resource": "R1"}]
        }
        res = validate_week(obj, 60, ["R1"])
        self.assertEqual(res["tasks"][0]["day"], 3)


class JsonValidationAndNormalizationTests(unittest.TestCase):
    def test_trailing_comma_tolerance(self):
        raw = '{"title": "Week 1", "milestone": "Complete topic", "tasks": [{"day": 1, "task": "Study", "minutes": 60, "resource": "R1",},],}'
        obj = extract_json(raw)
        self.assertEqual(obj["title"], "Week 1")
        self.assertEqual(obj["milestone"], "Complete topic")
        self.assertEqual(len(obj["tasks"]), 1)

    def test_milestone_synonym_normalization(self):
        # Test "goal", "weekly_milestone", "project" as milestone fallbacks
        for key in ["weekly_milestone", "milestone_goal", "goal", "project"]:
            obj = {
                "title": "Week 1",
                key: "Build linear regression model",
                "tasks": [{"day": 1, "task": "Study", "minutes": 60, "resource": "R1"}]
            }
            res = validate_week(obj, 60, ["R1"])
            self.assertEqual(res["milestone"], "Build linear regression model")

    def test_milestone_list_normalization(self):
        obj = {
            "title": "Week 1",
            "milestone": ["Part A: solve equations.", "Part B: write tests."],
            "tasks": [{"day": 1, "task": "Study", "minutes": 60, "resource": "R1"}]
        }
        res = validate_week(obj, 60, ["R1"])
        self.assertEqual(res["milestone"], "Part A: solve equations. Part B: write tests.")

    def test_output_schema_order(self):
        obj = {
            "title": "Week 1",
            "milestone": "Achieve goal",
            "tasks": [{"day": 1, "task": "Study", "minutes": 60, "resource": "R1"}]
        }
        res = validate_week(obj, 60, ["R1"])
        keys = list(res.keys())
        self.assertEqual(keys, ["title", "milestone", "tasks"])


class LocalizedFallbackTests(unittest.TestCase):
    def setUp(self):
        self.graph = load_graph("ml_engineer")
        self.nodes = {n["id"]: n for n in self.graph["nodes"]}
        self.week = {"week": 1, "items": [{"node": "linear_algebra", "hours": 5.0, "revision": False}]}

    def test_all_six_languages_pass_script_check(self):
        for lang in ["en", "hi", "mr", "ta", "te", "bn"]:
            w = template_week(self.week, self.nodes, lang)
            self.assertIn("title", w)
            self.assertIn("milestone", w)
            self.assertIn("tasks", w)
            self.assertGreaterEqual(len(w["tasks"]), 1)

            text = f"{w['title']} {w['milestone']} " + " ".join(t["task"] for t in w["tasks"])
            # Remove English topic name for script_ok check
            text_clean = text.replace("Linear Algebra Refresher", " ")
            self.assertTrue(script_ok(text_clean, lang), f"Failed script_ok for {lang}: {text}")

    def test_hindi_fallback_content(self):
        w = template_week(self.week, self.nodes, "hi")
        self.assertTrue(w["title"].startswith("सप्ताह 1:"))
        self.assertTrue(any("अध्ययन" in t["task"] for t in w["tasks"]))
        self.assertIn("सूचीबद्ध", w["milestone"])

    def test_marathi_fallback_content(self):
        w = template_week(self.week, self.nodes, "mr")
        self.assertTrue(w["title"].startswith("आठवडा 1:"))
        self.assertTrue(any("अभ्यास" in t["task"] for t in w["tasks"]))
        self.assertIn("नोंदवा", w["milestone"])

    def test_tamil_fallback_content(self):
        w = template_week(self.week, self.nodes, "ta")
        self.assertTrue(w["title"].startswith("வாரம் 1:"))
        self.assertTrue(any("கற்க" in t["task"] for t in w["tasks"]))

    def test_telugu_fallback_content(self):
        w = template_week(self.week, self.nodes, "te")
        self.assertTrue(w["title"].startswith("వారం 1:"))
        self.assertTrue(any("అధ్యయనం" in t["task"] for t in w["tasks"]))

    def test_bengali_fallback_content(self):
        w = template_week(self.week, self.nodes, "bn")
        self.assertTrue(w["title"].startswith("সপ্তাহ 1:"))
        self.assertTrue(any("অধ্যয়ন" in t["task"] for t in w["tasks"]))


class AttemptTrackingAndRetryMessageTests(unittest.TestCase):
    def test_first_attempt_success_records_attempts_1(self):
        p = build_plan(MockLLM(), "ml_engineer", 5, ["python_basics"], "en")
        for w in p["weeks"]:
            self.assertEqual(w["source"], "llm")
            self.assertEqual(w["attempts"], 1)

    def test_retry_recovery_records_attempts_2(self):
        mock = MockWithSentMessages()
        graph = load_graph("data_analysis")
        week = {"week": 1, "items": [{"node": "sql_basics", "hours": 5.0, "revision": False}]}
        meta = {"goal": "Data Analyst", "language": "en", "weekly_hours": 5.0}

        w = fill_week(mock, graph, week, meta, attempts=2)
        self.assertEqual(w["source"], "llm")
        self.assertEqual(w["attempts"], 2)

        # Inspect the retry messages sent to chat
        self.assertEqual(len(mock.calls), 2)
        retry_msgs = mock.calls[1]
        self.assertEqual(len(retry_msgs), 4)
        # Verify raw broken output is NOT repeated into assistant message
        assistant_msg = retry_msgs[2]["content"]
        self.assertNotIn("{\"title\": \"t\", \"tasks\": []}", assistant_msg)
        # Verify user correction message has schema guidance
        user_correction = retry_msgs[3]["content"]
        self.assertIn("milestone", user_correction)
        self.assertIn("Schema:", user_correction)

    def test_double_failure_records_fallback_with_attempts_2(self):
        flaky = DoubleFlaky()
        graph = load_graph("data_analysis")
        week = {"week": 1, "items": [{"node": "sql_basics", "hours": 5.0, "revision": False}]}
        meta = {"goal": "Data Analyst", "language": "en", "weekly_hours": 5.0}

        w = fill_week(flaky, graph, week, meta, attempts=2)
        self.assertEqual(w["source"], "fallback")
        self.assertEqual(w["attempts"], 2)
        self.assertEqual(flaky.calls, 2)
        self.assertIn("no JSON object found", w["error"])


if __name__ == "__main__":
    unittest.main()

