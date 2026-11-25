import json
import unittest

from companion.planner import pack, load_graph, find_gaps
from companion.roadmap import (
    build_plan, adapt_plan, validate_week, template_week, fill_week, ValidationError,
    redistribute_tasks, validate_workload, MAX_DAILY_MINUTES
)
from companion.testing import MockLLM


class ContextCapturingLLM:
    """Mock that records the messages received for each chat invocation."""
    def __init__(self):
        self.calls = []
        self.inner = MockLLM()

    def chat(self, messages):
        self.calls.append(list(messages))
        return self.inner.chat(messages)


class ProgressionMetadataTests(unittest.TestCase):
    def test_20h_topic_split_into_four_weeks(self):
        q = [{"node": "deep_learning", "hours": 20.0, "revision": False}]
        weeks = pack(q, 5.0)
        self.assertEqual(len(weeks), 4)

        expected = [
            {"part": 1, "total_parts": 4, "start": 0.0, "end": 5.0, "hours": 5.0},
            {"part": 2, "total_parts": 4, "start": 5.0, "end": 10.0, "hours": 5.0},
            {"part": 3, "total_parts": 4, "start": 10.0, "end": 15.0, "hours": 5.0},
            {"part": 4, "total_parts": 4, "start": 15.0, "end": 20.0, "hours": 5.0},
        ]
        for w, exp in zip(weeks, expected):
            self.assertEqual(len(w["items"]), 1)
            item = w["items"][0]
            self.assertEqual(item["node"], "deep_learning")
            self.assertEqual(item["hours"], exp["hours"])
            self.assertFalse(item["revision"])
            self.assertEqual(item["part"], exp["part"])
            self.assertEqual(item["total_parts"], exp["total_parts"])
            self.assertEqual(item["node_total_hours"], 20.0)
            self.assertEqual(item["cumulative_hours_start"], exp["start"])
            self.assertEqual(item["cumulative_hours_end"], exp["end"])

    def test_topic_completed_within_single_week(self):
        q = [{"node": "git_basics", "hours": 4.0, "revision": False}]
        weeks = pack(q, 5.0)
        self.assertEqual(len(weeks), 1)
        item = weeks[0]["items"][0]
        self.assertEqual(item["part"], 1)
        self.assertEqual(item["total_parts"], 1)
        self.assertEqual(item["node_total_hours"], 4.0)
        self.assertEqual(item["cumulative_hours_start"], 0.0)
        self.assertEqual(item["cumulative_hours_end"], 4.0)
        self.assertEqual(item["hours"], 4.0)

    def test_multiple_topics_retain_individual_progression(self):
        q = [
            {"node": "linear_algebra", "hours": 8.0, "revision": False},
            {"node": "prob_stats", "hours": 10.0, "revision": False},
        ]
        weeks = pack(q, 5.0)
        self.assertEqual(len(weeks), 4)

        # Week 1: linear_algebra Part 1/2 (0-5h)
        self.assertEqual(len(weeks[0]["items"]), 1)
        it = weeks[0]["items"][0]
        self.assertEqual(it["node"], "linear_algebra")
        self.assertEqual((it["part"], it["total_parts"]), (1, 2))
        self.assertEqual((it["cumulative_hours_start"], it["cumulative_hours_end"]), (0.0, 5.0))
        self.assertEqual(it["node_total_hours"], 8.0)

        # Week 2: linear_algebra Part 2/2 (5-8h) AND prob_stats Part 1/3 (0-2h)
        self.assertEqual(len(weeks[1]["items"]), 2)
        it1 = weeks[1]["items"][0]
        it2 = weeks[1]["items"][1]
        self.assertEqual(it1["node"], "linear_algebra")
        self.assertEqual((it1["part"], it1["total_parts"]), (2, 2))
        self.assertEqual((it1["cumulative_hours_start"], it1["cumulative_hours_end"]), (5.0, 8.0))

        self.assertEqual(it2["node"], "prob_stats")
        self.assertEqual((it2["part"], it2["total_parts"]), (1, 3))
        self.assertEqual((it2["cumulative_hours_start"], it2["cumulative_hours_end"]), (0.0, 2.0))
        self.assertEqual(it2["node_total_hours"], 10.0)

        # Week 3: prob_stats Part 2/3 (2-7h)
        self.assertEqual(len(weeks[2]["items"]), 1)
        it = weeks[2]["items"][0]
        self.assertEqual(it["node"], "prob_stats")
        self.assertEqual((it["part"], it["total_parts"]), (2, 3))
        self.assertEqual((it["cumulative_hours_start"], it["cumulative_hours_end"]), (2.0, 7.0))

        # Week 4: prob_stats Part 3/3 (7-10h)
        self.assertEqual(len(weeks[3]["items"]), 1)
        it = weeks[3]["items"][0]
        self.assertEqual(it["node"], "prob_stats")
        self.assertEqual((it["part"], it["total_parts"]), (3, 3))
        self.assertEqual((it["cumulative_hours_start"], it["cumulative_hours_end"]), (7.0, 10.0))

    def test_hour_totals_remain_unchanged(self):
        graph = load_graph("ml_engineer")
        gaps = find_gaps(graph, ["python_basics"])
        nodes = {n["id"]: n for n in graph["nodes"]}
        q = [{"node": g, "hours": nodes[g]["hours"], "revision": False} for g in gaps]
        total_q_hours = sum(i["hours"] for i in q)

        weeks = pack(q, 5.0)
        total_packed_hours = sum(i["hours"] for w in weeks for i in w["items"])
        self.assertAlmostEqual(total_q_hours, total_packed_hours, places=2)

    def test_prerequisite_ordering_remains_unchanged(self):
        graph = load_graph("ml_engineer")
        gaps = find_gaps(graph, [])
        nodes = {n["id"]: n for n in graph["nodes"]}
        q = [{"node": g, "hours": nodes[g]["hours"], "revision": False} for g in gaps]
        weeks = pack(q, 5.0)

        # Ensure first week starts with python_basics or prerequisites
        first_nodes = [i["node"] for i in weeks[0]["items"]]
        self.assertIn("python_basics", first_nodes)

        # Ensure calculus_opt appears after linear_algebra
        all_item_nodes = [i["node"] for w in weeks for i in w["items"]]
        la_index = max(idx for idx, nid in enumerate(all_item_nodes) if nid == "linear_algebra")
        calc_index = min(idx for idx, nid in enumerate(all_item_nodes) if nid == "calculus_opt")
        self.assertLessEqual(la_index, calc_index)

    def test_revision_items_compatible(self):
        q = [
            {"node": "python_basics", "hours": 3.0, "revision": True},
            {"node": "numpy_pandas", "hours": 5.0, "revision": False},
        ]
        weeks = pack(q, 5.0)
        self.assertTrue(weeks[0]["items"][0]["revision"])
        self.assertEqual(weeks[0]["items"][0]["part"], 1)
        self.assertEqual(weeks[0]["items"][0]["total_parts"], 1)
        self.assertFalse(weeks[0]["items"][1]["revision"])


class MaliciousMilestoneLLM:
    """Mock LLM that deliberately outputs rogue strings in title and milestone."""
    def __init__(self):
        self.calls = []

    def chat(self, messages):
        self.calls.append(list(messages))
        first_user = next((m["content"] for m in messages if m["role"] == "user"), "{}")
        p = json.loads(first_user)
        first_f = p["focus"][0]
        node_id = first_f["node"]
        res = first_f.get("allowed_resources", p.get("allowed_resources"))[0]
        return json.dumps({
            "title": f"WEEK 1 HACKED: {first_f['name']} in Keras",
            "milestone": f"Master {first_f['name']} using an unrelated 50-layer deep neural network",
            "tasks": [{"day": 1, "node": node_id, "task": f"Study {first_f['name']}", "minutes": 60, "resource": res}],
        })


