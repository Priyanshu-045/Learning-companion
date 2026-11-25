package com.example.companion.data

import android.content.Context
import com.example.companion.core.*
import org.json.JSONObject
import java.io.File

/**
 * Phase 4: Local persistence for learner profile, language, weekly availability,
 * roadmap, task completion, quiz scores, weak skills, and adaptation history.
 */
class LearnerRepository(private val context: Context) {

    private val stateFile: File
        get() = File(context.filesDir, "companion_state.json")

    fun hasSavedState(): Boolean = stateFile.exists() && stateFile.length() > 0

    fun loadState(): LearnerState? {
        if (!hasSavedState()) return null
        return try {
            val jsonText = stateFile.readText(Charsets.UTF_8)
            LearnerState.fromJson(JSONObject(jsonText))
        } catch (e: Exception) {
            e.printStackTrace()
            null
        }
    }

    fun saveState(state: LearnerState) {
        try {
            val jsonStr = state.toJson().toString(2)
            stateFile.writeText(jsonStr, Charsets.UTF_8)
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }

    fun clearState() {
        if (stateFile.exists()) {
            stateFile.delete()
        }
    }

    fun updateTaskCompletion(weekIndex: Int, taskIndex: Int, completed: Boolean) {
        val state = loadState() ?: return
        if (weekIndex in state.weeks.indices) {
            val week = state.weeks[weekIndex]
            if (taskIndex in week.tasks.indices) {
                week.tasks[taskIndex].completed = completed
                week.completed = week.tasks.all { it.completed }
                saveState(state)
            }
        }
    }

    /**
     * Adapts roadmap based on quiz performance and incomplete tasks (M2.3).
     */
    fun recordQuizAndAdapt(
        weekIndex: Int,
        score: Double,
        questions: List<QuizQuestion>,
        graph: SkillGraph,
        engine: LlmEngine,
        systemPrompt: String,
        shouldAbortLlm: () -> Boolean = { false },
        onProgress: ((String) -> Unit)? = null
    ): Pair<LearnerState, String> {
        val state = loadState() ?: throw IllegalStateException("No active learner state")
        val week = state.weeks[weekIndex]
        week.score = score

        val mastered = mutableListOf<String>()
        val weak = mutableListOf<String>()

        if (score >= 0.85) {
            mastered.addAll(week.items.map { it.node }.distinct())
            state.weakSkills.removeAll(mastered.toSet())
        } else if (score < 0.50) {
            weak.addAll(week.items.map { it.node }.distinct())
            state.weakSkills.addAll(weak.filter { it !in state.weakSkills })
        }

        // Collect incomplete items from current week
        val incomplete = mutableListOf<PlanItem>()
        val incompleteTasks = week.tasks.filter { !it.completed }
        if (incompleteTasks.isNotEmpty()) {
            val nodeMinutes = mutableMapOf<String, Int>()
            incompleteTasks.forEach { t ->
                val nid = t.node ?: week.items.firstOrNull()?.node ?: ""
                nodeMinutes[nid] = (nodeMinutes[nid] ?: 0) + t.minutes
            }
            nodeMinutes.forEach { (nid, mins) ->
                if (nid.isNotEmpty()) {
                    incomplete.add(PlanItem(node = nid, hours = kotlin.math.round(mins / 6.0) / 10.0))
                }
            }
        }

        val remainingFutureWeeks = if (weekIndex + 1 < state.weeks.size) {
            state.weeks.subList(weekIndex + 1, state.weeks.size)
        } else {
            emptyList()
        }

        val remainingQ = Planner.remainingQueue(remainingFutureWeeks)
        val (newQueue, action) = Planner.adaptQueue(
            weekItems = week.items,
            remaining = remainingQ,
            score = score,
            incompleteItems = if (incomplete.isNotEmpty()) incomplete else null,
            graph = graph,
            priorAdaptations = state.adaptations
        )

        val newWeeks = Planner.pack(newQueue, state.profile.weeklyHours, startWeek = week.week + 1)
        val generator = RoadmapGenerator(engine, systemPrompt)
        val lang = Lang.fromCode(state.profile.language)

        val filledNewWeeks = mutableListOf<Week>()
        val completedSoFar = (state.profile.knownSkills +
            state.weeks.take(weekIndex).flatMap { w -> w.items.filter { it.part == it.totalParts }.map { it.node } } +
            if (score >= 0.85) week.items.map { it.node } else emptyList()
        ).distinct().toMutableList()
        var priorMilestone: String? = week.milestone

        for ((idx, w) in newWeeks.withIndex()) {
            onProgress?.invoke("Adapting Week ${w.week} (${idx + 1} of ${newWeeks.size})...")
            val remainingWeeks = newWeeks.subList(idx, newWeeks.size)
            val remainingHours = remainingWeeks.sumOf { remW -> remW.items.sumOf { it.hours } }
            val remainingNodeCount = remainingWeeks.flatMap { remW -> remW.items.map { it.node } }.distinct().size
            val summary = RoadmapGenerator.buildPriorSummary(
                graph = graph,
                completedNodes = completedSoFar,
                week = w,
                remainingHours = remainingHours,
                remainingNodesCount = remainingNodeCount,
                lastAdaptation = action,
                weakSkills = state.weakSkills,
                priorMilestone = priorMilestone
            )
            val filled = generator.fillWeek(
                graph = graph,
                week = w,
                lang = lang,
                goal = state.profile.goal,
                weeklyHours = state.profile.weeklyHours,
                progressSummary = summary,
                shouldAbortLlm = shouldAbortLlm
            )
            filledNewWeeks.add(filled)
            priorMilestone = filled.milestone
            w.items.filter { !it.revision && it.part >= it.totalParts }.forEach {
                if (it.node !in completedSoFar) completedSoFar.add(it.node)
            }
        }

        val updatedWeeksList = state.weeks.take(weekIndex + 1) + filledNewWeeks
        state.adaptations.add(
            AdaptationRecord(
                week = week.week,
                action = action,
                score = score,
                masteredNodes = mastered,
                weakNodes = weak
            )
        )

        val updatedState = state.copy(
            weeks = updatedWeeksList,
            currentWeekIndex = weekIndex
        )
        saveState(updatedState)
        return Pair(updatedState, action)
    }
}

