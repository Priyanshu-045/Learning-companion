package com.example.companion

import org.json.JSONObject

data class SkillNode(val id: String, val name: String, val prereqs: List<String>, val hours: Double, val resources: List<String>)
data class SkillGraph(val domain: String, val title: String, val nodes: List<SkillNode>) {
    companion object {
        fun parse(json: String): SkillGraph {
            val o = JSONObject(json)
            val arr = o.getJSONArray("nodes")
            val nodes = (0 until arr.length()).map { i ->
                val n = arr.getJSONObject(i)
                fun strs(key: String) = n.getJSONArray(key).let { a -> (0 until a.length()).map { a.getString(it) } }
                SkillNode(n.getString("id"), n.getString("name"), strs("prereqs"), n.getDouble("hours"), strs("resources"))
            }
            return SkillGraph(o.getString("domain"), o.getString("title"), nodes)
        }
    }
}

data class PlanItem(val node: String, val hours: Double, val revision: Boolean = false)
data class Task(val day: Int, val task: String, val minutes: Int, val resource: String)
data class Week(
    val week: Int, val items: List<PlanItem>,
    val title: String? = null, val tasks: List<Task> = emptyList(), val milestone: String? = null,
    val score: Double? = null, val source: String = "skeleton"
)
data class ChatMessage(val role: String, val content: String) // role: system | user | assistant
