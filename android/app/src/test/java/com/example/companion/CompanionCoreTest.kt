package com.example.companion

import com.example.companion.core.*
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.File

class CompanionCoreTest {

    private val sampleGraphJson = """
    {
      "domain": "ml_engineer",
      "title": "ML Engineer",
      "nodes": [
        {"id": "python_core", "name": "Python Core", "prereqs": [], "hours": 6.0, "resources": ["Python Docs", "Real Python"]},
        {"id": "linear_algebra", "name": "Linear Algebra", "prereqs": ["python_core"], "hours": 8.0, "resources": ["3Blue1Brown", "Gilbert Strang"]},
        {"id": "calculus", "name": "Multivariate Calculus", "prereqs": ["linear_algebra"], "hours": 6.0, "resources": ["Khan Academy", "MIT OCW"]},
        {"id": "neural_nets", "name": "Neural Networks", "prereqs": ["calculus"], "hours": 10.0, "resources": ["Deep Learning Book", "PyTorch Tutorials"]}
      ]
    }
    """.trimIndent()

    @Test
    fun testLanguageDetectionAllSixLanguages() {
        assertEquals(Lang.EN, LanguageDetector.detect("I want to learn linear algebra and machine learning"))
        assertEquals(Lang.HI, LanguageDetector.detect("मुझे मशीन लर्निंग और गणित सीखना है क्या आप मदद कर सकते हैं"))
        assertEquals(Lang.MR, LanguageDetector.detect("मला मशीन लर्निंग शिकायचे आहे आणि कॉम्प्युटर सायन्स करायचे आहे"))
        assertEquals(Lang.TA, LanguageDetector.detect("எனக்கு இயந்திர கற்றல் படிக்க வேண்டும் மற்றும் பைதான் கற்க வேண்டும்"))
        assertEquals(Lang.TE, LanguageDetector.detect("నాకు మెషిన్ లెర్నింగ్ మరియు డేటా సైన్స్ నేర్చుకోవాలని ఉంది"))
        assertEquals(Lang.BN, LanguageDetector.detect("আমি মেশিন লার্নিং এবং ডেটা সায়েন্স শিখতে চাই"))
    }

    @Test
    fun testSkillGraphParsingAndTopologicalOrder() {
        val graph = SkillGraph.parse(sampleGraphJson)
        assertEquals(4, graph.nodes.size)
        val topo = Planner.topoOrder(graph)
        assertEquals(listOf("python_core", "linear_algebra", "calculus", "neural_nets"), topo)

        val gaps = Planner.findGaps(graph, setOf("python_core"))
        assertEquals(listOf("linear_algebra", "calculus", "neural_nets"), gaps)
    }

    @Test
    fun testPackWithProgressionCoordinates() {
        val graph = SkillGraph.parse(sampleGraphJson)
        val queue = listOf(
            PlanItem("linear_algebra", 8.0),
            PlanItem("calculus", 6.0)
        )
        // 10 hours per week: week 1 gets 8h lin_alg + 2h calculus (part 1 of 2); week 2 gets 4h calculus (part 2 of 2)
        val weeks = Planner.pack(queue, 10.0)
        assertEquals(2, weeks.size)

        val w1 = weeks[0]
        assertEquals(2, w1.items.size)
        assertEquals("linear_algebra", w1.items[0].node)
        assertEquals(8.0, w1.items[0].hours, 0.01)
        assertEquals(1, w1.items[0].part)
        assertEquals(1, w1.items[0].totalParts)

        assertEquals("calculus", w1.items[1].node)
        assertEquals(2.0, w1.items[1].hours, 0.01)
        assertEquals(1, w1.items[1].part)
        assertEquals(2, w1.items[1].totalParts)
        assertEquals(0.0, w1.items[1].cumulativeHoursStart, 0.01)
        assertEquals(2.0, w1.items[1].cumulativeHoursEnd, 0.01)

        val w2 = weeks[1]
        assertEquals(1, w2.items.size)
        assertEquals("calculus", w2.items[0].node)
        assertEquals(4.0, w2.items[0].hours, 0.01)
        assertEquals(2, w2.items[0].part)
        assertEquals(2, w2.items[0].totalParts)
        assertEquals(2.0, w2.items[0].cumulativeHoursStart, 0.01)
        assertEquals(6.0, w2.items[0].cumulativeHoursEnd, 0.01)
    }

    @Test
    fun testDeterministicWorkloadDistributionCappedAt120Min() {
        val tasks = listOf(
            Task(day = 1, task = "Massive Lin Alg session", minutes = 300, resource = "3Blue1Brown", node = "linear_algebra")
        )
        val budgetMinutes = 300
        val redistributed = Planner.redistributeTasks(tasks, budgetMinutes, maxDaily = 120)

        // Must distribute across 3 days (120, 120, 60)
        assertEquals(300, redistributed.sumOf { it.minutes })
        val dayLoads = redistributed.groupBy { it.day }.mapValues { entry -> entry.value.sumOf { it.minutes } }
        for ((day, load) in dayLoads) {
            assertTrue("Day $day load $load exceeds 120", load <= 120)
        }
        assertEquals(3, dayLoads.size)
    }

