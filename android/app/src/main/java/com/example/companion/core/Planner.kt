package com.example.companion.core

import kotlin.math.ceil
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/** Deterministic planning: skill graph -> gaps -> weekly schedule -> adaptation.
 * Complete Kotlin port matching Python prototype/companion/planner.py (M2.1 - M2.3).
 */
object Planner {
    private const val EPS = 0.01
    const val MAX_WEEKLY_HOURS = 100.0
    const val MAX_DAILY_MINUTES = 120

    fun validateHours(h: Double): Double {
        if (h.isNaN() || h.isInfinite() || h <= 0.0 || h > MAX_WEEKLY_HOURS) {
            throw IllegalArgumentException("weekly hours must be between 0 and $MAX_WEEKLY_HOURS, got $h")
        }
        return h
    }

    fun topoOrder(g: SkillGraph): List<String> {
        val nodes = g.nodes.associateBy { it.id }
        val order = mutableListOf<String>()
        val seen = mutableSetOf<String>()

        fun visit(id: String, stack: Set<String>) {
            if (id in seen) return
            require(id !in stack) { "cycle in skill graph at '$id'" }
            val node = nodes[id] ?: throw IllegalArgumentException("missing node '$id'")
            node.prereqs.forEach { visit(it, stack + id) }
            seen += id
            order += id
        }

        g.nodes.forEach { visit(it.id, emptySet()) }
        return order
    }

    fun findGaps(g: SkillGraph, known: Set<String>): List<String> =
        topoOrder(g).filter { it !in known }

    /** Pack queue items into weeks. Long items span weeks with multi-part progression coordinates. */
    fun pack(queue: List<PlanItem>, weeklyHoursInput: Double, startWeek: Int = 1): List<Week> {
        val weeklyHours = validateHours(weeklyHoursInput)
        val weeks = mutableListOf<Week>()
        var cur = mutableListOf<PlanItem>()
        var room = weeklyHours
        var week = startWeek

        for (item in queue) {
            var left = item.hours
            val totalHours = left
            val totalParts = if (totalHours <= room + EPS) 1 else {
                val rem = totalHours - room
                1 + ceil((rem - EPS) / weeklyHours).toInt()
            }
            var part = 1
            var cumStart = 0.0

            while (left > EPS) {
                val take = min(left, room)
                val cumEnd = ((cumStart + take) * 100).roundToInt() / 100.0
                val packedItem = PlanItem(
                    node = item.node,
                    hours = (take * 100).roundToInt() / 100.0,
                    revision = item.revision,
                    part = part,
                    totalParts = totalParts,
                    cumulativeHoursStart = (cumStart * 100).roundToInt() / 100.0,
                    cumulativeHoursEnd = (cumEnd * 100).roundToInt() / 100.0,
                    carriedForward = item.carriedForward,
                    reinforce = item.reinforce
                )
                cur.add(packedItem)
                left -= take
                room -= take
                cumStart = cumEnd
                part += 1

                if (room < EPS) {
                    weeks.add(Week(week = week, items = cur))
                    week++
                    cur = mutableListOf()
                    room = weeklyHours
                }
            }
        }
        if (cur.isNotEmpty()) {
            weeks.add(Week(week = week, items = cur))
        }
        return weeks
    }

    fun remainingQueue(weeks: List<Week>): List<PlanItem> {
        val q = mutableListOf<PlanItem>()
        for (w in weeks) {
            for (it in w.items) {
                val last = q.lastOrNull()
                if (last != null && last.node == it.node && last.revision == it.revision) {
                    val combinedHours = ((last.hours + it.hours) * 100).roundToInt() / 100.0
                    q[q.size - 1] = last.copy(hours = combinedHours)
                } else {
                    q.add(it)
                }
            }
        }
        return q
    }

    /** Deterministic adaptation rules matching M2.3 policy. */
    fun adaptQueue(
        weekItems: List<PlanItem>,
        remaining: List<PlanItem>,
        score: Double? = null,
        low: Double = 0.5,
        high: Double = 0.85,
        incompleteItems: List<PlanItem>? = null,
        graph: SkillGraph? = null,
        priorAdaptations: List<AdaptationRecord>? = null
    ): Pair<List<PlanItem>, String> {
        val rem = remaining.toMutableList()
        val carried = mutableListOf<PlanItem>()

        if (incompleteItems != null) {
            for (it in incompleteItems) {
                carried.add(PlanItem(node = it.node, hours = it.hours, revision = false, carriedForward = true))
            }
        }

        if (score == null) {
            val act = if (carried.isNotEmpty() || incompleteItems != null) "workload_updated" else "unchanged"
            return Pair(carried + rem, act)
        }

        // Count prior revisions to avoid infinite revision loops
        val priorRevCount = mutableMapOf<String, Int>()
        if (priorAdaptations != null) {
            for (a in priorAdaptations) {
                if (a.action in listOf("revision_added", "reinforced")) {
                    for (n in a.weakNodes) {
                        priorRevCount[n] = (priorRevCount[n] ?: 0) + 1
                    }
                } else if (a.action in listOf("accelerated", "mastery_progression")) {
                    for (n in a.masteredNodes) {
                        priorRevCount.remove(n)
                    }
                }
            }
        }

        if (score >= high) {
            // High score: accelerate first non-revision topic
            val idx = rem.indexOfFirst { !it.revision }
            return if (idx >= 0) {
                val orig = rem[idx]
                val acceleratedHours = max(1.0, (orig.hours * 0.75 * 10).roundToInt() / 10.0)
                rem[idx] = orig.copy(hours = acceleratedHours)
                Pair(carried + rem, "accelerated")
            } else {
                Pair(carried + rem, "mastery_progression")
            }
        } else if (score < low) {
            // Low score: add prerequisite & topic revisions
            val revs = mutableListOf<PlanItem>()
            val nodesMap = graph?.nodes?.associateBy { it.id } ?: emptyMap()

            for (it in weekItems) {
                val nid = it.node
                if ((priorRevCount[nid] ?: 0) >= 2) continue
                if (rem.any { r -> r.node == nid && r.revision }) continue

                // Add prerequisite review if available
                nodesMap[nid]?.prereqs?.forEach { p ->
                    if ((priorRevCount[p] ?: 0) == 0 && rem.none { r -> r.node == p }) {
                        revs.add(PlanItem(node = p, hours = 1.0, revision = true, reinforce = true))
                    }
                }

                val revHours = max(1.0, (it.hours * 0.5 * 10).roundToInt() / 10.0)
                revs.add(PlanItem(node = nid, hours = revHours, revision = true))
            }
            if (revs.isNotEmpty()) {
                return Pair(carried + revs + rem, "revision_added")
            }
        }

        return Pair(carried + rem, "unchanged")
    }

