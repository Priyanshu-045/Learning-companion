package com.example.companion.core

import org.json.JSONArray
import org.json.JSONObject

data class SkillNode(
    val id: String,
    val name: String,
    val prereqs: List<String>,
    val hours: Double,
    val resources: List<String>
)

data class SkillGraph(
    val domain: String,
    val title: String,
    val nodes: List<SkillNode>
) {
    companion object {
        fun parse(json: String): SkillGraph {
            val o = JSONObject(json)
            val arr = o.getJSONArray("nodes")
            val nodes = (0 until arr.length()).map { i ->
                val n = arr.getJSONObject(i)
                fun strs(key: String): List<String> {
                    val a = n.optJSONArray(key) ?: return emptyList()
                    return (0 until a.length()).map { a.getString(it) }
                }
                SkillNode(
                    id = n.getString("id"),
                    name = n.getString("name"),
                    prereqs = strs("prereqs"),
                    hours = n.getDouble("hours"),
                    resources = strs("resources")
                )
            }
            return SkillGraph(o.getString("domain"), o.getString("title"), nodes)
        }
    }
}

data class PlanItem(
    val node: String,
    val hours: Double,
    val revision: Boolean = false,
    val part: Int = 1,
    val totalParts: Int = 1,
    val cumulativeHoursStart: Double = 0.0,
    val cumulativeHoursEnd: Double = hours,
    val carriedForward: Boolean = false,
    val reinforce: Boolean = false
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("node", node)
        put("hours", hours)
        put("revision", revision)
        put("part", part)
        put("total_parts", totalParts)
        put("cumulative_hours_start", cumulativeHoursStart)
        put("cumulative_hours_end", cumulativeHoursEnd)
        if (carriedForward) put("carried_forward", true)
        if (reinforce) put("reinforce", true)
    }

    companion object {
        fun fromJson(o: JSONObject): PlanItem = PlanItem(
            node = o.getString("node"),
            hours = o.getDouble("hours"),
            revision = o.optBoolean("revision", false),
            part = o.optInt("part", 1),
            totalParts = o.optInt("total_parts", 1),
            cumulativeHoursStart = o.optDouble("cumulative_hours_start", 0.0),
            cumulativeHoursEnd = o.optDouble("cumulative_hours_end", o.optDouble("hours", 0.0)),
            carriedForward = o.optBoolean("carried_forward", false),
            reinforce = o.optBoolean("reinforce", false)
        )
    }
}

data class Task(
    val day: Int,
    val task: String,
    val minutes: Int,
    val resource: String,
    val node: String? = null,
    var completed: Boolean = false
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("day", day)
        put("task", task)
        put("minutes", minutes)
        put("resource", resource)
        if (node != null) put("node", node)
        put("completed", completed)
    }

    companion object {
        fun fromJson(o: JSONObject): Task = Task(
            day = o.getInt("day"),
            task = o.optString("task", o.optString("description", "")),
            minutes = o.getInt("minutes"),
            resource = o.optString("resource", ""),
            node = if (o.has("node") && !o.isNull("node")) o.getString("node") else null,
            completed = o.optBoolean("completed", false)
        )
    }
}

data class Week(
    val week: Int,
    val items: List<PlanItem>,
    val title: String? = null,
    val tasks: List<Task> = emptyList(),
    val milestone: String? = null,
    var score: Double? = null,
    val source: String = "skeleton",
    var completed: Boolean = false
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("week", week)
        put("items", JSONArray(items.map { it.toJson() }))
        if (title != null) put("title", title)
        put("tasks", JSONArray(tasks.map { it.toJson() }))
        if (milestone != null) put("milestone", milestone)
        if (score != null) put("score", score)
        put("source", source)
        put("completed", completed)
    }

    companion object {
        fun fromJson(o: JSONObject): Week {
            val itemsArr = o.optJSONArray("items") ?: JSONArray()
            val items = (0 until itemsArr.length()).map { PlanItem.fromJson(itemsArr.getJSONObject(it)) }
            val tasksArr = o.optJSONArray("tasks") ?: JSONArray()
            val tasks = (0 until tasksArr.length()).map { Task.fromJson(tasksArr.getJSONObject(it)) }
            return Week(
                week = o.getInt("week"),
                items = items,
                title = if (o.has("title")) o.getString("title") else null,
                tasks = tasks,
                milestone = if (o.has("milestone")) o.getString("milestone") else null,
                score = if (o.has("score") && !o.isNull("score")) o.getDouble("score") else null,
                source = o.optString("source", "skeleton"),
                completed = o.optBoolean("completed", false)
            )
        }
    }
}