class ContextChainingTests(unittest.TestCase):
    def test_next_week_contains_planner_derived_node_ids(self):
        llm = ContextCapturingLLM()
        plan = build_plan(llm, "ml_engineer", 5.0, ["python_basics", "numpy_pandas", "calculus_opt",
                                                    "ml_fundamentals", "pytorch_basics", "deep_learning",
                                                    "quantization", "ondevice_deploy"], "en")
        self.assertEqual(len(plan["weeks"]), 4)
        self.assertEqual(len(llm.calls), 4)

        # Week 1: Should NOT have "previous_week" in payload
        user_content_w1 = json.loads(llm.calls[0][1]["content"])
        self.assertNotIn("previous_week", user_content_w1)

        # Week 2: Contains planner-derived node IDs and parts
        user_content_w2 = json.loads(llm.calls[1][1]["content"])
        self.assertIn("previous_week", user_content_w2)
        prev_w2 = user_content_w2["previous_week"]
        self.assertEqual(prev_w2["week"], 1)
        self.assertIn("nodes", prev_w2)
        node_ids = [n["node"] for n in prev_w2["nodes"]]
        self.assertEqual(node_ids, ["linear_algebra"])
        self.assertEqual(prev_w2["nodes"][0]["part"], 1)
        self.assertEqual(prev_w2["nodes"][0]["total_parts"], 2)

    def test_next_week_does_not_contain_generated_milestone_or_title(self):
        llm = ContextCapturingLLM()
        plan = build_plan(llm, "ml_engineer", 5.0, ["python_basics", "numpy_pandas", "calculus_opt",
                                                    "ml_fundamentals", "pytorch_basics", "deep_learning",
                                                    "quantization", "ondevice_deploy"], "en")
        # Check all subsequent weeks (Week 2, 3, 4)
        for i in range(1, 4):
            raw_user_str = llm.calls[i][1]["content"]
            payload = json.loads(raw_user_str)
            prev = payload.get("previous_week", {})
            self.assertNotIn("title", prev)
            self.assertNotIn("milestone", prev)
            self.assertNotIn("tasks", prev)
            # Ensure the generated title of the previous week is nowhere in previous_week dict
            prev_generated_title = plan["weeks"][i - 1]["title"]
            prev_generated_ms = plan["weeks"][i - 1]["milestone"]
            self.assertNotIn(prev_generated_title, str(prev))
            self.assertNotIn(prev_generated_ms, str(prev))

    def test_malicious_milestone_cannot_contaminate_prompt(self):
        llm = MaliciousMilestoneLLM()
        plan = build_plan(llm, "ml_engineer", 5.0, ["python_basics", "numpy_pandas", "calculus_opt",
                                                    "ml_fundamentals", "pytorch_basics", "deep_learning",
                                                    "quantization", "ondevice_deploy"], "en")
        # Week 1 generated rogue title and milestone
        self.assertEqual(plan["weeks"][0]["title"], "WEEK 1 HACKED: Linear Algebra Refresher in Keras")
        self.assertIn("unrelated 50-layer deep neural network", plan["weeks"][0]["milestone"])

        # Inspect Week 2 prompt: MUST NOT contain any rogue text from Week 1!
        raw_prompt_w2 = llm.calls[1][1]["content"]
        self.assertNotIn("HACKED", raw_prompt_w2)
        self.assertNotIn("Keras", raw_prompt_w2)
        self.assertNotIn("50-layer", raw_prompt_w2)
        self.assertNotIn("unrelated", raw_prompt_w2)

        # Inspect previous_week in Week 2: only contains planner node "linear_algebra"
        payload_w2 = json.loads(raw_prompt_w2)
        prev_w2 = payload_w2["previous_week"]
        self.assertEqual(prev_w2["week"], 1)
        self.assertEqual(prev_w2["nodes"][0]["node"], "linear_algebra")

    def test_adapt_plan_preserves_planner_derived_context(self):
        llm = ContextCapturingLLM()
        plan = build_plan(llm, "ml_engineer", 5.0, ["python_basics", "numpy_pandas", "calculus_opt",
                                                    "ml_fundamentals", "pytorch_basics", "deep_learning",
                                                    "quantization", "ondevice_deploy"], "en")
        llm.calls.clear()

        # Adapt week 1 with a low score (adds revision)
        adapted = adapt_plan(llm, plan, 1, 0.4)
        self.assertGreater(len(adapted["weeks"]), 1)
        # The first regenerated week (week 2) should receive week 1 planner context
        user_content_first_new = json.loads(llm.calls[0][1]["content"])
        self.assertIn("previous_week", user_content_first_new)
        prev = user_content_first_new["previous_week"]
        self.assertEqual(prev["week"], 1)
        self.assertEqual(prev["nodes"][0]["node"], "linear_algebra")
        self.assertNotIn("title", prev)
        self.assertNotIn("milestone", prev)


