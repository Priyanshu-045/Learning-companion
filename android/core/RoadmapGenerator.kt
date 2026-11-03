package com.example.companion

import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.ceil
import kotlin.math.roundToInt

/**
 * LLM fills one week at a time; validation + one retry + deterministic fallback so the UI never crashes.
 * @param systemTemplate contents of assets/prompts/system_roadmap.txt (contains {LANGUAGE_NAME})
 */
class RoadmapGenerator(private val engine: LlmEngine, private val systemTemplate: String) {

    fun fillWeek(graph: SkillGraph, week: Week, lang: Lang, goal: String, weeklyHours: Double, attempts: Int = 2): Week {
        val nodes = graph.nodes.associateBy { it.id }
        val allowed = week.items.flatMap { nodes.getValue(it.node).resources }.distinct()
        val budget = (week.items.sumOf { it.hours } * 60).roundToInt()
        val payload = JSONObject()
            .put("task", "fill_week").put("language", lang.code).put("goal", goal)
            .put("week", week.week).put("weekly_hours", weeklyHours)
            .put("focus", JSONArray(week.items.map {
                JSONObject().put("node", it.node).put("name", nodes.getValue(it.node).name)
                    .put("hours", it.hours).put("revision", it.revision)
            }))
            .put("allowed_resources", JSONArray(allowed))
        val messages = mutableListOf(
            ChatMessage("system", systemTemplate.replace("{LANGUAGE_NAME}", lang.displayName)),
            ChatMessage("user", payload.toString())
        )
        val terms = (nodes.values.map { it.name } + allowed).sortedByDescending { it.length }
        for (attempt in 1..attempts) {
            var raw = ""
            try {
                raw = engine.chat(messages)
                val v = WeekValidator.validate(WeekValidator.extractJson(raw), budget, allowed)
                var text = (listOf(v.title, v.milestone) + v.tasks.map { it.task }).joinToString(" ")
                terms.forEach { text = text.replace(it, " ") } // English topic names are allowed technical terms
                if (!LanguageDetector.scriptOk(text, lang))
                    throw ValidationError("all text values must be written only in ${lang.displayName}")
                return week.copy(title = v.title, tasks = v.tasks, milestone = v.milestone, source = "llm")
            } catch (e: ValidationError) {
                messages += ChatMessage("assistant", raw)
                messages += ChatMessage("user", "Invalid output: ${e.message}. Return only the corrected JSON object.")
            } catch (e: Exception) {
                break // engine failure (model missing / OOM): go straight to fallback
            }
        }
        return templateWeek(week, nodes)
    }

    /** Last-resort deterministic week (English). Ship translated UI strings here before release. */
    private fun templateWeek(week: Week, nodes: Map<String, SkillNode>): Week {
        val tasks = mutableListOf<Task>()
        var k = 0
        for (item in week.items) {
            val n = nodes.getValue(item.node)
            val total = item.hours * 60
            val sessions = maxOf(1, ceil(total / 60).toInt())
            val minutes = maxOf(5, ((total / sessions) / 5).roundToInt() * 5)
            for (s in 0 until sessions) {
                tasks += Task(k % 5 + 1, (if (item.revision) "Revise " else "Study ") + n.name, minutes, n.resources[0])
                k++
            }
        }
        val names = week.items.joinToString(", ") { nodes.getValue(it.node).name }
        return week.copy(title = "Week ${week.week}: $names", tasks = tasks,
            milestone = "Finish the listed topics and note one question for each", source = "fallback")
    }
}
