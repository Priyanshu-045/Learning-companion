package com.example.companion.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.example.companion.core.Lang

@Composable
fun GoalIntakeScreen(
    currentLang: Lang,
    onContinue: (goal: String, domain: String) -> Unit,
    onBack: () -> Unit
) {
    var goalText by remember { mutableStateOf("") }
    var selectedDomain by remember { mutableStateOf("ml_engineer") }

    val domains = listOf(
        "ml_engineer" to "Machine Learning Engineer (Linear Algebra, Calculus, PyTorch, Deep Learning)",
        "data_analysis" to "Data Analyst (SQL, Python, Statistics, Pandas, Visualization)",
        "web_dev" to "Web Development (HTML/CSS, JavaScript, React, Backend APIs)"
    )

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp)
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.SpaceBetween
    ) {
        Column {
            Text(
                text = "What is your learning goal?",
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold
            )

            Spacer(modifier = Modifier.height(8.dp))

            Text(
                text = "Tell us what you want to achieve or master. We will create a step-by-step roadmap.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )

            Spacer(modifier = Modifier.height(20.dp))

            OutlinedTextField(
                value = goalText,
                onValueChange = { goalText = it },
                label = { Text("Describe your goal") },
                placeholder = {
                    Text(
                        when (currentLang) {
                            Lang.HI -> "उदा. मुझे मशीन लर्निंग इंजीनियर बनना है"
                            Lang.MR -> "उदा. मला मशीन लर्निंग शिकायचे आहे"
                            Lang.TA -> "எ.கா. நான் இயந்திர கற்றல் பொறியாளராக வேண்டும்"
                            Lang.TE -> "ఉదా. నేను మెషిన్ లెర్నింగ్ ఇంజనీర్ అవ్వాలనుకుంటున్నాను"
                            Lang.BN -> "যেমন: আমি মেশিন লার্নিং ইঞ্জিনিয়ার হতে চাই"
                            else -> "e.g., I want to master ML engineering and build neural networks"
                        }
                    )
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(130.dp),
                shape = RoundedCornerShape(12.dp)
            )

            Spacer(modifier = Modifier.height(28.dp))

            Text(
                text = "Target Domain Curriculum",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold
            )

            Spacer(modifier = Modifier.height(12.dp))

            domains.forEach { (domId, desc) ->
                val isSelected = selectedDomain == domId
                Surface(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 6.dp)
                        .clip(RoundedCornerShape(12.dp))
                        .clickable { selectedDomain = domId },
                    color = if (isSelected) MaterialTheme.colorScheme.primaryContainer
                    else MaterialTheme.colorScheme.surfaceVariant,
                    shape = RoundedCornerShape(12.dp)
                ) {
                    Row(
                        modifier = Modifier.padding(16.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        RadioButton(
                            selected = isSelected,
                            onClick = { selectedDomain = domId }
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Column {
                            Text(
                                text = domId.replace("_", " ").uppercase(),
                                style = MaterialTheme.typography.titleSmall,
                                fontWeight = FontWeight.Bold
                            )
                            Text(
                                text = desc,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                }
            }
        }

        Spacer(modifier = Modifier.height(24.dp))

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            OutlinedButton(
                onClick = onBack,
                modifier = Modifier
                    .weight(1f)
                    .height(54.dp),
                shape = RoundedCornerShape(12.dp)
            ) {
                Text("Back")
            }

            Button(
                onClick = {
                    val finalGoal = if (goalText.isNotBlank()) goalText else "Become an expert in $selectedDomain"
                    onContinue(finalGoal, selectedDomain)
                },
                modifier = Modifier
                    .weight(1.5f)
                    .height(54.dp),
                shape = RoundedCornerShape(12.dp)
            ) {
                Text("Continue", fontWeight = FontWeight.Bold)
            }
        }
    }
}