class TopicResourceBindingAndCoverageTests(unittest.TestCase):
    def setUp(self):
        self.graph = load_graph("ml_engineer")
        self.nodes = {n["id"]: n for n in self.graph["nodes"]}
        self.focus_items = [
            {"node": "linear_algebra", "hours": 4.0, "revision": False, "part": 1, "total_parts": 2},
        ]
        self.node_resources = {
            "linear_algebra": ["3Blue1Brown: Essence of Linear Algebra", "Khan Academy: Linear Algebra"],
            "calculus_opt": ["3Blue1Brown: Essence of Calculus", "Khan Academy: Calculus"],
            "prob_stats": ["Khan Academy: Statistics and Probability", "StatQuest (YouTube)"],
        }
        self.node_names = {
            "linear_algebra": "Linear Algebra Refresher",
            "calculus_opt": "Calculus and Optimization Basics",
            "prob_stats": "Probability and Statistics",
        }
        self.allowed = ["3Blue1Brown: Essence of Linear Algebra", "Khan Academy: Linear Algebra"]

    def test_task_to_node_association_success(self):
        obj = {
            "title": "Week 1: Linear Algebra Refresher",
            "milestone": "Solve 5 systems of linear equations using matrix methods",
            "tasks": [
                {"day": 1, "node": "linear_algebra", "task": "Study vector spaces", "minutes": 120, "resource": "Khan Academy: Linear Algebra"},
                {"day": 3, "node": "linear_algebra", "task": "Practice matrix multiplications", "minutes": 120, "resource": "3Blue1Brown: Essence of Linear Algebra"},
            ]
        }
        res = validate_week(obj, 240, self.allowed, focus_items=self.focus_items, node_resources=self.node_resources, node_names=self.node_names)
        self.assertEqual(len(res["tasks"]), 2)
        for t in res["tasks"]:
            self.assertEqual(t["node"], "linear_algebra")
            self.assertIn(t["resource"], self.node_resources["linear_algebra"])

    def test_task_missing_node_rejected(self):
        obj = {
            "title": "Week 1: Linear Algebra",
            "milestone": "Solve systems of linear equations",
            "tasks": [
                {"day": 1, "task": "Study vector spaces", "minutes": 120, "resource": "Khan Academy: Linear Algebra"},
            ]
        }
        with self.assertRaises(ValidationError) as ctx:
            validate_week(obj, 120, self.allowed, focus_items=self.focus_items, node_resources=self.node_resources, node_names=self.node_names)
        self.assertIn("missing 'node'", str(ctx.exception))

    def test_task_unknown_node_rejected(self):
        obj = {
            "title": "Week 1: Linear Algebra",
            "milestone": "Solve systems of linear equations",
            "tasks": [
                {"day": 1, "node": "quantum_computing", "task": "Study qubits", "minutes": 120, "resource": "Khan Academy: Linear Algebra"},
            ]
        }
        with self.assertRaises(ValidationError) as ctx:
            validate_week(obj, 120, self.allowed, focus_items=self.focus_items, node_resources=self.node_resources, node_names=self.node_names)
        self.assertIn("not in current week's focus topics", str(ctx.exception))

    def test_cross_topic_resource_rejected(self):
        # linear_algebra task attempting to use a calculus resource
        obj = {
            "title": "Week 1: Linear Algebra",
            "milestone": "Solve systems of linear equations",
            "tasks": [
                {"day": 1, "node": "linear_algebra", "task": "Study vector spaces", "minutes": 120, "resource": "Khan Academy: Calculus"},
            ]
        }
        all_allowed = self.allowed + ["Khan Academy: Calculus"]
        with self.assertRaises(ValidationError) as ctx:
            validate_week(obj, 120, all_allowed, focus_items=self.focus_items, node_resources=self.node_resources, node_names=self.node_names)
        self.assertIn("different topic", str(ctx.exception))

    def test_unknown_resource_rejected(self):
        obj = {
            "title": "Week 1: Linear Algebra",
            "milestone": "Solve systems of linear equations",
            "tasks": [
                {"day": 1, "node": "linear_algebra", "task": "Study vector spaces", "minutes": 120, "resource": "https://hallucinated-course.org"},
            ]
        }
        with self.assertRaises(ValidationError) as ctx:
            validate_week(obj, 120, self.allowed, focus_items=self.focus_items, node_resources=self.node_resources, node_names=self.node_names)
        self.assertIn("not an allowed resource", str(ctx.exception))

    def test_mandatory_topic_coverage_multi_topic_success(self):
        focus = [
            {"node": "linear_algebra", "hours": 3.0, "revision": False},
            {"node": "prob_stats", "hours": 2.0, "revision": False},
        ]
        obj = {
            "title": "Week 2: Linear Algebra and Probability",
            "milestone": "Solve linear equations and compute conditional probabilities",
            "tasks": [
                {"day": 1, "node": "linear_algebra", "task": "Study matrix inversion", "minutes": 90, "resource": "Khan Academy: Linear Algebra"},
                {"day": 3, "node": "linear_algebra", "task": "Practice Gaussian elimination", "minutes": 90, "resource": "3Blue1Brown: Essence of Linear Algebra"},
                {"day": 5, "node": "prob_stats", "task": "Calculate conditional probabilities", "minutes": 120, "resource": "Khan Academy: Statistics and Probability"},
            ]
        }
        all_res = self.node_resources["linear_algebra"] + self.node_resources["prob_stats"]
        res = validate_week(obj, 300, all_res, focus_items=focus, node_resources=self.node_resources, node_names=self.node_names)
        covered = {t["node"] for t in res["tasks"]}
        self.assertEqual(covered, {"linear_algebra", "prob_stats"})

    def test_mandatory_topic_coverage_multi_topic_missing_one_rejected(self):
        focus = [
            {"node": "linear_algebra", "hours": 3.0, "revision": False},
            {"node": "prob_stats", "hours": 2.0, "revision": False},
        ]
        # Only linear_algebra tasks provided, prob_stats omitted!
        obj = {
            "title": "Week 2: Linear Algebra Refresher",
            "milestone": "Solve systems of linear equations",
            "tasks": [
                {"day": 1, "node": "linear_algebra", "task": "Study matrix inversion", "minutes": 90, "resource": "Khan Academy: Linear Algebra"},
                {"day": 3, "node": "linear_algebra", "task": "Practice Gaussian elimination", "minutes": 90, "resource": "3Blue1Brown: Essence of Linear Algebra"},
            ]
        }
        all_res = self.node_resources["linear_algebra"] + self.node_resources["prob_stats"]
        with self.assertRaises(ValidationError) as ctx:
            validate_week(obj, 180, all_res, focus_items=focus, node_resources=self.node_resources, node_names=self.node_names)
        err_msg = str(ctx.exception)
        self.assertIn("missing tasks for scheduled focus topic(s)", err_msg)
        self.assertIn("Probability and Statistics", err_msg)
        self.assertIn("prob_stats", err_msg)

    def test_generic_placeholder_milestones_rejected(self):
        generic_samples = [
            "Complete week",
            "Complete the week",
            "Finish topics",
            "Finish the topics",
            "Study scheduled material",
            "Study the material",
            "Complete all tasks",
            "finish tasks",
            "Weekly milestone",
            "TBD",
            "N/A",
            "Finish the listed topics",
        ]
        for gm in generic_samples:
            obj = {
                "title": "Week 1: Linear Algebra",
                "milestone": gm,
                "tasks": [
                    {"day": 1, "node": "linear_algebra", "task": "Study vectors", "minutes": 60, "resource": "Khan Academy: Linear Algebra"},
                ]
            }
            with self.assertRaises(ValidationError, msg=f"Milestone '{gm}' should be rejected as generic"):
                validate_week(obj, 60, self.allowed, focus_items=self.focus_items, node_resources=self.node_resources, node_names=self.node_names)

    def test_duplicate_consecutive_milestone_rejected(self):
        prior = "Solve 5 systems of linear equations using Gaussian elimination"
        obj = {
            "title": "Week 2: Linear Algebra Part 2",
            "milestone": "Solve 5 systems of linear equations using Gaussian elimination",  # Exact duplicate
            "tasks": [
                {"day": 1, "node": "linear_algebra", "task": "Study vector spaces", "minutes": 60, "resource": "Khan Academy: Linear Algebra"},
            ]
        }
        with self.assertRaises(ValidationError) as ctx:
            validate_week(obj, 60, self.allowed, focus_items=self.focus_items, node_resources=self.node_resources, node_names=self.node_names, prior_milestone=prior)
        self.assertIn("identical to the previous week's milestone", str(ctx.exception))

    def test_unrelated_milestone_rejected_in_english(self):
        obj = {
            "title": "Week 1: Linear Algebra",
            "milestone": "Deploy docker containers and configure kubernetes clusters on AWS",
            "tasks": [
                {"day": 1, "node": "linear_algebra", "task": "Study vector spaces", "minutes": 60, "resource": "Khan Academy: Linear Algebra"},
            ]
        }
        with self.assertRaises(ValidationError) as ctx:
            validate_week(obj, 60, self.allowed, focus_items=self.focus_items, node_resources=self.node_resources, node_names=self.node_names, lang="en")
        self.assertIn("does not reflect current week's focus topic(s)", str(ctx.exception))

    def test_template_week_contains_node_and_exclusive_resource(self):
        from companion.roadmap import template_week, MAX_DAILY_MINUTES
        import math
        week = {
            "week": 2,
            "items": [
                {"node": "linear_algebra", "hours": 3.0, "revision": False},
                {"node": "prob_stats", "hours": 2.0, "revision": True},
            ]
        }
        w = template_week(week, self.nodes, "en")
        la_tasks = [t for t in w["tasks"] if t["node"] == "linear_algebra"]
        ps_tasks = [t for t in w["tasks"] if t["node"] == "prob_stats"]
        # M2.2C: session count is ceil(total_minutes / MAX_DAILY_MINUTES)
        expected_la = max(1, math.ceil(3 * 60 / MAX_DAILY_MINUTES))
        expected_ps = max(1, math.ceil(2 * 60 / MAX_DAILY_MINUTES))
        self.assertEqual(len(la_tasks), expected_la)
        self.assertEqual(len(ps_tasks), expected_ps)
        self.assertEqual(len(w["tasks"]), expected_la + expected_ps)
        for t in la_tasks:
            self.assertEqual(t["resource"], self.nodes["linear_algebra"]["resources"][0])
        for t in ps_tasks:
            self.assertEqual(t["resource"], self.nodes["prob_stats"]["resources"][0])

    def test_legacy_validate_week_backward_compatibility(self):
        # Legacy callers pass only (obj, budget, allowed) without focus_items or node_resources
        obj = {
            "title": "Week 1",
            "milestone": "Complete personal practice",
            "tasks": [
                {"day": 2, "task": "Practice problems", "minutes": 30, "resource": "http://invented"},
                {"day": 1, "task": "Read textbook", "minutes": 30, "resource": "AllowedBook"},
            ]
        }
        out = validate_week(obj, 60, ["AllowedBook"])
        self.assertEqual(out["title"], "Week 1")
        self.assertEqual(out["milestone"], "Complete personal practice")
        self.assertEqual([t["day"] for t in out["tasks"]], [1, 2])
        # Invented resource was snapped to AllowedBook
        self.assertEqual(out["tasks"][1]["resource"], "AllowedBook")
        self.assertEqual(sum(t["minutes"] for t in out["tasks"]), 60)

    def test_fill_week_retry_prompt_names_missing_topic(self):
        from companion.roadmap import fill_week
        class MissingTopicThenRecoverLLM:
            def __init__(self):
                self.calls = []
            def chat(self, messages):
                self.calls.append(list(messages))
                if len(self.calls) == 1:
                    # Attempt 1: Omit prob_stats
                    return json.dumps({
                        "title": "Week 2: Multi-Topic",
                        "milestone": "Solve linear equations",
                        "tasks": [{"day": 1, "node": "linear_algebra", "task": "Study linear algebra", "minutes": 180, "resource": "Khan Academy: Linear Algebra"}]
                    })
                # Attempt 2: Recover with both topics
                return json.dumps({
                    "title": "Week 2: Multi-Topic",
                    "milestone": "Solve linear equations and calculate probability",
                    "tasks": [
                        {"day": 1, "node": "linear_algebra", "task": "Study linear algebra", "minutes": 180, "resource": "Khan Academy: Linear Algebra"},
                        {"day": 3, "node": "prob_stats", "task": "Study probability", "minutes": 120, "resource": "Khan Academy: Statistics and Probability"},
                    ]
                })

        mock_llm = MissingTopicThenRecoverLLM()
        week = {
            "week": 2,
            "items": [
                {"node": "linear_algebra", "hours": 3.0, "revision": False},
                {"node": "prob_stats", "hours": 2.0, "revision": False},
            ]
        }
        meta = {"language": "en", "goal": "ML", "weekly_hours": 5.0}
        res = fill_week(mock_llm, self.graph, week, meta, attempts=2)
        self.assertEqual(res["source"], "llm")
        self.assertEqual(res["attempts"], 2)

        # Inspect retry message (attempt 2 user prompt)
        retry_user_msg = mock_llm.calls[1][3]["content"]
        self.assertIn("missing tasks for scheduled focus topic(s)", retry_user_msg)
        self.assertIn("Probability and Statistics", retry_user_msg)
        self.assertIn("prob_stats", retry_user_msg)