    /** Deterministically redistribute tasks so no day exceeds maxDaily minutes (M2.2C). */
    fun redistributeTasks(
        tasks: List<Task>,
        budgetMinutes: Int,
        maxDaily: Int = MAX_DAILY_MINUTES
    ): List<Task> {
        if (tasks.isEmpty()) return emptyList()

        // Check if redistribution is necessary
        var alreadyOk = true
        val dayLoads = mutableMapOf<Int, Int>()
        for (t in tasks) {
            if (t.day !in 1..7 || t.minutes > maxDaily) {
                alreadyOk = false
                break
            }
            dayLoads[t.day] = (dayLoads[t.day] ?: 0) + t.minutes
        }
        if (alreadyOk && dayLoads.values.all { it <= maxDaily }) {
            return tasks.sortedBy { it.day }
        }

        // Split tasks exceeding maxDaily into chunks
        val chunks = mutableListOf<Task>()
        for (t in tasks) {
            var mins = t.minutes
            while (mins > maxDaily) {
                var take = maxDaily
                if (mins - take in 1..4) {
                    take = mins - 5
                }
                chunks.add(t.copy(minutes = take))
                mins -= take
            }
            if (mins > 0) {
                chunks.add(t.copy(minutes = mins))
            }
        }

        val totalMinutes = chunks.sumOf { it.minutes }
        val maxCapacity = 7 * maxDaily
        if (totalMinutes > maxCapacity) {
            throw IllegalArgumentException("budget $totalMinutes min exceeds 7-day capacity $maxCapacity min")
        }

        // Assign chunks to days greedily
        val assigned = mutableListOf<Task>()
        var curDay = 1
        var curDayMins = 0

        for (idx in chunks.indices) {
            val chunk = chunks[idx]
            var cmins = chunk.minutes

            if (curDayMins + cmins <= maxDaily) {
                assigned.add(chunk.copy(day = curDay, minutes = cmins))
                curDayMins += cmins
            } else {
                val remBudget = chunks.subList(idx, chunks.size).sumOf { it.minutes }
                val remDaysCap = (7 - curDay) * maxDaily
                val room = maxDaily - curDayMins

                if (curDayMins > 0 && remBudget > remDaysCap && room >= 5) {
                    var take = room
                    if (cmins - take in 1..4) take = cmins - 5
                    if (take >= 5) {
                        assigned.add(chunk.copy(day = curDay, minutes = take))
                        cmins -= take
                    }
                    curDay++
                    curDayMins = 0
                } else if (curDayMins > 0) {
                    curDay++
                    curDayMins = 0
                }

                if (curDay > 7) {
                    throw IllegalArgumentException("redistribution requires > 7 days")
                }

                assigned.add(chunk.copy(day = curDay, minutes = cmins))
                curDayMins += cmins
            }
        }

        return assigned.sortedBy { it.day }
    }

    fun validateWorkload(
        tasks: List<Task>,
        budgetMinutes: Int,
        maxDaily: Int = MAX_DAILY_MINUTES,
        focusNodes: Set<String>? = null,
        nodeResources: Map<String, List<String>>? = null
    ) {
        val total = tasks.sumOf { it.minutes }
        if (kotlin.math.abs(total - budgetMinutes) > 1) {
            throw IllegalArgumentException("total minutes $total != budget $budgetMinutes")
        }
        val dayLoads = mutableMapOf<Int, Int>()
        for (t in tasks) {
            require(t.day in 1..7) { "invalid day ${t.day}" }
            require(t.minutes >= 5) { "task minutes must be >= 5, got ${t.minutes}" }
            require(t.minutes <= maxDaily) { "task duration ${t.minutes} exceeds cap $maxDaily" }
            dayLoads[t.day] = (dayLoads[t.day] ?: 0) + t.minutes
        }
        for ((d, load) in dayLoads) {
            require(load <= maxDaily) { "day $d load $load exceeds $maxDaily min" }
        }
        if (focusNodes != null) {
            val covered = tasks.mapNotNull { it.node }.toSet()
            val missing = focusNodes - covered
            require(missing.isEmpty()) { "missing focus topic(s): $missing" }
            for (t in tasks) {
                if (t.node != null) {
                    require(t.node in focusNodes) { "unexpected node '${t.node}'" }
                    if (nodeResources != null && t.node in nodeResources) {
                        val validRes = nodeResources[t.node] ?: emptyList()
                        require(t.resource in validRes) { "invalid resource '${t.resource}' for node '${t.node}'" }
                    }
                }
            }
        }
    }
}

