package com.example.companion.ui

import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.example.companion.core.*
import com.example.companion.data.LearnerRepository
import com.example.companion.data.ModelStorage
import com.example.companion.ui.screens.*
import com.example.companion.ui.theme.LearningCompanionTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.concurrent.atomic.AtomicBoolean

sealed class Screen {
    data object Welcome : Screen()
    data class GoalIntake(val lang: Lang) : Screen()
    data class SkillsAvailability(val goal: String, val domain: String, val lang: Lang) : Screen()
    data object Roadmap : Screen()
    data class WeekDetail(val weekIndex: Int) : Screen()
    data object TaskDashboard : Screen()
    data class Quiz(val weekIndex: Int) : Screen()
    data object Profile : Screen()
}

class MainActivity : ComponentActivity() {

    private lateinit var repository: LearnerRepository
    private lateinit var modelStorage: ModelStorage
    private lateinit var systemRoadmapPrompt: String
    private lateinit var engine: ExecuTorchEngine

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        repository = LearnerRepository(applicationContext)
        modelStorage = ModelStorage(applicationContext)
        engine = ExecuTorchEngine(
            modelPath = modelStorage.activeModelFile.absolutePath,
            tokenizerPath = modelStorage.productionTokenizerFile.absolutePath,
            temperature = 0.0f,
            storageVerifier = { modelStorage.resolveAndVerify().ready }
        )

        systemRoadmapPrompt = try {
            assets.open("prompts/system_roadmap.txt").bufferedReader().readText()
        } catch (e: Exception) {
            "You are an expert tutor. Provide weekly plans in {LANGUAGE_NAME}."
        }

        setContent {
            LearningCompanionTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    CompanionApp(
                        repository = repository,
                        engine = engine,
                        systemPrompt = systemRoadmapPrompt,
                        loadGraphFromAssets = { domain ->
                            val json = assets.open("skill_graphs/$domain.json").bufferedReader().readText()
                            SkillGraph.parse(json)
                        }
                    )
                }
            }
        }
    }

    override fun onDestroy() {
        if (isFinishing && ::engine.isInitialized) {
            engine.stop()
        }
        super.onDestroy()
    }
}