class MilestoneReflectsFocusTests(unittest.TestCase):
    """Regression tests for milestone_reflects_focus() morphological matching."""

    def _make_focus(self, node_id, name, resources):
        focus = [{"node": node_id, "hours": 5.0, "revision": False}]
        node_names = {node_id: name}
        node_resources = {node_id: resources}
        return focus, node_names, node_resources

    def test_exact_word_match(self):
        """Direct word overlap should always match."""
        from companion.roadmap import milestone_reflects_focus
        focus, nn, nr = self._make_focus(
            "linear_algebra", "Linear Algebra",
            ["Khan Academy: Linear Algebra"]
        )
        ms = "Complete linear algebra exercises on vector spaces"
        self.assertTrue(milestone_reflects_focus(ms, focus, nn, nr))

    def test_morphological_variant_statistical_matches_statistics(self):
        """'statistical' vs 'statistics' — 5-char stem 'stati' must match."""
        from companion.roadmap import milestone_reflects_focus
        focus, nn, nr = self._make_focus(
            "prob_stats", "Probability and Statistics",
            ["Khan Academy: Statistics and Probability", "StatQuest (YouTube)"]
        )
        ms = "Develop and implement a statistical test for a new dataset"
        self.assertTrue(milestone_reflects_focus(ms, focus, nn, nr),
                        "'statistical' should match 'statistics' via 5-char stem")

    def test_morphological_variant_optimization_matches_optimize(self):
        """'optimization' vs 'optimize' — 5-char stem 'optim' must match."""
        from companion.roadmap import milestone_reflects_focus
        focus, nn, nr = self._make_focus(
            "calculus_opt", "Calculus and Optimization Basics",
            ["3Blue1Brown: Essence of Calculus", "Khan Academy: Calculus"]
        )
        ms = "Complete 3 optimization problems and implement gradient descent"
        self.assertTrue(milestone_reflects_focus(ms, focus, nn, nr),
                        "'optimization' should match 'optimize' via 5-char stem")

    def test_resource_name_match_bypasses_topic_check(self):
        """A milestone mentioning a resource name exactly should pass."""
        from companion.roadmap import milestone_reflects_focus
        focus, nn, nr = self._make_focus(
            "prob_stats", "Probability and Statistics",
            ["StatQuest (YouTube)", "Khan Academy: Statistics and Probability"]
        )
        ms = "Finish StatQuest playlist on distributions"
        self.assertTrue(milestone_reflects_focus(ms, focus, nn, nr))

    def test_unrelated_milestone_does_not_match(self):
        """A completely unrelated milestone must not spuriously match via stem."""
        from companion.roadmap import milestone_reflects_focus
        focus, nn, nr = self._make_focus(
            "linear_algebra", "Linear Algebra",
            ["Khan Academy: Linear Algebra"]
        )
        ms = "Deploy Docker containers and configure Kubernetes on AWS"
        self.assertFalse(milestone_reflects_focus(ms, focus, nn, nr))

    def test_short_words_below_stem_length_not_matched_by_stem(self):
        """Words shorter than STEM_LEN must not trigger a false stem match."""
        from companion.roadmap import milestone_reflects_focus
        # Node name contains "Data" (4 chars); milestone mentions "date" (4 chars).
        # Neither startswith the other; stem check requires len >= 5, so no match.
        focus, nn, nr = self._make_focus(
            "data_node", "Data Wrangling",
            ["Pandas Docs"]
        )
        ms = "Pick the best date format for your project"
        # 'date' and 'data' are both 4 chars — stem check skipped, no match
        self.assertFalse(milestone_reflects_focus(ms, focus, nn, nr))


