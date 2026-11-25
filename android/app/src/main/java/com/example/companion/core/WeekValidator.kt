package com.example.companion.core

import org.json.JSONObject
import kotlin.math.max
import kotlin.math.roundToInt

class ValidationError(message: String) : Exception(message)

data class ValidWeek(
    val title: String,
    val tasks: List<Task>,
    val milestone: String
)

object WeekValidator {
    private val GENERIC_MILESTONES = setOf(
        "complete week", "complete the week", "finish week", "finish the week",
        "complete topics", "complete the topics", "finish topics", "finish the topics",
        "finish all topics", "study scheduled material", "study material", "study the material",
        "study topics", "complete all tasks", "complete tasks", "finish tasks",
        "weekly milestone", "milestone", "goal", "tbd", "na", "n/a", "none"
    )

    fun extractJson(text: String): JSONObject {
        var t = text.trim()
            .removePrefix("```json").removePrefix("```")
            .removeSuffix("```").trim()
        val a = t.indexOf('{')
        val b = t.lastIndexOf('}')
        if (a == -1 || b <= a) throw ValidationError("no JSON object found")
        val clean = t.substring(a, b + 1).replace(Regex(",\\s*([}\\]])"), "$1")
        return try {
            JSONObject(clean)
        } catch (e: Exception) {
            throw ValidationError("invalid JSON: ${e.message}")
        }
    }

    private fun isGenericMilestone(text: String): Boolean {
        val clean = text.lowercase().replace(Regex("[^a-z0-9\\s]"), "").trim()
        if (clean in GENERIC_MILESTONES) return true
        val words = clean.split(Regex("\\s+"))
        return words.size <= 2 && words.any { it in setOf("complete", "finish", "week", "milestone", "goal") }
    }

    fun validate(
        obj: JSONObject,
        budgetMinutes: Int,
        allowedResources: List<String>,
        focusItems: List<PlanItem>? = null,
        nodeResources: Map<String, List<String>>? = null
    ): ValidWeek {
        val title = obj.optString("title", "").trim()
        val milestone = obj.optString("milestone", "").trim()
        if (title.isEmpty()) throw ValidationError("missing 'title'")
        if (milestone.isEmpty()) throw ValidationError("missing 'milestone'")
        if (isGenericMilestone(milestone)) {
            throw ValidationError("generic placeholder milestone '$milestone' is not acceptable; describe a concrete outcome")
        }

        val arr = obj.optJSONArray("tasks")
            ?: throw ValidationError("'tasks' must be a list of 1-14 items")
        if (arr.length() !in 1..14) {
            throw ValidationError("'tasks' must be a list of 1-14 items")
        }

        val focusNodeIds = focusItems?.map { it.node }?.toSet() ?: emptySet()
        val coveredNodes = mutableSetOf<String>()
        val rawTasks = mutableListOf<Task>()

        for (i in 0 until arr.length()) {
            val t = arr.optJSONObject(i) ?: throw ValidationError("each task must be an object")
            val day = t.optInt("day", -1)
            if (day !in 1..7) throw ValidationError("'day' must be an integer 1-7")
            val text = t.optString("task", t.optString("description", "")).trim()
            if (text.isEmpty()) throw ValidationError("task text missing")
            val mins = t.optDouble("minutes", -1.0)
            if (mins.isNaN() || mins <= 0) throw ValidationError("'minutes' must be a positive number")

            val node = if (t.has("node") && !t.isNull("node")) t.getString("node").trim() else null
            if (focusItems != null) {
                if (node == null || node.isEmpty()) throw ValidationError("task missing 'node'")
                if (node !in focusNodeIds) {
                    throw ValidationError("task node '$node' is not in focus topics $focusNodeIds")
                }
                coveredNodes.add(node)
            }

            var res = t.optString("resource", "").trim()
            if (nodeResources != null && node != null) {
                val validForNode = nodeResources[node] ?: emptyList()
                if (res.isEmpty()) throw ValidationError("task for node '$node' missing 'resource'")
                val match = validForNode.firstOrNull { it.equals(res, ignoreCase = true) }
                    ?: throw ValidationError("resource '$res' is not an allowed resource for node '$node'. Allowed: $validForNode")
                res = match
            } else if (allowedResources.isNotEmpty()) {
                if (res !in allowedResources) res = allowedResources[0]
            }

            rawTasks.add(Task(day = day, task = text, minutes = mins.roundToInt(), resource = res, node = node))
        }

        if (focusItems != null) {
            val missing = focusNodeIds - coveredNodes
            if (missing.isNotEmpty()) {
                throw ValidationError("missing tasks for mandatory focus topic(s): $missing")
            }
        }

        // Rescale task minutes proportionally to exact budget
        val rawTotal = rawTasks.sumOf { it.minutes }
        val scale = budgetMinutes.toDouble() / max(1, rawTotal)
        var scaledTasks = rawTasks.map {
            it.copy(minutes = max(5, (it.minutes * scale / 5).roundToInt() * 5))
        }

        // Fix rounding drift
        val drift = scaledTasks.sumOf { it.minutes } - budgetMinutes
        if (drift != 0 && scaledTasks.isNotEmpty()) {
            val last = scaledTasks.last()
            scaledTasks = scaledTasks.dropLast(1) + last.copy(minutes = max(5, last.minutes - drift))
        }

        // Deterministic workload redistribution (max 120 min/day)
        val distributedTasks = Planner.redistributeTasks(scaledTasks, budgetMinutes)
        return ValidWeek(title = title, tasks = distributedTasks, milestone = milestone)
    }
}

