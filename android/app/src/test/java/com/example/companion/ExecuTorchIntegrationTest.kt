package com.example.companion

import com.example.companion.core.*
import org.junit.Assert.*
import org.junit.Test
import java.io.File

class ExecuTorchIntegrationTest {

    private val sampleGraph = SkillGraph.parse(
        """
        {
          "domain": "ml_engineer",
          "title": "ML Engineer",
          "nodes": [
            {"id": "linear_algebra", "name": "Linear Algebra", "prereqs": [], "hours": 4.0, "resources": ["3Blue1Brown", "Gilbert Strang"]},
            {"id": "quantization", "name": "Model Quantization", "prereqs": ["linear_algebra"], "hours": 6.0, "resources": ["PyTorch quantization documentation"]},
            {"id": "ondevice_deploy", "name": "On-Device Deployment", "prereqs": ["quantization"], "hours": 6.0, "resources": ["ExecuTorch documentation"]}
          ]
        }
        """.trimIndent()
    )

    @Test
    fun testStripPromptEchoAndSpecialTokens() {
        val prompt = "<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\nHello<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
        val rawWithEcho = "${prompt}{\"title\":\"Week 1\"}<|eot_id|>"
        assertEquals("{\"title\":\"Week 1\"}", ExecuTorchEngine.stripPromptEchoAndSpecialTokens(rawWithEcho, prompt))

        val rawWithoutBos = prompt.removePrefix("<|begin_of_text|>") + "{\"title\":\"Week 1\"}<|end_of_text|>"
        assertEquals("{\"title\":\"Week 1\"}", ExecuTorchEngine.stripPromptEchoAndSpecialTokens(rawWithoutBos, prompt))
    }

    @Test
    fun testMissingModelTriggersFallbackSafely() {
        val missingEngine = ExecuTorchEngine(
            modelPath = "/nonexistent/path/model.pte",
            tokenizerPath = "/nonexistent/path/tokenizer.model"
        )
        assertFalse(missingEngine.load())
        assertFalse(missingEngine.isLoaded)
        assertNotNull(missingEngine.lastError)

        val week = Week(week = 1, items = listOf(PlanItem(node = "linear_algebra", hours = 4.0)))
        val generator = RoadmapGenerator(missingEngine, "Return JSON in {LANGUAGE_NAME}.")
        val result = generator.fillWeek(sampleGraph, week, Lang.HI, "Learn ML", 10.0)

        assertEquals("fallback", result.source)
        assertTrue(result.tasks.isNotEmpty())
        assertEquals(240, result.tasks.sumOf { it.minutes })
    }

    @Test
    fun testFillWeekUsesLlmWhenValidAndFallsBackOnTruncatedJson() {
        val validEngine = object : LlmEngine {
            override fun chat(messages: List<ChatMessage>, maxTokens: Int): String = """
                {
                  "title": "Week 1: Linear Algebra Foundations",
                  "milestone": "Complete vector spaces and eigen-decomposition problem sets",
                  "tasks": [
                    {"day": 1, "node": "linear_algebra", "task": "Watch vector space lectures", "minutes": 120, "resource": "3Blue1Brown"},
                    {"day": 2, "node": "linear_algebra", "task": "Solve matrix elimination problems", "minutes": 120, "resource": "Gilbert Strang"}
                  ]
                }
            """.trimIndent()
        }
        val week = Week(week = 1, items = listOf(PlanItem(node = "linear_algebra", hours = 4.0)))
        val llmResult = RoadmapGenerator(validEngine, "System {LANGUAGE_NAME}").fillWeek(sampleGraph, week, Lang.EN, "Master ML", 10.0)
        assertEquals("llm", llmResult.source)
        assertEquals("Week 1: Linear Algebra Foundations", llmResult.title)
        assertEquals(240, llmResult.tasks.sumOf { it.minutes })

        val truncatedEngine = object : LlmEngine {
            override fun chat(messages: List<ChatMessage>, maxTokens: Int): String =
                "{\"title\": \"Week 1\", \"tasks\": [{\"day\": 1, \"task\": \"Incomplete"
        }
        val fbResult = RoadmapGenerator(truncatedEngine, "System {LANGUAGE_NAME}").fillWeek(sampleGraph, week, Lang.EN, "Master ML", 10.0)
        assertEquals("fallback", fbResult.source)
        assertEquals(240, fbResult.tasks.sumOf { it.minutes })
    }