class WorkloadDistributionTests(unittest.TestCase):
    """M2.2C: Deterministic Workload Distribution Tests."""

    def setUp(self):
        self.graph = load_graph("ml_engineer")
        self.nodes = {n["id"]: n for n in self.graph["nodes"]}
        self.focus_items = [
            {"node": "linear_algebra", "hours": 3.0, "revision": False},
            {"node": "prob_stats", "hours": 2.0, "revision": False},
        ]
        self.node_resources = {
            "linear_algebra": ["Khan Academy: Linear Algebra", "3Blue1Brown: Essence of Linear Algebra"],
            "prob_stats": ["Khan Academy: Statistics and Probability", "StatQuest (YouTube)"],
        }
        self.node_names = {
            "linear_algebra": "Linear Algebra",
            "prob_stats": "Probability and Statistics",
        }

    def test_300_minute_single_day_redistributed(self):
        """A single 300-min task concentrated on Day 1 is redistributed across multiple days (<=120 min each)."""
        tasks = [
            {
                "day": 1,
                "node": "linear_algebra",
                "task": "Intensive study of vector spaces and matrices",
                "minutes": 300,
                "resource": "Khan Academy: Linear Algebra",
            }
        ]
        result = redistribute_tasks(tasks, 300, max_daily=120)
        # All days must have load <= 120
        day_loads = {}
        for t in result:
            self.assertLessEqual(t["minutes"], 120)
            self.assertEqual(t["node"], "linear_algebra")
            self.assertEqual(t["resource"], "Khan Academy: Linear Algebra")
            day_loads[t["day"]] = day_loads.get(t["day"], 0) + t["minutes"]

        for d, load in day_loads.items():
            self.assertLessEqual(load, 120, f"Day {d} load {load} exceeds daily cap 120")

        self.assertEqual(sum(t["minutes"] for t in result), 300)
        self.assertEqual(len(day_loads), 3)  # 120 + 120 + 60 -> exactly 3 days
        validate_workload(result, 300, max_daily=120)

    def test_multiple_topics_same_week_preserves_both(self):
        """Redistribution handles multiple topics without starving either topic."""
        tasks = [
            {
                "day": 1,
                "node": "linear_algebra",
                "task": "Linear algebra deep dive",
                "minutes": 180,
                "resource": "Khan Academy: Linear Algebra",
            },
            {
                "day": 1,
                "node": "prob_stats",
                "task": "Probability basics",
                "minutes": 120,
                "resource": "Khan Academy: Statistics and Probability",
            },
        ]
        result = redistribute_tasks(tasks, 300, max_daily=120)

        # Validate that both topics preserved their exact minutes
        la_mins = sum(t["minutes"] for t in result if t["node"] == "linear_algebra")
        ps_mins = sum(t["minutes"] for t in result if t["node"] == "prob_stats")
        self.assertEqual(la_mins, 180)
        self.assertEqual(ps_mins, 120)
        self.assertEqual(sum(t["minutes"] for t in result), 300)

        # Check day loads
        day_loads = {}
        for t in result:
            day_loads[t["day"]] = day_loads.get(t["day"], 0) + t["minutes"]
        for d, load in day_loads.items():
            self.assertLessEqual(load, 120)

        # Must pass comprehensive workload validation
        validate_workload(
            result, 300, max_daily=120,
            focus_items=self.focus_items,
            node_resources=self.node_resources,
            original_tasks=tasks,
        )

    def test_daily_limit_enforced_in_validation(self):
        """validate_workload raises ValidationError if any day exceeds max_daily."""
        bad_tasks = [
            {"day": 1, "node": "linear_algebra", "task": "Study", "minutes": 130, "resource": "R"},
            {"day": 2, "node": "linear_algebra", "task": "Study", "minutes": 50, "resource": "R"},
        ]
        with self.assertRaises(ValidationError) as ctx:
            validate_workload(bad_tasks, 180, max_daily=120)
        self.assertIn("exceeds daily cap", str(ctx.exception))

    def test_weekly_minute_preservation(self):
        """Redistribution preserves exact total minutes across varied budgets."""
        for budget in [60, 150, 300, 450, 600]:
            tasks = [
                {"day": 1, "node": "linear_algebra", "task": f"Study {budget}", "minutes": budget, "resource": "R"}
            ]
            result = redistribute_tasks(tasks, budget, max_daily=120)
            self.assertEqual(sum(t["minutes"] for t in result), budget)
            validate_workload(result, budget, max_daily=120)

    def test_node_and_resource_preservation(self):
        """Each redistributed task preserves its node and resource association."""
        tasks = [
            {"day": 1, "node": "linear_algebra", "task": "LA task", "minutes": 200, "resource": "Khan Academy: Linear Algebra"},
            {"day": 1, "node": "prob_stats", "task": "PS task", "minutes": 100, "resource": "StatQuest (YouTube)"},
        ]
        result = redistribute_tasks(tasks, 300, max_daily=120)
        for t in result:
            if t["node"] == "linear_algebra":
                self.assertEqual(t["resource"], "Khan Academy: Linear Algebra")
            elif t["node"] == "prob_stats":
                self.assertEqual(t["resource"], "StatQuest (YouTube)")
            else:
                self.fail(f"Unexpected node {t['node']}")

    def test_fallback_schedule_validity(self):
        """Deterministic fallback weeks satisfy workload limits across all languages."""
        from companion.lang import LANG_NAMES
        week = {
            "week": 1,
            "items": [
                {"node": "linear_algebra", "hours": 5.0, "revision": False},
            ],
        }
        for lang in LANG_NAMES:
            fb = template_week(week, self.nodes, lang=lang)
            self.assertEqual(sum(t["minutes"] for t in fb["tasks"]), 300)
            day_loads = {}
            for t in fb["tasks"]:
                self.assertLessEqual(t["minutes"], 120)
                day_loads[t["day"]] = day_loads.get(t["day"], 0) + t["minutes"]
            for d, load in day_loads.items():
                self.assertLessEqual(load, 120, f"Fallback for {lang} day {d} exceeded 120 min")

    def test_adaptive_plan_schedule_validity(self):
        """Adaptive plan weeks satisfy workload constraints."""
        plan = build_plan(MockLLM(), "ml_engineer", 5.0, ["python_basics"], "en")
        # Adapt with low score (adds revision)
        adapted_low = adapt_plan(MockLLM(), plan, 1, 0.4)
        for w in adapted_low["weeks"]:
            day_loads = {}
            for t in w["tasks"]:
                self.assertLessEqual(t["minutes"], 120)
                day_loads[t["day"]] = day_loads.get(t["day"], 0) + t["minutes"]
            for d, load in day_loads.items():
                self.assertLessEqual(load, 120, f"Week {w['week']} day {d} exceeded cap in low adaptation")

        # Adapt with high score (accelerates)
        adapted_high = adapt_plan(MockLLM(), plan, 1, 0.9)
        for w in adapted_high["weeks"]:
            day_loads = {}
            for t in w["tasks"]:
                self.assertLessEqual(t["minutes"], 120)
                day_loads[t["day"]] = day_loads.get(t["day"], 0) + t["minutes"]
            for d, load in day_loads.items():
                self.assertLessEqual(load, 120, f"Week {w['week']} day {d} exceeded cap in high adaptation")

    def test_edge_case_short_weeks_and_small_workloads(self):
        """Short workloads (e.g. 1 hour = 60 min) do not create unnecessary days."""
        tasks = [
            {"day": 1, "node": "linear_algebra", "task": "Quick 1h review", "minutes": 60, "resource": "Khan Academy: Linear Algebra"}
        ]
        result = redistribute_tasks(tasks, 60, max_daily=120)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["day"], 1)
        self.assertEqual(result[0]["minutes"], 60)

    def test_edge_case_uneven_task_durations(self):
        """Uneven task durations (35m, 65m, 125m, 75m = 300m) are redistributed into valid days."""
        tasks = [
            {"day": 1, "node": "linear_algebra", "task": "T1", "minutes": 35, "resource": "Khan Academy: Linear Algebra"},
            {"day": 1, "node": "linear_algebra", "task": "T2", "minutes": 65, "resource": "Khan Academy: Linear Algebra"},
            {"day": 1, "node": "linear_algebra", "task": "T3", "minutes": 125, "resource": "Khan Academy: Linear Algebra"},
            {"day": 1, "node": "linear_algebra", "task": "T4", "minutes": 75, "resource": "Khan Academy: Linear Algebra"},
        ]
        result = redistribute_tasks(tasks, 300, max_daily=120)
        self.assertEqual(sum(t["minutes"] for t in result), 300)
        day_loads = {}
        for t in result:
            self.assertGreaterEqual(t["minutes"], 5)
            self.assertLessEqual(t["minutes"], 120)
            day_loads[t["day"]] = day_loads.get(t["day"], 0) + t["minutes"]
        for d, load in day_loads.items():
            self.assertLessEqual(load, 120)
        self.assertLessEqual(max(day_loads.keys()), 7)

    def test_budget_exceeds_7_days_capacity_rejected(self):
        """Budget exceeding 7 * max_daily raises ValidationError."""
        tasks = [
            {"day": 1, "node": "linear_algebra", "task": "Overloaded", "minutes": 900, "resource": "R"}
        ]
        with self.assertRaises(ValidationError) as ctx:
            redistribute_tasks(tasks, 900, max_daily=120)
        self.assertIn("exceeds maximum capacity of 7 days", str(ctx.exception))

    def test_validate_week_with_overloaded_llm_output_redistributes_cleanly(self):
        """validate_week accepts an LLM payload with an overloaded day and outputs a compliant schedule."""
        obj = {
            "title": "Week 1: Linear Algebra",
            "milestone": "Master linear algebra vector spaces and matrix operations",
            "tasks": [
                {"day": 1, "node": "linear_algebra", "task": "Study linear algebra full day", "minutes": 300, "resource": "Khan Academy: Linear Algebra"},
            ],
        }
        res = validate_week(
            obj,
            budget_minutes=300,
            allowed=self.node_resources["linear_algebra"],
            focus_items=[{"node": "linear_algebra", "hours": 5.0, "revision": False}],
            node_resources=self.node_resources,
            node_names=self.node_names,
            lang="en",
        )
        self.assertEqual(sum(t["minutes"] for t in res["tasks"]), 300)
        day_loads = {}
        for t in res["tasks"]:
            self.assertLessEqual(t["minutes"], 120)
            day_loads[t["day"]] = day_loads.get(t["day"], 0) + t["minutes"]
        for d, load in day_loads.items():
            self.assertLessEqual(load, 120)
        self.assertEqual(len(day_loads), 3)


