package com.example.companion

import kotlin.math.min
import kotlin.math.max
import kotlin.math.round

/** Deterministic planning. Port of prototype/companion/planner.py. */
object Planner {
    private const val EPS = 0.01

    fun topoOrder(g: SkillGraph): List<String> {
        val nodes = g.nodes.associateBy { it.id }
        val order = mutableListOf<String>()
        val seen = mutableSetOf<String>()
        fun visit(id: String, stack: Set<String>) {
            if (id in seen) return
            require(id !in stack) { "cycle in skill graph at '$id'" }
            nodes.getValue(id).prereqs.forEach { visit(it, stack + id) }
            seen += id; order += id
        }
        g.nodes.forEach { visit(it.id, emptySet()) }
        return order
    }

    fun findGaps(g: SkillGraph, known: Set<String>) = topoOrder(g).filter { it !in known }

    fun pack(queue: List<PlanItem>, weeklyHours: Double, startWeek: Int = 1): List<Week> {
        val weeks = mutableListOf<Week>()
        var cur = mutableListOf<PlanItem>()
        var room = weeklyHours
        var week = startWeek
        for (item in queue) {
            var left = item.hours
            while (left > EPS) {
                val take = min(left, room)
                cur += PlanItem(item.node, round(take * 100) / 100, item.revision)
                left -= take; room -= take
                if (room < EPS) { weeks += Week(week, cur); week++; cur = mutableListOf(); room = weeklyHours }
            }
        }
        if (cur.isNotEmpty()) weeks += Week(week, cur)
        return weeks
    }

    fun remainingQueue(weeks: List<Week>): List<PlanItem> {
        val q = mutableListOf<PlanItem>()
        for (w in weeks) for (it in w.items) {
            val last = q.lastOrNull()
            if (last != null && last.node == it.node && last.revision == it.revision)
                q[q.size - 1] = last.copy(hours = round((last.hours + it.hours) * 100) / 100)
            else q += it
        }
        return q
    }

    /** Returns (new queue, action) where action is revision_added | accelerated | unchanged. */
    fun adaptQueue(weekItems: List<PlanItem>, remaining: List<PlanItem>, score: Double,
                   low: Double = 0.5, high: Double = 0.85): Pair<List<PlanItem>, String> {
        if (score < low) {
            val revs = weekItems.filter { !it.revision }
                .map { PlanItem(it.node, max(1.0, round(it.hours * 0.5 * 10) / 10), true) }
            if (revs.isNotEmpty()) return Pair(revs + remaining, "revision_added")
        } else if (score >= high) {
            val idx = remaining.indexOfFirst { !it.revision }
            if (idx >= 0) {
                val m = remaining.toMutableList()
                m[idx] = m[idx].copy(hours = max(1.0, round(m[idx].hours * 0.75 * 10) / 10))
                return Pair(m, "accelerated")
            }
        }
        return Pair(remaining, "unchanged")
    }
}
