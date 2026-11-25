package com.example.companion.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.example.companion.core.QuizQuestion

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun QuizScreen(
    weekNumber: Int,
    questions: List<QuizQuestion>,
    onSubmitQuiz: (score: Double, answers: List<Int>) -> Unit,
    onBack: () -> Unit
) {
    val selectedAnswers = remember { mutableStateMapOf<Int, Int>() }
    var showResultsDialog by remember { mutableStateOf(false) }
    var calculatedScore by remember { mutableStateOf(0.0) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Week $weekNumber Mastery Quiz", fontWeight = FontWeight.Bold) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 20.dp),
            verticalArrangement = Arrangement.SpaceBetween
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "Knowledge Check (${questions.size} Questions)",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(vertical = 8.dp)
                )

                Text(
                    text = "Answer each question to evaluate your topic mastery and enable adaptive learning adjustments.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )

                Spacer(modifier = Modifier.height(14.dp))

                LazyColumn(
                    modifier = Modifier.fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(16.dp),
                    contentPadding = PaddingValues(bottom = 16.dp)
                ) {
                    itemsIndexed(questions) { qIdx, question ->
                        QuestionCard(
                            questionIndex = qIdx,
                            question = question,
                            selectedOption = selectedAnswers[qIdx],
                            onSelectOption = { optIdx ->
                                selectedAnswers[qIdx] = optIdx
                            }
                        )
                    }
                }
            }

            Button(
                onClick = {
                    var correct = 0
                    questions.forEachIndexed { idx, q ->
                        if (selectedAnswers[idx] == q.correctIndex) {
                            correct++
                        }
                    }
                    val total = if (questions.isNotEmpty()) questions.size else 1
                    calculatedScore = correct.toDouble() / total
                    showResultsDialog = true
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(54.dp)
                    .padding(bottom = 8.dp),
                shape = RoundedCornerShape(12.dp),
                enabled = questions.isNotEmpty() && selectedAnswers.size == questions.size
            ) {
                Text("Submit Quiz & Adapt Plan", fontWeight = FontWeight.Bold)
            }
        }
    }

    if (showResultsDialog) {
        val scorePercent = (calculatedScore * 100).toInt()
        val adaptationMessage = when {
            calculatedScore >= 0.85 -> "🎉 High Mastery ($scorePercent%)! Next module duration is accelerated by 25%."
            calculatedScore >= 0.50 -> "👍 Solid Progress ($scorePercent%)! Curriculum proceeds as scheduled."
            else -> "⚠️ Needs Reinforcement ($scorePercent%). Future roadmap will include targeted revision."
        }

        AlertDialog(
            onDismissRequest = { /* force action */ },
            title = { Text("Quiz Complete", fontWeight = FontWeight.Bold) },
            text = {
                Column {
                    Text(
                        text = "Score: $scorePercent%",
                        style = MaterialTheme.typography.headlineSmall,
                        fontWeight = FontWeight.Bold,
                        color = if (calculatedScore >= 0.7) Color(0xFF2E7D32) else Color(0xFFC62828)
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = adaptationMessage,
                        style = MaterialTheme.typography.bodyMedium
                    )
                }
            },
            confirmButton = {
                Button(
                    onClick = {
                        showResultsDialog = false
                        val answersList = (0 until questions.size).map { selectedAnswers[it] ?: 0 }
                        onSubmitQuiz(calculatedScore, answersList)
                    }
                ) {
                    Text("Apply Adaptation")
                }
            }
        )
    }
}

@Composable
fun QuestionCard(
    questionIndex: Int,
    question: QuizQuestion,
    selectedOption: Int?,
    onSelectOption: (Int) -> Unit
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(14.dp),
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 2.dp
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Surface(
                    shape = RoundedCornerShape(6.dp),
                    color = MaterialTheme.colorScheme.primaryContainer
                ) {
                    Text(
                        text = "Q${questionIndex + 1}",
                        style = MaterialTheme.typography.labelSmall,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp)
                    )
                }
                Spacer(modifier = Modifier.width(8.dp))
                Surface(
                    shape = RoundedCornerShape(6.dp),
                    color = MaterialTheme.colorScheme.outlineVariant
                ) {
                    Text(
                        text = question.node,
                        style = MaterialTheme.typography.labelSmall,
                        modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                    )
                }
            }

            Spacer(modifier = Modifier.height(10.dp))

            Text(
                text = question.question,
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.SemiBold
            )

            Spacer(modifier = Modifier.height(12.dp))

            question.options.forEachIndexed { optIdx, optionText ->
                val isSelected = selectedOption == optIdx
                Surface(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 4.dp)
                        .clip(RoundedCornerShape(8.dp))
                        .clickable { onSelectOption(optIdx) },
                    color = if (isSelected) MaterialTheme.colorScheme.primaryContainer
                    else MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
                    shape = RoundedCornerShape(8.dp)
                ) {
                    Row(
                        modifier = Modifier.padding(12.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        RadioButton(
                            selected = isSelected,
                            onClick = { onSelectOption(optIdx) }
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = optionText,
                            style = MaterialTheme.typography.bodyMedium
                        )
                    }
                }
            }
        }
    }
}

