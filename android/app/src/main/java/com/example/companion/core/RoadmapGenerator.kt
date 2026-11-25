package com.example.companion.core

import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.ceil
import kotlin.math.max
import kotlin.math.roundToInt

data class FallbackTemplate(
    val title: String,
    val study: String,
    val revise: String,
    val milestone: String
)

/** Compact deterministic progress state from earlier weeks (avoids raw JSON node echo). */
data class PriorProgressSummary(
    val completedNodes: List<String> = emptyList(),
    val satisfiedPrereqs: List<String> = emptyList(),
    val remainingHours: Double = 0.0,
    val remainingNodesCount: Int = 0,
    val lastAdaptation: String? = null,
    val weakSkills: List<String> = emptyList(),
    val priorMilestone: String? = null
)

/**
 * LLM fills one week at a time; validation + retry + localized deterministic fallback.
 * Port of prototype/companion/roadmap.py.
 */
class RoadmapGenerator(
    private val engine: LlmEngine,
    private val systemTemplate: String
) {
    companion object {
        private const val TAG = "RoadmapGenerator"
        const val DEFAULT_WEEK_MAX_TOKENS = 520

        fun weekLabel(lang: Lang): String = when (lang) {
            Lang.HI -> "सप्ताह"
            Lang.MR -> "आठवडा"
            Lang.TA -> "வாரம்"
            Lang.TE -> "వారం"
            Lang.BN -> "সপ্তাহ"
            else -> "Week"
        }

        fun buildPriorSummary(
            graph: SkillGraph,
            completedNodes: Collection<String>,
            week: Week,
            remainingHours: Double,
            remainingNodesCount: Int,
            lastAdaptation: String? = null,
            weakSkills: List<String> = emptyList(),
            priorMilestone: String? = null
        ): PriorProgressSummary {
            val completedSet = completedNodes.toSet()
            val nodesMap = graph.nodes.associateBy { it.id }
            val relevantPrereqs = week.items
                .flatMap { nodesMap[it.node]?.prereqs ?: emptyList() }
                .distinct()
                .filter { it in completedSet }
            return PriorProgressSummary(
                completedNodes = completedNodes.toList(),
                satisfiedPrereqs = relevantPrereqs,
                remainingHours = remainingHours,
                remainingNodesCount = remainingNodesCount,
                lastAdaptation = lastAdaptation,
                weakSkills = weakSkills,
                priorMilestone = priorMilestone
            )
        }

        internal fun formatFocusLines(graph: SkillGraph, week: Week): String {
            val nodes = graph.nodes.associateBy { it.id }
            return week.items.joinToString("\n") { itm ->
                val node = nodes.getValue(itm.node)
                val mins = (itm.hours * 60).roundToInt()
                val mode = when {
                    itm.revision && itm.reinforce -> "reinforcement review"
                    itm.revision -> "revision practice"
                    itm.carriedForward -> "carried-forward study"
                    else -> "study"
                }
                val resChoices = node.resources.joinToString(" OR ") { "\"$it\"" }
                "* Topic: ${node.name} | required \"node\": \"${itm.node}\" | budget: $mins min ($mode, stage ${itm.part} of ${itm.totalParts})\n" +
                    "  Allowed \"resource\" values for \"${itm.node}\": $resChoices"
            }
        }

        internal fun buildCompactWeekPrompt(
            graph: SkillGraph,
            week: Week,
            lang: Lang,
            goal: String,
            weeklyHours: Double,
            progressSummary: PriorProgressSummary? = null
        ): String {
            val nodes = graph.nodes.associateBy { it.id }
            val budgetMinutes = (week.items.sumOf { it.hours } * 60).roundToInt()
            val focusLines = formatFocusLines(graph, week)
            val requiredIds = week.items.map { it.node }.distinct()
            val requiredIdsStr = requiredIds.joinToString(", ") { "\"$it\"" }
            val focusNames = week.items.map { nodes.getValue(it.node).name }.distinct().joinToString(" & ")
            val wLabel = weekLabel(lang)

            val sb = StringBuilder()
            sb.appendLine("Goal: ${goal.trim().ifEmpty { graph.title }}")
            sb.appendLine("Language: ${lang.displayName} (output text ONLY in ${lang.displayName})")
            sb.appendLine("Week ${week.week} | Budget: $budgetMinutes min (${weeklyHours}h/wk pace) | Max: 120 min/day across days 1-7")

            if (progressSummary != null) {
                val parts = mutableListOf<String>()
                if (progressSummary.completedNodes.isNotEmpty()) {
                    val recentNames = progressSummary.completedNodes.takeLast(2).map { nodes[it]?.name ?: it }
                    parts.add("done=${progressSummary.completedNodes.size} topic(s) (latest: ${recentNames.joinToString(", ")})")
                }
                if (progressSummary.satisfiedPrereqs.isNotEmpty()) {
                    val pNames = progressSummary.satisfiedPrereqs.map { nodes[it]?.name ?: it }
                    parts.add("prereqs_done=[${pNames.joinToString(", ")}]")
                }
                if (progressSummary.remainingHours > 0.0) {
                    val remH = (progressSummary.remainingHours * 10).roundToInt() / 10.0
                    parts.add("remaining=${remH}h (${progressSummary.remainingNodesCount} topic(s))")
                }
                if (!progressSummary.lastAdaptation.isNullOrBlank() && progressSummary.lastAdaptation != "unchanged") {
                    parts.add("adaptation=${progressSummary.lastAdaptation}")
                }
                if (progressSummary.weakSkills.isNotEmpty()) {
                    val wNames = progressSummary.weakSkills.map { nodes[it]?.name ?: it }
                    parts.add("weak_skills=[${wNames.joinToString(", ")}]")
                }
                if (parts.isNotEmpty()) {
                    sb.appendLine("Progress: ${parts.joinToString(" | ")}")
                }
                if (!progressSummary.priorMilestone.isNullOrBlank()) {
                    sb.appendLine("Do not repeat prior milestone: \"${progressSummary.priorMilestone}\"")
                }
            }

            sb.appendLine("ACTIVE FOCUS (schedule ALL; ONLY valid \"node\" IDs: [$requiredIdsStr]):")
            sb.appendLine(focusLines)
            val firstNode = requiredIds.first()
            val multiHint = if (requiredIds.size > 1) " Cover EVERY node in [$requiredIdsStr]." else ""
            sb.append("Each task object has ONLY 5 keys (day, node, task, minutes, resource), with a concrete learning activity in \"task\" and <=120 in \"minutes\". Output compact single-line JSON starting {\"title\":\"$wLabel ${week.week}: $focusNames\",\"milestone\":\"<concrete outcome>\",\"tasks\":[{\"day\":1,\"node\":\"$firstNode\",...}]}.$multiHint")
            return sb.toString()
        }

        internal fun buildConciseRetryMessages(
            graph: SkillGraph,
            week: Week,
            lang: Lang,
            goal: String,
            budgetMinutes: Int,
            validationError: String
        ): List<ChatMessage> {
            val nodes = graph.nodes.associateBy { it.id }
            val focusLines = formatFocusLines(graph, week)
            val requiredIds = week.items.map { it.node }.distinct()
            val requiredIdsStr = requiredIds.joinToString(", ") { "\"$it\"" }
            val focusNames = week.items.map { nodes.getValue(it.node).name }.distinct().joinToString(" & ")
            val wLabel = weekLabel(lang)

            val sys = ChatMessage(
                "system",
                "Output ONLY ONE valid compact single-line JSON object for Week ${week.week} in ${lang.displayName}. " +
                    "Schema: {\"title\":string,\"milestone\":string,\"tasks\":[{\"day\":1-7,\"node\":string,\"task\":string,\"minutes\":int,\"resource\":string}]}."
            )
            val usr = ChatMessage(
                "user",
                "Fix error: $validationError\n" +
                    "Goal: ${goal.trim().ifEmpty { graph.title }} | Budget: $budgetMinutes min | <=120 min/day\n" +
                    "Use ONLY the 5 keys (day, node, task, minutes, resource), concrete study activity strings in \"task\", and exact allowed values:\n" +
                    "$focusLines\n" +
                    "Required \"node\" IDs: [$requiredIdsStr]. Start title \"$wLabel ${week.week}: $focusNames\" with a concrete milestone."
            )
            return listOf(sys, usr)
        }

        private fun safeLogI(msg: String) {
            try { Log.i(TAG, msg) } catch (_: RuntimeException) {}
        }

        private fun safeLogW(msg: String) {
            try { Log.w(TAG, msg) } catch (_: RuntimeException) {}
        }

        val FALLBACK_TEMPLATES = mapOf(
            "en" to FallbackTemplate(
                title = "Week {week}: {names}",
                study = "Study {name}",
                revise = "Revise {name}",
                milestone = "Complete the scheduled topics and write a summary of key concepts"
            ),
            "hi" to FallbackTemplate(
                title = "सप्ताह {week}: {names}",
                study = "{name} का अध्ययन करें",
                revise = "{name} का पुनरीक्षण करें",
                milestone = "सूचीबद्ध विषयों को पूरा करें और प्रत्येक के लिए एक प्रश्न नोट करें"
            ),
            "mr" to FallbackTemplate(
                title = "आठवडा {week}: {names}",
                study = "{name} चा अभ्यास करा",
                revise = "{name} ची उजळणी करा",
                milestone = "दिलेले विषय पूर्ण करा आणि प्रत्येकासाठी एक प्रश्न नोंदवा"
            ),
            "ta" to FallbackTemplate(
                title = "வாரம் {week}: {names}",
                study = "{name} கற்க",
                revise = "{name} திருப்புதல் செய்க",
                milestone = "பட்டியலிடப்பட்ட தலைப்புகளை முடித்து ஒவ்வொன்றிற்கும் ஒரு குறிப்பை எழுதவும்"
            ),
            "te" to FallbackTemplate(
                title = "వారం {week}: {names}",
                study = "{name} అధ్యయనం చేయండి",
                revise = "{name} పునశ్చరణ చేయండి",
                milestone = "జాబితా చేయబడిన అంశాలను పూర్తి చేసి ప్రతిదానికి ఒక ప్రశ్న రాయండి"
            ),
            "bn" to FallbackTemplate(
                title = "সপ্তাহ {week}: {names}",
                study = "{name} অধ্যয়ন করুন",
                revise = "{name} পুনরাবৃত্তি করুন",
                milestone = "তালিকাভুক্ত বিষয়গুলি শেষ করুন এবং প্রতিটির জন্য একটি প্রশ্ন লিখুন"
            )
        )
    }

    fun fillWeek(
        graph: SkillGraph,
        week: Week,
        lang: Lang,
        goal: String,
        weeklyHours: Double,
        attempts: Int = 2,
        maxTokens: Int = DEFAULT_WEEK_MAX_TOKENS,
        priorContext: JSONObject? = null,
        progressSummary: PriorProgressSummary? = null,
        shouldAbortLlm: () -> Boolean = { false }
    ): Week {
        val nodes = graph.nodes.associateBy { it.id }
        val nodeResources = week.items.associate { it.node to nodes.getValue(it.node).resources }
        val allowed = week.items.flatMap { nodes.getValue(it.node).resources }.distinct()
        val budgetMinutes = (week.items.sumOf { it.hours } * 60).roundToInt()

        if (shouldAbortLlm()) {
            safeLogI("Week ${week.week} LLM skipped (user fallback requested); using deterministic template (source=fallback)")
            return templateWeek(week, nodes, lang)
        }

        val resolvedSummary = progressSummary ?: priorContext?.let { ctx ->
            val prevArr = ctx.optJSONArray("nodes")
            val prevIds = if (prevArr != null) {
                (0 until prevArr.length()).mapNotNull { i ->
                    prevArr.optJSONObject(i)?.optString("node", "")?.takeIf { it.isNotEmpty() }
                }
            } else emptyList()
            buildPriorSummary(
                graph = graph,
                completedNodes = prevIds,
                week = week,
                remainingHours = 0.0,
                remainingNodesCount = 0
            )
        }

        val initialSystem = ChatMessage("system", systemTemplate.replace("{LANGUAGE_NAME}", lang.displayName))
        val initialUser = ChatMessage("user", buildCompactWeekPrompt(graph, week, lang, goal, weeklyHours, resolvedSummary))
        val messages = mutableListOf(initialSystem, initialUser)

        var fallbackReason = "empty_response"
        for (attempt in 1..attempts) {
            if (shouldAbortLlm()) {
                fallbackReason = "aborted_by_user"
                break
            }
            var raw = ""
            try {
                raw = engine.chat(messages, maxTokens)
                if (raw.isBlank()) {
                    fallbackReason = "blank_response"
                    break
                }
                val v = WeekValidator.validate(
                    WeekValidator.extractJson(raw),
                    budgetMinutes,
                    allowed,
                    focusItems = week.items,
                    nodeResources = nodeResources
                )
                // Verify language script when generating non-English plans (allowing technical node/resource names).
                if (lang != Lang.EN) {
                    var checkText = (listOf(v.title, v.milestone) + v.tasks.map { it.task }).joinToString(" ")
                    val technicalTerms = (nodes.values.map { it.name } + allowed).sortedByDescending { it.length }
                    for (term in technicalTerms) {
                        checkText = checkText.replace(term, " ")
                    }
                    if (!LanguageDetector.scriptOk(checkText, lang)) {
                        throw ValidationError("all text values must be written in ${lang.displayName}")
                    }
                }
                safeLogI("Week ${week.week} generated successfully via on-device LLM (source=llm, attempt=$attempt)")
                return week.copy(
                    title = v.title,
                    tasks = v.tasks,
                    milestone = v.milestone,
                    source = "llm"
                )
            } catch (e: ValidationError) {
                fallbackReason = "validation_error: ${e.message}"
                safeLogW("Week ${week.week} attempt $attempt validation failed: ${e.message}")
                messages.clear()
                messages.addAll(
                    buildConciseRetryMessages(
                        graph = graph,
                        week = week,
                        lang = lang,
                        goal = goal,
                        budgetMinutes = budgetMinutes,
                        validationError = e.message ?: "invalid schema"
                    )
                )
            } catch (e: Exception) {
                fallbackReason = "engine_error: ${e.message}"
                safeLogW("Week ${week.week} inference failed (${e.javaClass.simpleName}): ${e.message}")
                break
            }
        }

        safeLogI("Week ${week.week} using deterministic fallback (source=fallback, reason=$fallbackReason)")
        return templateWeek(week, nodes, lang)
    }

    /** Deterministic localized fallback week for all 6 languages. Enforces daily load <= 120m. */
    fun templateWeek(week: Week, nodes: Map<String, SkillNode>, lang: Lang): Week {
        val tmpl = FALLBACK_TEMPLATES[lang.code] ?: FALLBACK_TEMPLATES.getValue("en")
        val tasks = mutableListOf<Task>()
        var k = 0
        val budget = (week.items.sumOf { it.hours } * 60).roundToInt()

        for (item in week.items) {
            val n = nodes.getValue(item.node)
            val totalMins = (item.hours * 60).roundToInt()
            val sessions = max(1, ceil(totalMins.toDouble() / Planner.MAX_DAILY_MINUTES).toInt())
            val perSession = max(5, ((totalMins.toDouble() / sessions / 5).roundToInt() * 5))

            for (s in 0 until sessions) {
                val mins = if (s == sessions - 1) {
                    max(5, totalMins - perSession * s)
                } else {
                    perSession
                }
                val templateStr = if (item.revision) tmpl.revise else tmpl.study
                val taskDesc = templateStr.replace("{name}", n.name)
                tasks.add(
                    Task(
                        day = (k % 5) + 1,
                        task = taskDesc,
                        minutes = mins,
                        resource = n.resources.firstOrNull() ?: "",
                        node = item.node
                    )
                )
                k++
            }
        }

        // Fix rounding drift
        val drift = tasks.sumOf { it.minutes } - budget
        if (drift != 0 && tasks.isNotEmpty()) {
            val last = tasks.last()
            tasks[tasks.size - 1] = last.copy(minutes = max(5, last.minutes - drift))
        }

        // Apply deterministic workload redistribution
        val redistributed = Planner.redistributeTasks(tasks, budget)
        val namesStr = week.items.joinToString(", ") { nodes.getValue(it.node).name }
        val weekTitle = tmpl.title.replace("{week}", week.week.toString()).replace("{names}", namesStr)

        return week.copy(
            title = weekTitle,
            tasks = redistributed,
            milestone = tmpl.milestone,
            source = "fallback"
        )
    }

    /** Deterministic quiz generation covering the week's topics. */
    fun generateQuiz(graph: SkillGraph, week: Week, lang: Lang): List<QuizQuestion> {
        val nodes = graph.nodes.associateBy { it.id }
        val questions = mutableListOf<QuizQuestion>()

        for (item in week.items) {
            val node = nodes[item.node] ?: continue
            val qText = when (lang) {
                Lang.HI -> "${node.name} के संबंध में इनमें से कौन सा कथन सही है?"
                Lang.MR -> "${node.name} च्या संदर्भात खालीलपैकी कोणते विधान योग्य आहे?"
                Lang.TA -> "${node.name} பற்றிய சரியான கூற்று எது?"
                Lang.TE -> "${node.name} కి సంబంధించి కిందివాటిలో సరైన ప్రకటన ఏది?"
                Lang.BN -> "${node.name} সম্পর্কে নিচের কোন বিবৃতি সঠিক?"
                else -> "Which of the following is correct regarding ${node.name}?"
            }
            val opt1 = "${node.name} foundational core principle"
            val opt2 = "Unrelated random procedure"
            val opt3 = "Deprecated legacy utility"
            val opt4 = "None of the above"

            questions.add(
                QuizQuestion(
                    node = node.id,
                    question = qText,
                    options = listOf(opt1, opt2, opt3, opt4),
                    correctIndex = 0,
                    explanation = "Standard mastery principle for ${node.name}."
                )
            )
        }

        return questions
    }
}