@Composable
fun CompanionApp(
    repository: LearnerRepository,
    engine: LlmEngine,
    systemPrompt: String,
    loadGraphFromAssets: (String) -> SkillGraph
) {
    var learnerState by remember { mutableStateOf(repository.loadState()) }
    var currentScreen by remember {
        mutableStateOf<Screen>(
            if (learnerState != null) Screen.Roadmap else Screen.Welcome
        )
    }
    var isGenerating by remember { mutableStateOf(false) }
    var generationStatus by remember { mutableStateOf("Preparing personalized curriculum...") }
    val abortLlm = remember { AtomicBoolean(false) }
    val coroutineScope = rememberCoroutineScope()

    if (isGenerating) {
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(16.dp),
                modifier = Modifier.padding(24.dp)
            ) {
                CircularProgressIndicator()
                Text(
                    text = generationStatus,
                    style = MaterialTheme.typography.bodyMedium,
                    textAlign = TextAlign.Center
                )
                OutlinedButton(
                    onClick = {
                        abortLlm.set(true)
                        (engine as? ExecuTorchEngine)?.stop()
                        generationStatus = "Switching remaining weeks to fast offline template..."
                    }
                ) {
                    Text("Use Instant Fallback")
                }
            }
        }
        return
    }

    when (val screen = currentScreen) {
        is Screen.Welcome -> {
            WelcomeScreen(
                onGetStarted = { selectedLang ->
                    currentScreen = Screen.GoalIntake(selectedLang)
                }
            )
        }

        is Screen.GoalIntake -> {
            GoalIntakeScreen(
                currentLang = screen.lang,
                onContinue = { goal, domain ->
                    currentScreen = Screen.SkillsAvailability(goal, domain, screen.lang)
                },
                onBack = { currentScreen = Screen.Welcome }
            )
        }

        is Screen.SkillsAvailability -> {
            val graph = remember(screen.domain) { loadGraphFromAssets(screen.domain) }
            SkillsAvailabilityScreen(
                graph = graph,
                onGenerateRoadmap = { knownSkills, weeklyHours ->
                    isGenerating = true
                    abortLlm.set(false)
                    (engine as? ExecuTorchEngine)?.resetCancellation()
                    generationStatus = "Checking on-device AI model & planning schedule..."
                    coroutineScope.launch(Dispatchers.IO) {
                        try {
                            val gaps = Planner.findGaps(graph, knownSkills.toSet())
                            val nodesMap = graph.nodes.associateBy { it.id }
                            val queue = gaps.map { id ->
                                PlanItem(node = id, hours = nodesMap.getValue(id).hours)
                            }
                            val packedWeeks = Planner.pack(queue, weeklyHours)
                            val etEngine = engine as? ExecuTorchEngine

                            if (etEngine != null && !abortLlm.get() && !etEngine.isLoaded) {
                                withContext(Dispatchers.Main) {
                                    generationStatus = "Verifying & loading Llama 3.2 1B (offline storage)..."
                                }
                                val loaded = etEngine.load()
                                if (!loaded) {
                                    Log.i("MainActivity", "Offline model not active (${etEngine.lastError}); using deterministic fallback.")
                                }
                            }

                            val generator = RoadmapGenerator(engine, systemPrompt)
                            val filledWeeks = mutableListOf<Week>()
                            val completedSoFar = knownSkills.toMutableList()
                            var priorMilestone: String? = null
                            for ((idx, w) in packedWeeks.withIndex()) {
                                val usingLlm = etEngine?.isLoaded == true && !abortLlm.get()
                                withContext(Dispatchers.Main) {
                                    generationStatus = if (usingLlm) {
                                        "Generating Week ${w.week} of ${packedWeeks.size} via on-device Llama 3.2 1B..."
                                    } else {
                                        "Generating Week ${w.week} of ${packedWeeks.size} (deterministic fallback)..."
                                    }
                                }
                                val remainingWeeks = packedWeeks.subList(idx, packedWeeks.size)
                                val remainingHours = remainingWeeks.sumOf { remW -> remW.items.sumOf { it.hours } }
                                val remainingNodeCount = remainingWeeks.flatMap { remW -> remW.items.map { it.node } }.distinct().size
                                val summary = RoadmapGenerator.buildPriorSummary(
                                    graph = graph,
                                    completedNodes = completedSoFar,
                                    week = w,
                                    remainingHours = remainingHours,
                                    remainingNodesCount = remainingNodeCount,
                                    priorMilestone = priorMilestone
                                )
                                val filled = generator.fillWeek(
                                    graph = graph,
                                    week = w,
                                    lang = screen.lang,
                                    goal = screen.goal,
                                    weeklyHours = weeklyHours,
                                    progressSummary = summary,
                                    shouldAbortLlm = { abortLlm.get() }
                                )
                                filledWeeks.add(filled)
                                priorMilestone = filled.milestone
                                w.items.filter { !it.revision && it.part >= it.totalParts }.forEach {
                                    if (it.node !in completedSoFar) completedSoFar.add(it.node)
                                }
                            }

                            val llmCount = filledWeeks.count { it.source == "llm" }
                            val fbCount = filledWeeks.size - llmCount
                            Log.i("MainActivity", "Roadmap completed: ${filledWeeks.size} weeks (llm=$llmCount, fallback=$fbCount)")

                            val profile = LearnerProfile(
                                goal = screen.goal,
                                language = screen.lang.code,
                                knownSkills = knownSkills,
                                weeklyHours = weeklyHours,
                                domain = screen.domain
                            )
                            val newState = LearnerState(
                                profile = profile,
                                weeks = filledWeeks,
                                currentWeekIndex = 0
                            )
                            repository.saveState(newState)
                            withContext(Dispatchers.Main) {
                                learnerState = newState
                                currentScreen = Screen.Roadmap
                            }
                        } catch (e: Exception) {
                            Log.e("MainActivity", "Roadmap generation error: ${e.message}", e)
                        } finally {
                            withContext(Dispatchers.Main) {
                                isGenerating = false
                            }
                        }
                    }
                },
                onBack = { currentScreen = Screen.GoalIntake(screen.lang) }
            )
        }

        is Screen.Roadmap -> {
            val state = learnerState
            if (state == null) {
                currentScreen = Screen.Welcome
            } else {
                RoadmapScreen(
                    state = state,
                    onSelectWeek = { weekIdx ->
                        currentScreen = Screen.WeekDetail(weekIdx)
                    },
                    onOpenDashboard = { currentScreen = Screen.TaskDashboard },
                    onOpenProfile = { currentScreen = Screen.Profile }
                )
            }
        }

        is Screen.WeekDetail -> {
            val state = learnerState
            if (state == null || screen.weekIndex !in state.weeks.indices) {
                currentScreen = Screen.Roadmap
            } else {
                val week = state.weeks[screen.weekIndex]
                WeekDetailScreen(
                    weekIndex = screen.weekIndex,
                    week = week,
                    onTaskToggle = { taskIdx, completed ->
                        repository.updateTaskCompletion(screen.weekIndex, taskIdx, completed)
                        learnerState = repository.loadState()
                    },
                    onTakeQuiz = {
                        currentScreen = Screen.Quiz(screen.weekIndex)
                    },
                    onBack = { currentScreen = Screen.Roadmap }
                )
            }
        }

        is Screen.TaskDashboard -> {
            val state = learnerState
            if (state == null) {
                currentScreen = Screen.Welcome
            } else {
                TaskDashboardScreen(
                    state = state,
                    onBack = { currentScreen = Screen.Roadmap }
                )
            }
        }

        is Screen.Quiz -> {
            val state = learnerState
            if (state == null || screen.weekIndex !in state.weeks.indices) {
                currentScreen = Screen.Roadmap
            } else {
                val week = state.weeks[screen.weekIndex]
                val graph = remember(state.profile.domain) { loadGraphFromAssets(state.profile.domain) }
                val generator = remember { RoadmapGenerator(engine, systemPrompt) }
                val questions = remember(screen.weekIndex) {
                    generator.generateQuiz(graph, week, Lang.fromCode(state.profile.language))
                }

                QuizScreen(
                    weekNumber = week.week,
                    questions = questions,
                    onSubmitQuiz = { score, answers ->
                        isGenerating = true
                        abortLlm.set(false)
                        (engine as? ExecuTorchEngine)?.resetCancellation()
                        generationStatus = "Adapting future roadmap based on quiz results..."
                        coroutineScope.launch(Dispatchers.IO) {
                            try {
                                val (adaptedState, action) = repository.recordQuizAndAdapt(
                                    weekIndex = screen.weekIndex,
                                    score = score,
                                    questions = questions,
                                    graph = graph,
                                    engine = engine,
                                    systemPrompt = systemPrompt,
                                    shouldAbortLlm = { abortLlm.get() },
                                    onProgress = { msg ->
                                        coroutineScope.launch(Dispatchers.Main) {
                                            generationStatus = msg
                                        }
                                    }
                                )
                                Log.i("MainActivity", "Quiz adaptation complete: action=$action")
                                withContext(Dispatchers.Main) {
                                    learnerState = adaptedState
                                    currentScreen = Screen.Roadmap
                                }
                            } catch (e: Exception) {
                                Log.e("MainActivity", "Quiz adaptation error: ${e.message}", e)
                            } finally {
                                withContext(Dispatchers.Main) {
                                    isGenerating = false
                                }
                            }
                        }
                    },
                    onBack = { currentScreen = Screen.WeekDetail(screen.weekIndex) }
                )
            }
        }

        is Screen.Profile -> {
            val state = learnerState
            if (state == null) {
                currentScreen = Screen.Welcome
            } else {
                ProfileScreen(
                    state = state,
                    onLanguageChange = { newLang ->
                        val updatedState = state.copy(
                            profile = state.profile.copy(language = newLang.code)
                        )
                        repository.saveState(updatedState)
                        learnerState = updatedState
                    },
                    onResetCurriculum = {
                        repository.clearState()
                        learnerState = null
                        currentScreen = Screen.Welcome
                    },
                    onBack = { currentScreen = Screen.Roadmap }
                )
            }
        }
    }
}