    @Test
    fun testCompactPromptEliminatesConflictingExampleIdsAndRawPreviousWeekJson() {
        val systemFile = File("src/main/assets/prompts/system_roadmap.txt")
        if (systemFile.exists()) {
            val sysText = systemFile.readText()
            assertFalse("Conflicting example ID practice_module_b must be removed", sysText.contains("practice_module_b"))
            assertFalse("Conflicting example ID core_module_a must be removed", sysText.contains("core_module_a"))
            assertTrue("System prompt should stay compact (< 1500 chars)", sysText.length < 1500)
        }

        val week = Week(week = 2, items = listOf(PlanItem(node = "ondevice_deploy", hours = 6.0)))
        val summary = RoadmapGenerator.buildPriorSummary(
            graph = sampleGraph,
            completedNodes = listOf("linear_algebra", "quantization"),
            week = week,
            remainingHours = 6.0,
            remainingNodesCount = 1,
            lastAdaptation = "accelerated",
            weakSkills = listOf("quantization"),
            priorMilestone = "Quantize ResNet18 INT8"
        )
        val prompt = RoadmapGenerator.buildCompactWeekPrompt(
            graph = sampleGraph,
            week = week,
            lang = Lang.EN,
            goal = "Deploy models on phone",
            weeklyHours = 10.0,
            progressSummary = summary
        )
        assertTrue(prompt.contains("\"ondevice_deploy\""))
        assertTrue(prompt.contains("ExecuTorch documentation"))
        assertTrue(prompt.contains("adaptation=accelerated"))
        assertTrue(prompt.contains("prereqs_done=[Model Quantization]"))
        assertFalse("Prompt must not echo raw previous_week JSON key", prompt.contains("\"previous_week\""))
        assertFalse("Completed node ID must not appear as JSON node binding", prompt.contains("\"node\":\"quantization\""))
        assertFalse("Focus formatting must not include non-JSON fraction part=1/1", prompt.contains("part="))
        assertFalse("Focus formatting must not include resources=[...] array literal", prompt.contains("resources=["))
    }

    @Test
    fun testBoundedSeqLenAndConciseRetryRecovery() {
        val shortPrompt = "<|begin_of_text|>Hello"
        val boundedShort = ExecuTorchEngine.computeBoundedSeqLen(shortPrompt, 128)
        assertTrue(boundedShort in 128..ExecuTorchEngine.MAX_MODEL_SEQ_LEN)

        val longPrompt = "x".repeat(6000)
        assertEquals(ExecuTorchEngine.MAX_MODEL_SEQ_LEN, ExecuTorchEngine.computeBoundedSeqLen(longPrompt, 380))

        // Attempt 1 fails with wrong node ID; Attempt 2 must use concise retry prompt without replaying full history and recover
        var callCount = 0
        val capturedRetries = mutableListOf<List<ChatMessage>>()
        val flakyEngine = object : LlmEngine {
            override fun chat(messages: List<ChatMessage>, maxTokens: Int): String {
                callCount++
                capturedRetries.add(messages)
                return if (callCount == 1) {
                    """{"title":"Week 2","milestone":"Build deployment","tasks":[{"day":1,"node":"quantization","task":"Wrong node","minutes":360,"resource":"ExecuTorch documentation"}]}"""
                } else {
                    """{"title":"Week 2: Model Quantization & On-Device Deployment","milestone":"Quantize and deploy Llama model cleanly","tasks":[{"day":1,"node":"quantization","task":"Quantize weights","minutes":180,"resource":"PyTorch quantization documentation"},{"day":3,"node":"ondevice_deploy","task":"Run PTE on Android","minutes":180,"resource":"ExecuTorch documentation"}]}"""
                }
            }
        }
        val multiWeek = Week(
            week = 2,
            items = listOf(PlanItem("quantization", 3.0), PlanItem("ondevice_deploy", 3.0))
        )
        val recovered = RoadmapGenerator(flakyEngine, "System {LANGUAGE_NAME}").fillWeek(
            graph = sampleGraph,
            week = multiWeek,
            lang = Lang.EN,
            goal = "Master On-Device ML",
            weeklyHours = 6.0
        )
        assertEquals("llm", recovered.source)
        assertEquals(2, callCount)
        // Concise retry uses 2 messages (short system + fix instruction), not a 4-turn conversation replay
        assertEquals(2, capturedRetries[1].size)
        assertTrue(capturedRetries[1][1].content.contains("Fix error:"))
        assertTrue(recovered.tasks.groupBy { it.day }.values.all { dayTasks -> dayTasks.sumOf { it.minutes } <= 120 })
    }
}