class MultilingualQualityTests(unittest.TestCase):
    """M2.2D: Multilingual Quality and Consistency Tests across all six competition languages."""

    def setUp(self):
        self.graph = load_graph("ml_engineer")
        self.nodes = {n["id"]: n for n in self.graph["nodes"]}
        self.dataset = {
            "en": {
                "text": "I want to become a Machine Learning Engineer. I have 5 hours a week and already know python basics.",
                "lang": "en",
                "domain": "ml_engineer",
                "hours": 5.0,
                "known": ["python_basics"],
            },
            "hi": {
                "text": "मुझे मशीन लर्निंग इंजीनियर बनना है, सप्ताह में 5 घंटे पढ़ सकता हूँ और मुझे python basics पहले से आता है।",
                "lang": "hi",
                "domain": "ml_engineer",
                "hours": 5.0,
                "known": ["python_basics"],
            },
            "mr": {
                "text": "मला मशीन लर्निंग इंजिनिअर व्हायचे आहे, आठवड्यात 5 तास अभ्यास करू शकतो आणि मला आधीच python basics येते.",
                "lang": "mr",
                "domain": "ml_engineer",
                "hours": 5.0,
                "known": ["python_basics"],
            },
            "ta": {
                "text": "நான் இயந்திர கற்றல் பொறியாளர் ஆக விரும்புகிறேன், வாரத்திற்கு 5 மணிநேரம் படிக்க முடியும் மற்றும் python basics எனக்கு ஏற்கனவே தெரியும்.",
                "lang": "ta",
                "domain": "ml_engineer",
                "hours": 5.0,
                "known": ["python_basics"],
            },
            "te": {
                "text": "నేను మెషిన్ లెర్నింగ్ ఇంజనీర్ కావాలనుకుంటున్నాను, వారానికి 5 గంటలు చదవగలను మరియు నాకు python basics ఇప్పటికే తెలుసు.",
                "lang": "te",
                "domain": "ml_engineer",
                "hours": 5.0,
                "known": ["python_basics"],
            },
            "bn": {
                "text": "আমি মেশিন লার্নিং ইঞ্জিনিয়ার হতে চাই, সপ্তাহে ৫ ঘণ্টা পড়াশোনা করতে পারব এবং python basics আমার আগে থেকেই জানা আছে।",
                "lang": "bn",
                "domain": "ml_engineer",
                "hours": 5.0,
                "known": ["python_basics"],
            },
        }

    def test_language_detection_all_six_languages(self):
        """detect_language accurately detects each of the six competition languages."""
        from companion.lang import detect_language
        for code, data in self.dataset.items():
            detected = detect_language(data["text"])
            self.assertEqual(detected, code, f"Failed language detection for {code}: got {detected}")

    def test_hindi_marathi_devanagari_disambiguation(self):
        """Devanagari text is correctly disambiguated between Marathi and Hindi using vocabulary markers."""
        from companion.lang import detect_language
        # Marathi examples
        self.assertEqual(detect_language("मला डेटा सायन्स शिकायचे आहे, आठवड्यात ५ तास अभ्यास करायचा आहे"), "mr")
        self.assertEqual(detect_language("मशीन लर्निंगचा अभ्यास करण्यासाठी मला नवीन प्लॅन पाहिजे"), "mr")
        # Hindi examples
        self.assertEqual(detect_language("मुझे डेटा साइंस सीखना है, सप्ताह में 5 घंटे पढ़ना चाहता हूँ"), "hi")
        self.assertEqual(detect_language("मशीन लर्निंग का अध्ययन करने के लिए मुझे नया प्लान चाहिए"), "hi")

    def test_romanized_hindi_defaults_to_english_not_hindi(self):
        """Romanized Hindi (Latin script) is NOT falsely classified as Hindi."""
        from companion.lang import detect_language
        self.assertEqual(detect_language("mujhe machine learning sikhna hai, 5 ghante per week"), "en")
        self.assertEqual(detect_language("main data science sikhna chahta hu"), "en")

    def test_multilingual_intake_pipeline_all_six_languages(self):
        """Intake understand() extracts language, domain, hours, and known skills for all 6 languages."""
        from companion.intake import understand
        for code, data in self.dataset.items():
            profile = understand(data["text"])
            self.assertEqual(profile["language"], data["lang"], f"Wrong language for {code}")
            self.assertEqual(profile["domain"], data["domain"], f"Wrong domain for {code}")
            self.assertEqual(profile["weekly_hours"], data["hours"], f"Wrong hours for {code}")
            self.assertEqual(profile["known"], data["known"], f"Wrong known skills for {code}")

    def test_fallback_localization_all_six_languages(self):
        """Deterministic fallback weeks produce localized content passing script_ok for all 6 languages."""
        from companion.lang import script_ok, LANG_NAMES
        week = {
            "week": 1,
            "items": [
                {"node": "linear_algebra", "hours": 3.0, "revision": False},
                {"node": "prob_stats", "hours": 2.0, "revision": True},
            ],
        }
        for lang in ["en", "hi", "mr", "ta", "te", "bn"]:
            fb = template_week(week, self.nodes, lang=lang)
            self.assertIn("tasks", fb)
            self.assertTrue(len(fb["tasks"]) >= 2)
            # Check script validity
            text = " ".join([fb["title"], fb["milestone"]] + [t["task"] for t in fb["tasks"]])
            for term in ["Linear Algebra", "Probability and Statistics", "Khan Academy: Linear Algebra", "Khan Academy: Statistics and Probability"]:
                text = text.replace(term, " ")
            self.assertTrue(script_ok(text, lang), f"Fallback for {lang} ({LANG_NAMES[lang]}) failed script check: {text}")

    def test_language_consistency_across_multi_week_roadmap(self):
        """Roadmap generation preserves language setting consistently across all weeks."""
        from companion.lang import script_ok
        da_graph = load_graph("data_analysis")
        for lang in ["hi", "mr", "ta", "te", "bn"]:
            plan = build_plan(MockLLM(), "data_analysis", 6.0, [], lang)
            self.assertEqual(plan["language"], lang)
            self.assertTrue(len(plan["weeks"]) >= 3)
            for w in plan["weeks"]:
                text = " ".join([w["title"], w["milestone"]] + [t["task"] for t in w["tasks"]])
                # Strip known English terms from the data_analysis graph
                for n in da_graph["nodes"]:
                    text = text.replace(n["name"], " ")
                    for r in n["resources"]:
                        text = text.replace(r, " ")
                self.assertTrue(script_ok(text, lang), f"Week {w['week']} in plan for {lang} failed script check: {text}")

    def test_prevent_english_leakage_in_regional_script_ok(self):
        """script_ok rejects responses written predominantly in English when an Indic language is expected."""
        from companion.lang import script_ok
        # Pure English response must be rejected for Hindi
        self.assertFalse(script_ok("Week 1: Study linear algebra vectors and complete milestone", "hi"))
        # Pure English response must be rejected for Tamil
        self.assertFalse(script_ok("Week 1: Study linear algebra vectors and complete milestone", "ta"))
        # Pure English response must be rejected for Bengali
        self.assertFalse(script_ok("Week 1: Study linear algebra vectors and complete milestone", "bn"))