    @Test
    fun testWeekValidatorStrictTopicBindingAndResourceChecking() {
        val budgetMinutes = 120
        val allowedResources = listOf("3Blue1Brown", "Gilbert Strang")
        val focusItems = listOf(PlanItem(node = "linear_algebra", hours = 2.0))
        val nodeResources = mapOf("linear_algebra" to allowedResources)

        val validJson = JSONObject("""
        {
          "title": "Week 1: Foundations",
          "milestone": "Solve system of linear equations and understand matrix multiplication",
          "tasks": [
            {"day": 1, "task": "Watch vectors series", "minutes": 60, "resource": "3Blue1Brown", "node": "linear_algebra"},
            {"day": 2, "task": "Practice dot product", "minutes": 60, "resource": "Gilbert Strang", "node": "linear_algebra"}
          ]
        }
        """.trimIndent())

        val result = WeekValidator.validate(validJson, budgetMinutes, allowedResources, focusItems, nodeResources)
        assertEquals("Week 1: Foundations", result.title)
        assertEquals(2, result.tasks.size)
        assertEquals(120, result.tasks.sumOf { it.minutes })
        assertEquals("linear_algebra", result.tasks[0].node)
    }

    @Test(expected = ValidationError::class)
    fun testWeekValidatorRejectsMissingTopic() {
        val budgetMinutes = 180
        val focusItems = listOf(
            PlanItem(node = "linear_algebra", hours = 2.0),
            PlanItem(node = "calculus", hours = 1.0)
        )
        val nodeResources = mapOf(
            "linear_algebra" to listOf("3Blue1Brown"),
            "calculus" to listOf("Khan Academy")
        )

        // Missing tasks for calculus
        val invalidJson = JSONObject("""
        {
          "title": "Week 1: Foundations",
          "milestone": "Solve system of linear equations",
          "tasks": [
            {"day": 1, "task": "Watch vectors series", "minutes": 180, "resource": "3Blue1Brown", "node": "linear_algebra"}
          ]
        }
        """.trimIndent())

        WeekValidator.validate(invalidJson, budgetMinutes, listOf("3Blue1Brown", "Khan Academy"), focusItems, nodeResources)
    }

    @Test
    fun testLocalizedFallbackTemplatesAllSixLanguages() {
        val graph = SkillGraph.parse(sampleGraphJson)
        val nodes = graph.nodes.associateBy { it.id }
        val week = Week(
            week = 1,
            items = listOf(PlanItem(node = "linear_algebra", hours = 2.0))
        )
        val generator = RoadmapGenerator(MockLlmEngine(), "system prompt")

        val langs = listOf(Lang.EN, Lang.HI, Lang.MR, Lang.TA, Lang.TE, Lang.BN)
        for (lang in langs) {
            val fbWeek = generator.templateWeek(week, nodes, lang)
            assertEquals("fallback", fbWeek.source)
            assertTrue(fbWeek.title!!.isNotBlank())
            assertTrue(fbWeek.milestone!!.isNotBlank())
            assertEquals(120, fbWeek.tasks.sumOf { it.minutes })
            assertTrue(fbWeek.tasks.all { it.node == "linear_algebra" })
            assertTrue(fbWeek.tasks.all { it.resource == "3Blue1Brown" })
        }
    }

    @Test
    fun testAdaptationAccelerationAndStateRoundTrip() {
        val graph = SkillGraph.parse(sampleGraphJson)
        val profile = LearnerProfile(
            goal = "Master Machine Learning",
            language = "en",
            knownSkills = listOf("python_core"),
            weeklyHours = 10.0,
            domain = "ml_engineer"
        )
        val items = listOf(
            PlanItem(node = "linear_algebra", hours = 8.0),
            PlanItem(node = "calculus", hours = 2.0)
        )
        val week1 = Week(week = 1, items = items, title = "Week 1", milestone = "Master Linear Algebra")
        val state = LearnerState(
            profile = profile,
            weeks = listOf(week1),
            currentWeekIndex = 0
        )

        // High score adaptation: >= 0.85 accelerates remaining queue
        val remaining = listOf(PlanItem(node = "neural_nets", hours = 10.0))
        val (adaptedQ, action) = Planner.adaptQueue(
            weekItems = week1.items,
            remaining = remaining,
            score = 0.90
        )
        assertEquals("accelerated", action)
        assertEquals(1, adaptedQ.size)
        // 10.0 * 0.75 = 7.5 hours
        assertEquals(7.5, adaptedQ[0].hours, 0.01)

        // Test JSON round-trip persistence
        val jsonStr = state.toJson().toString()
        val reloaded = LearnerState.fromJson(JSONObject(jsonStr))
        assertEquals(state.profile.goal, reloaded.profile.goal)
        assertEquals(state.profile.domain, reloaded.profile.domain)
        assertEquals(state.profile.language, reloaded.profile.language)
        assertEquals(state.weeks.size, reloaded.weeks.size)
        assertEquals(state.weeks[0].items[0].node, reloaded.weeks[0].items[0].node)
    }
}