data class ChatMessage(val role: String, val content: String)

data class LearnerProfile(
    val goal: String,
    val language: String,
    val knownSkills: List<String> = emptyList(),
    val weeklyHours: Double = 10.0,
    val domain: String = "ml_engineer"
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("goal", goal)
        put("language", language)
        put("known_skills", JSONArray(knownSkills))
        put("weekly_hours", weeklyHours)
        put("domain", domain)
    }

    companion object {
        fun fromJson(o: JSONObject): LearnerProfile {
            val knownArr = o.optJSONArray("known_skills") ?: JSONArray()
            val known = (0 until knownArr.length()).map { knownArr.getString(it) }
            return LearnerProfile(
                goal = o.optString("goal", ""),
                language = o.optString("language", "en"),
                knownSkills = known,
                weeklyHours = o.optDouble("weekly_hours", 10.0),
                domain = o.optString("domain", "ml_engineer")
            )
        }
    }
}

data class AdaptationRecord(
    val week: Int,
    val action: String,
    val score: Double,
    val masteredNodes: List<String> = emptyList(),
    val weakNodes: List<String> = emptyList()
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("week", week)
        put("action", action)
        put("score", score)
        put("mastered_nodes", JSONArray(masteredNodes))
        put("weak_nodes", JSONArray(weakNodes))
    }

    companion object {
        fun fromJson(o: JSONObject): AdaptationRecord {
            val mArr = o.optJSONArray("mastered_nodes") ?: JSONArray()
            val mastered = (0 until mArr.length()).map { mArr.getString(it) }
            val wArr = o.optJSONArray("weak_nodes") ?: JSONArray()
            val weak = (0 until wArr.length()).map { wArr.getString(it) }
            return AdaptationRecord(
                week = o.getInt("week"),
                action = o.getString("action"),
                score = o.getDouble("score"),
                masteredNodes = mastered,
                weakNodes = weak
            )
        }
    }
}

data class LearnerState(
    val profile: LearnerProfile,
    val weeks: List<Week>,
    var currentWeekIndex: Int = 0,
    val weakSkills: MutableList<String> = mutableListOf(),
    val adaptations: MutableList<AdaptationRecord> = mutableListOf()
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("profile", profile.toJson())
        put("domain", profile.domain)
        put("language", profile.language)
        put("weekly_hours", profile.weeklyHours)
        put("weeks", JSONArray(weeks.map { it.toJson() }))
        put("current_week_index", currentWeekIndex)
        put("weak_skills", JSONArray(weakSkills))
        put("adaptations", JSONArray(adaptations.map { it.toJson() }))
    }

    companion object {
        fun fromJson(o: JSONObject): LearnerState {
            val profObj = o.optJSONObject("profile") ?: JSONObject().apply {
                put("domain", o.optString("domain", "ml_engineer"))
                put("language", o.optString("language", "en"))
                put("weekly_hours", o.optDouble("weekly_hours", 10.0))
            }
            val profile = LearnerProfile.fromJson(profObj)
            val weeksArr = o.optJSONArray("weeks") ?: JSONArray()
            val weeks = (0 until weeksArr.length()).map { Week.fromJson(weeksArr.getJSONObject(it)) }
            val weakArr = o.optJSONArray("weak_skills") ?: JSONArray()
            val weak = (0 until weakArr.length()).map { weakArr.getString(it) }.toMutableList()
            val adArr = o.optJSONArray("adaptations") ?: JSONArray()
            val adaptations = (0 until adArr.length()).map { AdaptationRecord.fromJson(adArr.getJSONObject(it)) }.toMutableList()
            return LearnerState(
                profile = profile,
                weeks = weeks,
                currentWeekIndex = o.optInt("current_week_index", 0),
                weakSkills = weak,
                adaptations = adaptations
            )
        }
    }
}

data class QuizQuestion(
    val node: String,
    val question: String,
    val options: List<String>,
    val correctIndex: Int,
    val explanation: String
)

data class QuizResult(
    val score: Double,
    val totalQuestions: Int,
    val correctAnswers: Int,
    val weakNodes: List<String>,
    val strongNodes: List<String>
)