class AdaptiveLearningTests(unittest.TestCase):
    """M2.3: Adaptive Learning and Personalized Roadmap Updates Tests."""

    def setUp(self):
        self.llm = MockLLM()
        self.thresholds = {"mastery": 0.80, "reinforce": 0.60}
        self.plan = build_plan(self.llm, "ml_engineer", 5.0, ["python_basics"], "en")

    def test_1_high_quiz_score_allows_progression(self):
        """Score >= 0.80 demonstrates mastery and allows progression without adding revision."""
        p = adapt_plan(self.llm, self.plan, 1, 0.85, thresholds=self.thresholds)
        action = p["adaptations"][-1]["action"]
        self.assertIn(action, ("mastery_progression", "accelerated"))
        # Week 2 should advance to the next curriculum topic, not a revision
        self.assertFalse(any(i.get("revision") for i in p["weeks"][1]["items"]))

    def test_2_medium_quiz_score_triggers_reinforcement(self):
        """Score 0.60–0.79 reinforces topic with targeted practice."""
        p = adapt_plan(self.llm, self.plan, 1, 0.70, thresholds=self.thresholds)
        self.assertEqual(p["adaptations"][-1]["action"], "reinforced")
        # Week 2 should contain reinforcement item
        w2_items = p["weeks"][1]["items"]
        self.assertTrue(any(i.get("reinforce") for i in w2_items))

    def test_3_low_quiz_score_triggers_revision(self):
        """Score < 0.60 schedules revision before advancing."""
        p = adapt_plan(self.llm, self.plan, 1, 0.40, thresholds=self.thresholds)
        self.assertEqual(p["adaptations"][-1]["action"], "revision_added")
        w2_items = p["weeks"][1]["items"]
        self.assertTrue(any(i.get("revision") for i in w2_items))

    def test_4_completed_tasks_not_rescheduled(self):
        """Completed tasks remain recorded in week and are not rescheduled."""
        # Week 1 has tasks. Mark all completed
        tasks_count = len(self.plan["weeks"][0]["tasks"])
        completed_indices = list(range(tasks_count))
        p = adapt_plan(self.llm, self.plan, 1, 0.85, completed_tasks=completed_indices, thresholds=self.thresholds)
        # All tasks in week 1 marked completed
        self.assertTrue(all(t.get("completed") for t in p["weeks"][0]["tasks"]))
        # No completed tasks appear in future weeks
        self.assertEqual(p["weeks"][0]["tasks"][0]["task"], self.plan["weeks"][0]["tasks"][0]["task"])

    def test_5_incomplete_tasks_carried_forward(self):
        """Incomplete tasks from a week are carried forward into subsequent weeks."""
        # Mark only task 0 as completed; other tasks incomplete
        p = adapt_plan(self.llm, self.plan, 1, score=None, completed_tasks=[0], thresholds=self.thresholds)
        rec = p["adaptations"][-1]
        self.assertIn("incomplete_carried_forward", rec)
        # Week 2 should contain the carried forward item
        self.assertTrue(any(i.get("carried_forward") for i in p["weeks"][1]["items"]))

    def test_6_weak_prerequisite_identification(self):
        """Weak skills are tracked and foundational prerequisites scheduled for review."""
        # Low score on week 1
        p = adapt_plan(self.llm, self.plan, 1, 0.35, thresholds=self.thresholds)
        self.assertIn("weak_skills", p)
        # Node from week 1 tracked as weak
        w1_node = p["weeks"][0]["items"][0]["node"]
        self.assertIn(w1_node, p["weak_skills"])
        self.assertEqual(p["weak_skills"][w1_node], 0.35)

    def test_7_weekly_availability_increase(self):
        """Increasing weekly hours from 5 to 8 shortens roadmap length while respecting constraints."""
        initial_weeks = len(self.plan["weeks"])
        p = adapt_plan(self.llm, self.plan, 1, score=0.85, new_weekly_hours=8.0, thresholds=self.thresholds)
        self.assertEqual(p["weekly_hours"], 8.0)
        # With more hours per week, total remaining weeks should be fewer
        self.assertLess(len(p["weeks"]), initial_weeks)
        # Week 2 total study minutes should equal 8 * 60 = 480
        self.assertEqual(sum(t["minutes"] for t in p["weeks"][1]["tasks"]), 480)

    def test_8_weekly_availability_decrease(self):
        """Decreasing weekly hours from 5 to 3 expands roadmap length without dropping topics."""
        initial_weeks = len(self.plan["weeks"])
        p = adapt_plan(self.llm, self.plan, 1, score=0.85, new_weekly_hours=3.0, thresholds=self.thresholds)
        self.assertEqual(p["weekly_hours"], 3.0)
        # With fewer hours per week, total remaining weeks should increase
        self.assertGreater(len(p["weeks"]), initial_weeks)
        self.assertEqual(sum(t["minutes"] for t in p["weeks"][1]["tasks"]), 180)

    def test_9_daily_workload_limit_preserved_after_adaptation(self):
        """Even with increased hours (e.g. 8h/week), no day exceeds MAX_DAILY_MINUTES (120m)."""
        p = adapt_plan(self.llm, self.plan, 1, score=0.85, new_weekly_hours=8.0, thresholds=self.thresholds)
        for w in p["weeks"]:
            day_loads = {}
            for t in w["tasks"]:
                self.assertLessEqual(t["minutes"], 120)
                day_loads[t["day"]] = day_loads.get(t["day"], 0) + t["minutes"]
            for d, load in day_loads.items():
                self.assertLessEqual(load, 120, f"Week {w['week']} day {d} has {load}m > 120m")

    def test_10_topic_resource_binding_preserved_after_adaptation(self):
        """All tasks in adapted weeks strictly adhere to node-specific resources."""
        graph = load_graph("ml_engineer")
        nodes = {n["id"]: n for n in graph["nodes"]}
        p = adapt_plan(self.llm, self.plan, 1, score=0.40, thresholds=self.thresholds)
        for w in p["weeks"][1:]:
            for t in w["tasks"]:
                node_id = t["node"]
                allowed_resources = nodes[node_id]["resources"]
                self.assertIn(t["resource"], allowed_resources)

    def test_11_repeated_adaptation_no_duplicate_revision_loops(self):
        """Repeated low scores cap revisions and do not cause infinite loops or duplicates."""
        p = self.plan
        p = adapt_plan(self.llm, p, 1, 0.30, thresholds=self.thresholds)
        p = adapt_plan(self.llm, p, 2, 0.30, thresholds=self.thresholds)
        # Verify adaptation terminated and plan remains valid
        self.assertTrue(len(p["weeks"]) > 2)
        # Verify no infinite loop; weeks count is bounded
        self.assertLess(len(p["weeks"]), 50)

    def test_12_deterministic_adaptation_identical_inputs(self):
        """Identical inputs produce identical adapted roadmaps."""
        p1 = adapt_plan(self.llm, build_plan(self.llm, "ml_engineer", 5.0, ["python_basics"], "en"), 1, 0.40, thresholds=self.thresholds)
        p2 = adapt_plan(self.llm, build_plan(self.llm, "ml_engineer", 5.0, ["python_basics"], "en"), 1, 0.40, thresholds=self.thresholds)
        self.assertEqual(len(p1["weeks"]), len(p2["weeks"]))
        for w1, w2 in zip(p1["weeks"], p2["weeks"]):
            self.assertEqual(w1["items"], w2["items"])
            self.assertEqual(len(w1["tasks"]), len(w2["tasks"]))

    def test_13_multilingual_compatibility_adaptation(self):
        """Plan adaptation preserves regional language setting and passes script checks."""
        from companion.lang import script_ok
        p_hi = build_plan(self.llm, "ml_engineer", 5.0, ["python_basics"], "hi")
        adapted_hi = adapt_plan(self.llm, p_hi, 1, 0.40, thresholds=self.thresholds)
        self.assertEqual(adapted_hi["language"], "hi")
        # Check script validity of adapted week
        text = " ".join([adapted_hi["weeks"][1]["title"], adapted_hi["weeks"][1]["milestone"]] + [t["task"] for t in adapted_hi["weeks"][1]["tasks"]])
        graph = load_graph("ml_engineer")
        for n in graph["nodes"]:
            text = text.replace(n["name"], " ")
            for r in n["resources"]:
                text = text.replace(r, " ")
        self.assertTrue(script_ok(text, "hi"))

    def test_14_existing_regression_behaviour_preserved(self):
        """Legacy adapt_plan(llm, plan, 1, 0.7) without thresholds still produces action 'unchanged'."""
        p = adapt_plan(self.llm, self.plan, 1, 0.7)
        self.assertEqual(p["adaptations"][-1]["action"], "unchanged")

    def test_15_nan_and_inf_scores_rejected(self):
        """NaN, Inf, negative, and out-of-range quiz scores are rejected with ValueError."""
        import math
        for bad_score in [float("nan"), float("inf"), float("-inf"), -0.1, 1.1, "bad", True]:
            with self.assertRaises(ValueError):
                adapt_plan(self.llm, self.plan, 1, bad_score)

    def test_16_availability_action_labeling(self):
        """Updating availability without score labels action 'availability_updated'; with score labels both."""
        p_no_score = adapt_plan(self.llm, self.plan, 1, score=None, new_weekly_hours=4.0)
        self.assertEqual(p_no_score["adaptations"][-1]["action"], "availability_updated")
        self.assertIn("Weekly study time updated to 4.0h/week", p_no_score["adaptations"][-1].get("feedback", ""))

        p_with_score = adapt_plan(self.llm, self.plan, 1, score=0.85, new_weekly_hours=4.0, thresholds=self.thresholds)
        self.assertIn("hours_updated", p_with_score["adaptations"][-1]["action"])

    def test_17_revision_cycle_limit_resets_on_mastery(self):
        """Revision cycle counter tracks consecutive revisions and resets when a topic is mastered."""
        p = self.plan
        # Week 1: low score -> revised_nodes recorded
        p = adapt_plan(self.llm, p, 1, 0.30, thresholds=self.thresholds)
        self.assertIn("revised_nodes", p["adaptations"][-1])
        # Week 2: low score again -> revised_nodes recorded
        p = adapt_plan(self.llm, p, 2, 0.30, thresholds=self.thresholds)
        self.assertIn("revised_nodes", p["adaptations"][-1])
        # Week 3: high score -> mastered_nodes recorded, resets revision counter
        p = adapt_plan(self.llm, p, 3, 0.90, thresholds=self.thresholds)
        self.assertIn("mastered_nodes", p["adaptations"][-1])

    def test_18_learner_state_persistence_round_trip(self):
        """JSON serialization and deserialization of plan preserves all state and allows continued adaptation."""
        import tempfile
        import pathlib
        # 1. Adapt plan with score and incomplete tasks
        tasks_w1 = self.plan["weeks"][0]["tasks"]
        adapted_1 = adapt_plan(self.llm, self.plan, 1, score=0.40, completed_tasks=[0, 1], thresholds=self.thresholds)

        # 2. Save state to JSON file and reload fresh instance
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".json") as tmp:
            tmp_path = pathlib.Path(tmp.name)
            tmp_path.write_text(json.dumps(adapted_1, ensure_ascii=False, indent=2), encoding="utf-8")

        reloaded = json.loads(tmp_path.read_text(encoding="utf-8"))
        tmp_path.unlink()

        # 3. Verify all invariants
        self.assertEqual(reloaded["domain"], adapted_1["domain"])
        self.assertEqual(reloaded["language"], adapted_1["language"])
        self.assertEqual(reloaded["weekly_hours"], adapted_1["weekly_hours"])
        self.assertEqual(reloaded["weak_skills"], adapted_1["weak_skills"])
        self.assertEqual(len(reloaded["adaptations"]), len(adapted_1["adaptations"]))
        self.assertEqual(reloaded["weeks"][0]["score"], 0.40)
        self.assertTrue(reloaded["weeks"][0]["tasks"][0]["completed"])
        self.assertTrue(reloaded["weeks"][0]["tasks"][1]["completed"])
        self.assertFalse(reloaded["weeks"][0]["tasks"][2]["completed"])

        # 4. Adapt reloaded instance on week 2
        w2_tasks_count = len(reloaded["weeks"][1]["tasks"])
        adapted_2 = adapt_plan(self.llm, reloaded, 2, score=0.85, completed_tasks=list(range(w2_tasks_count)), thresholds=self.thresholds)
        self.assertEqual(len(adapted_2["adaptations"]), 2)
        self.assertEqual(adapted_2["weeks"][1]["score"], 0.85)
        self.assertTrue(all(t.get("completed") for t in adapted_2["weeks"][1]["tasks"]))


if __name__ == "__main__":
    unittest.main()

