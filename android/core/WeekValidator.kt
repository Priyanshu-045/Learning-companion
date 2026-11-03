package com.example.companion

import org.json.JSONObject
import kotlin.math.max
import kotlin.math.roundToInt

class ValidationError(message: String) : Exception(message)

data class ValidWeek(val title: String, val tasks: List<Task>, val milestone: String)

/** Strict schema check + deterministic clean-up. Port of validate_week in roadmap.py. */
object WeekValidator {
    fun extractJson(text: String): JSONObject {
        val t = text.trim().removePrefix("```json").removePrefix("```").removeSuffix("```").trim()
        val a = t.indexOf('{'); val b = t.lastIndexOf('}')
        if (a == -1 || b <= a) throw ValidationError("no JSON object found")
        return try { JSONObject(t.substring(a, b + 1)) } catch (e: Exception) { throw ValidationError("invalid JSON: ${e.message}") }
    }

    fun validate(obj: JSONObject, budgetMinutes: Int, allowed: List<String>): ValidWeek {
        val title = obj.optString("title", "").trim()
        val milestone = obj.optString("milestone", "").trim()
        if (title.isEmpty()) throw ValidationError("missing 'title'")
        if (milestone.isEmpty()) throw ValidationError("missing 'milestone'")
        val arr = obj.optJSONArray("tasks")
        if (arr == null || arr.length() !in 1..14) throw ValidationError("'tasks' must be a list of 1-14 items")
        val raw = (0 until arr.length()).map { i ->
            val t = arr.optJSONObject(i) ?: throw ValidationError("each task must be an object")
            val day = t.optInt("day", -1)
            if (day !in 1..7) throw ValidationError("'day' must be an integer 1-7")
            val text = t.optString("task", "").trim()
            if (text.isEmpty()) throw ValidationError("task text missing")
            val mins = t.optDouble("minutes", -1.0)
            if (mins.isNaN() || mins <= 0) throw ValidationError("'minutes' must be a positive number")
            var res = t.optString("resource", "")
            if (allowed.isNotEmpty() && res !in allowed) res = allowed[0] // never trust invented resources
            Triple(day, text, Pair(mins, res))
        }
        val scale = budgetMinutes / raw.sumOf { it.third.first }
        val tasks = raw.map { (day, text, mr) ->
            Task(day, text, max(5, (mr.first * scale / 5).roundToInt() * 5), mr.second)
        }.sortedBy { it.day }
        return ValidWeek(title, tasks, milestone)
    }
}
