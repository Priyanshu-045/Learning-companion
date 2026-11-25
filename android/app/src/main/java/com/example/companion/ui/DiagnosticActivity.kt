package com.example.companion.ui

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Bundle
import android.os.Debug
import android.os.Process
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.pytorch.executorch.extension.llm.LlmCallback
import org.pytorch.executorch.extension.llm.LlmModule
import com.example.companion.core.CompatibleLlmCallback
import com.example.companion.core.ExecuTorchEngine
import java.io.File

class DiagnosticActivity : ComponentActivity() {

    companion object {
        private const val TAG = "ExecuTorchDiagnostic"
        const val DEFAULT_MODEL_PATH = "/data/local/tmp/llama/Llama-3.2-1B-Instruct-SpinQuant_INT4_EO8.pte"
        const val DEFAULT_TOKENIZER_PATH = "/data/local/tmp/llama/tokenizer.model"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        // Configure Qualcomm FastRPC / Hexagon cDSP library search path
        try {
            val nativeDir = applicationInfo.nativeLibraryDir
            val adspPath = "$nativeDir;/data/local/tmp/llama;/data/data/$packageName/files;/vendor/dsp/cdsp;/vendor/lib/rfsa/dsp/cdsp;/system/lib/rfsa/adsp;/system/vendor/lib/rfsa/adsp;/dsp"
            android.system.Os.setenv("ADSP_LIBRARY_PATH", adspPath, true)
            Log.i(TAG, "Configured ADSP_LIBRARY_PATH: $adspPath")
        } catch (e: Throwable) {
            Log.w(TAG, "Failed to configure ADSP_LIBRARY_PATH: ${e.message}", e)
        }

        val promptFile = intent.getStringExtra("prompt_file")
        val initialPrompt = if (!promptFile.isNullOrEmpty() && File(promptFile).exists()) {
            File(promptFile).readText()
        } else {
            intent.getStringExtra("prompt") ?: "What is machine learning? Explain in two sentences."
        }
        val autoRun = intent.getBooleanExtra("auto_run", false)
        val maxTokensArg = intent.getIntExtra("max_tokens", 350)
        val qnnModel = File("/data/local/tmp/llama/Llama-3.2-1B-Instruct-QNN_HTP.pte")
        val defaultModel = if (qnnModel.exists()) qnnModel.absolutePath else DEFAULT_MODEL_PATH
        val initialModelPath = intent.getStringExtra("model_path") ?: defaultModel
        val initialTokenizerPath = intent.getStringExtra("tokenizer_path") ?: DEFAULT_TOKENIZER_PATH

        setContent {
            MaterialTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    DiagnosticScreen(initialPrompt, autoRun, maxTokensArg, initialModelPath, initialTokenizerPath)
                }
            }
        }
    }

    private fun getBatteryTemp(): Double {
        return try {
            val intent = registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            val temp = intent?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, 0) ?: 0
            temp / 10.0
        } catch (_: Exception) {
            0.0
        }
    }

    data class MemoryMetrics(val pssMb: Double, val nativePssMb: Double, val rssMb: Double, val hwmMb: Double)

    private fun captureMemoryMetrics(label: String): MemoryMetrics {
        return try {
            val am = getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
            val memInfo = am.getProcessMemoryInfo(intArrayOf(Process.myPid()))[0]
            val pssMb = memInfo.totalPss / 1024.0
            val nativePssMb = memInfo.nativePss / 1024.0
            val (rssMb, hwmMb) = try {
                val status = File("/proc/self/status").readText()
                val rssLine = status.lines().firstOrNull { it.startsWith("VmRSS:") }
                val hwmLine = status.lines().firstOrNull { it.startsWith("VmHWM:") }
                val rssKb = rssLine?.replace(Regex("[^0-9]"), "")?.toDoubleOrNull() ?: 0.0
                val hwmKb = hwmLine?.replace(Regex("[^0-9]"), "")?.toDoubleOrNull() ?: 0.0
                (rssKb / 1024.0) to (hwmKb / 1024.0)
            } catch (e: Exception) {
                0.0 to 0.0
            }
            val summary = "[$label] PSS: %.1f MB (Native PSS: %.1f MB) | RSS: %.1f MB | HWM: %.1f MB".format(pssMb, nativePssMb, rssMb, hwmMb)
            Log.i(TAG, summary)
            MemoryMetrics(pssMb, nativePssMb, rssMb, hwmMb)
        } catch (e: Exception) {
            Log.e(TAG, "Memory capture error: ${e.message}")
            MemoryMetrics(0.0, 0.0, 0.0, 0.0)
        }
    }

    @Composable
    fun DiagnosticScreen(
        initialPrompt: String,
        autoRun: Boolean,
        maxTokensArg: Int,
        initialModelPath: String = DEFAULT_MODEL_PATH,
        initialTokenizerPath: String = DEFAULT_TOKENIZER_PATH
    ) {
        val coroutineScope = rememberCoroutineScope()
        val scrollState = rememberScrollState()

        var modelPath by remember { mutableStateOf(initialModelPath) }
        var tokenizerPath by remember { mutableStateOf(initialTokenizerPath) }
        var promptText by remember { mutableStateOf(initialPrompt) }

        var isModelLoaded by remember { mutableStateOf(false) }
        var isLoading by remember { mutableStateOf(false) }
        var isGenerating by remember { mutableStateOf(false) }
        var statusMessage by remember { mutableStateOf("Ready. Press 'Load Model' to begin.") }

        var streamingOutput by remember { mutableStateOf("") }
        var ttftMs by remember { mutableLongStateOf(0L) }
        var totalGenTimeMs by remember { mutableLongStateOf(0L) }
        var tokenCount by remember { mutableIntStateOf(0) }
        var decodeTokPerSec by remember { mutableDoubleStateOf(0.0) }
        var reportedStats by remember { mutableDoubleStateOf(0.0) }
        var memorySummary by remember { mutableStateOf("") }

        var llmModuleInstance by remember { mutableStateOf<LlmModule?>(null) }

        fun runInferenceAction(module: LlmModule, targetPrompt: String, maxTokens: Int) {
            if (isGenerating) return
            isGenerating = true
            streamingOutput = ""
            tokenCount = 0
            ttftMs = 0L
            decodeTokPerSec = 0.0
            reportedStats = 0.0

            coroutineScope.launch(Dispatchers.IO) {
                try {
                    val memBefore = captureMemoryMetrics("Before Inference")
                    val formattedPrompt = if (targetPrompt.startsWith("<|begin_of_text|>")) {
                        targetPrompt
                    } else {
                        "<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n$targetPrompt<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
                    }
                    val startTs = System.currentTimeMillis()
                    var firstTokenTs = 0L
                    var count = 0
                    val outputAccumulator = StringBuilder()

                    val callback = object : CompatibleLlmCallback() {
                        override fun onResult(result: String) {
                            val now = System.currentTimeMillis()
                            if (firstTokenTs == 0L && result.isNotEmpty()) {
                                firstTokenTs = now
                                ttftMs = firstTokenTs - startTs
                                Log.i(TAG, "First token received: TTFT = ${ttftMs}ms")
                            }
                            count++
                            outputAccumulator.append(result)
                            coroutineScope.launch(Dispatchers.Main) {
                                streamingOutput += result
                                tokenCount = count
                            }
                        }

                        override fun onSpeedReported(speed: Double) {
                            reportedStats = speed
                            Log.i(TAG, "Reported stats from ExecuTorch: $speed tok/s")
                        }
                    }

                    val boundedSeqLen = ExecuTorchEngine.computeBoundedSeqLen(formattedPrompt, maxTokens)
                    Log.i(TAG, "Starting generation: promptChars=${formattedPrompt.length}, boundedSeqLen=$boundedSeqLen, maxTokens=$maxTokens")
                    val genRes = module.generate(formattedPrompt, boundedSeqLen, callback, false)
                    val endTs = System.currentTimeMillis()
                    totalGenTimeMs = endTs - startTs

                    val decodeDurationSec = if (firstTokenTs > 0L) (endTs - firstTokenTs) / 1000.0 else 0.0
                    val calcTokPerSec = if (decodeDurationSec > 0.0 && count > 1) (count - 1) / decodeDurationSec else 0.0

                    val memAfter = captureMemoryMetrics("After Inference")
                    val tempAfter = getBatteryTemp()

                    val effectiveSpeed = if (reportedStats > 0.0) reportedStats else calcTokPerSec
                    Log.i(TAG, "BENCHMARK_RESULT: pkg=$packageName, ttft_ms=$ttftMs, decode_tok_per_sec=%.2f, total_time_ms=$totalGenTimeMs, token_count=$count, pss_mb=%.1f, rss_mb=%.1f, hwm_mb=%.1f, temp_c=%.1f".format(
                        effectiveSpeed, memAfter.pssMb, memAfter.rssMb, memAfter.hwmMb, tempAfter
                    ))
                    Log.i(TAG, "BENCHMARK_OUTPUT_BEGIN\n$outputAccumulator\nBENCHMARK_OUTPUT_END")

                    withContext(Dispatchers.Main) {
                        isGenerating = false
                        decodeTokPerSec = effectiveSpeed
                        memorySummary = "PSS: %.1f MB | RSS: %.1f MB | HWM: %.1f MB".format(memAfter.pssMb, memAfter.rssMb, memAfter.hwmMb)
                        statusMessage = "Inference completed: $count tokens in ${totalGenTimeMs}ms (TTFT: ${ttftMs}ms, %.1f tok/s)".format(effectiveSpeed)
                        Log.i(TAG, statusMessage)
                    }
                } catch (t: Throwable) {
                    Log.e(TAG, "Generation error: ${t.message}", t)
                    withContext(Dispatchers.Main) {
                        isGenerating = false
                        statusMessage = "GENERATION ERROR: ${t.message}"
                    }
                }
            }
        }

        fun loadModelAction(onLoaded: ((LlmModule) -> Unit)? = null) {
            if (isLoading || isGenerating) return
            isLoading = true
            statusMessage = "Loading ExecuTorch model into memory..."
            coroutineScope.launch(Dispatchers.IO) {
                try {
                    val modelFile = File(modelPath)
                    val tokenizerFile = File(tokenizerPath)
                    if (!modelFile.exists()) {
                        throw IllegalArgumentException("Model file does not exist: $modelPath")
                    }
                    if (!tokenizerFile.exists()) {
                        throw IllegalArgumentException("Tokenizer file does not exist: $tokenizerPath")
                    }

                    Log.i(TAG, "Initializing LlmModule: model=${modelFile.length()} bytes, tokenizer=${tokenizerFile.length()} bytes")
                    val t0 = System.currentTimeMillis()
                    
                    // Diagnostic probe: inspect methods via core ExecuTorch Module (safely via reflection for cross-flavor compat)
                    try {
                        val moduleClass = Class.forName("org.pytorch.executorch.Module")
                        val loadMethod = moduleClass.getMethod("load", String::class.java)
                        val coreModule = loadMethod.invoke(null, modelPath)
                        val getMethods = try { moduleClass.getMethod("getMethods") } catch (_: Throwable) { null }
                        val loadMethodFn = moduleClass.getMethod("loadMethod", String::class.java)
                        val methodNames = (getMethods?.invoke(coreModule) as? Array<*>)?.filterIsInstance<String>() ?: emptyList()
                        Log.i(TAG, "ExecuTorch core Module loaded! Discovered methods: $methodNames")
                        if (methodNames.contains("prefill_forward")) {
                            Log.i(TAG, "Testing QNN HTP dispatch on 'prefill_forward'...")
                            val retPrefill = loadMethodFn.invoke(coreModule, "prefill_forward")
                            Log.i(TAG, "loadMethod('prefill_forward') result: $retPrefill")
                        }
                        if (methodNames.contains("kv_forward")) {
                            Log.i(TAG, "Testing QNN HTP dispatch on 'kv_forward'...")
                            val retKv = loadMethodFn.invoke(coreModule, "kv_forward")
                            Log.i(TAG, "loadMethod('kv_forward') result: $retKv")
                        }
                    } catch (e: Throwable) {
                        Log.w(TAG, "Core Module inspection threw: ${e.message}", e)
                    }

                    val module = LlmModule(modelPath, tokenizerPath, 0.0f)
                    val loadRes = module.load()
                    val loadDuration = System.currentTimeMillis() - t0

                    val mem = captureMemoryMetrics("After Load")

                    withContext(Dispatchers.Main) {
                        llmModuleInstance = module
                        isModelLoaded = true
                        isLoading = false
                        memorySummary = "PSS: %.1f MB | RSS: %.1f MB | HWM: %.1f MB".format(mem.pssMb, mem.rssMb, mem.hwmMb)
                        statusMessage = "Model loaded successfully in ${loadDuration}ms (ret code: $loadRes)"
                        Log.i(TAG, statusMessage)
                    }
                    onLoaded?.invoke(module)
                } catch (t: Throwable) {
                    Log.e(TAG, "Model loading failed: ${t.message}", t)
                    withContext(Dispatchers.Main) {
                        isLoading = false
                        isModelLoaded = false
                        statusMessage = "LOAD FAILED: ${t.javaClass.simpleName}: ${t.message}"
                    }
                }
            }
        }

        LaunchedEffect(autoRun) {
            if (autoRun) {
                loadModelAction { module ->
                    runInferenceAction(module, initialPrompt, maxTokensArg)
                }
            }
        }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(16.dp)
                .verticalScroll(scrollState),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Text(
                text = "⚡ ExecuTorch On-Device Diagnostic",
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold
            )
            Text(
                text = "Physical Device: Realme GT 6T (Snapdragon 7+ Gen 3) [$packageName]",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.primary
            )

            // Status Card
            Card(
                colors = CardDefaults.cardColors(
                    containerColor = if (isModelLoaded) Color(0xFFE8F5E9) else Color(0xFFFFF3E0)
                ),
                shape = RoundedCornerShape(8.dp)
            ) {
                Column(modifier = Modifier.padding(12.dp)) {
                    Text(text = "Status: $statusMessage", fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                    if (memorySummary.isNotEmpty()) {
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(text = memorySummary, fontFamily = FontFamily.Monospace, fontSize = 11.sp)
                    }
                }
            }

            // Model & Tokenizer inputs
            OutlinedTextField(
                value = modelPath,
                onValueChange = { modelPath = it },
                label = { Text("Model Path (.pte)") },
                modifier = Modifier.fillMaxWidth(),
                textStyle = LocalTextStyle.current.copy(fontSize = 11.sp, fontFamily = FontFamily.Monospace)
            )

            OutlinedTextField(
                value = tokenizerPath,
                onValueChange = { tokenizerPath = it },
                label = { Text("Tokenizer Path (.model)") },
                modifier = Modifier.fillMaxWidth(),
                textStyle = LocalTextStyle.current.copy(fontSize = 11.sp, fontFamily = FontFamily.Monospace)
            )

            // Load button
            Button(
                onClick = { loadModelAction() },
                enabled = !isLoading && !isGenerating,
                modifier = Modifier.fillMaxWidth()
            ) {
                if (isLoading) {
                    CircularProgressIndicator(modifier = Modifier.size(18.dp), color = Color.White, strokeWidth = 2.dp)
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("Loading Model...")
                } else {
                    Text(if (isModelLoaded) "Reload Model" else "Load Model")
                }
            }

            // Prompt input
            OutlinedTextField(
                value = promptText,
                onValueChange = { promptText = it },
                label = { Text("Inference Prompt") },
                modifier = Modifier.fillMaxWidth(),
                minLines = 2
            )

            // Action Buttons
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                Button(
                    onClick = {
                        val module = llmModuleInstance ?: return@Button
                        runInferenceAction(module, promptText, maxTokensArg)
                    },
                    enabled = isModelLoaded && !isGenerating,
                    modifier = Modifier.weight(1f)
                ) {
                    if (isGenerating) {
                        CircularProgressIndicator(modifier = Modifier.size(16.dp), color = Color.White, strokeWidth = 2.dp)
                        Spacer(modifier = Modifier.width(6.dp))
                        Text("Generating...")
                    } else {
                        Text("Run Inference")
                    }
                }

                OutlinedButton(
                    onClick = {
                        llmModuleInstance?.stop()
                        statusMessage = "Stopped by user"
                    },
                    enabled = isGenerating
                ) {
                    Text("Stop")
                }
            }

            // Benchmark Metrics Card
            if (tokenCount > 0 || isGenerating) {
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
                ) {
                    Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text("📊 Live Inference Metrics", fontWeight = FontWeight.Bold, fontSize = 13.sp)
                        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text("TTFT: ${ttftMs}ms", fontSize = 12.sp, fontFamily = FontFamily.Monospace)
                            Text("Decode Speed: %.1f tok/s".format(decodeTokPerSec), fontSize = 12.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace, color = MaterialTheme.colorScheme.primary)
                        }
                        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text("Tokens: $tokenCount", fontSize = 12.sp, fontFamily = FontFamily.Monospace)
                            Text("Total Time: ${totalGenTimeMs}ms", fontSize = 12.sp, fontFamily = FontFamily.Monospace)
                        }
                    }
                }
            }

            // Output Box
            Text("Generated Output:", fontWeight = FontWeight.Bold, fontSize = 13.sp)
            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .defaultMinSize(minHeight = 120.dp),
                shape = RoundedCornerShape(8.dp),
                color = MaterialTheme.colorScheme.surface,
                tonalElevation = 2.dp
            ) {
                Text(
                    text = if (streamingOutput.isEmpty()) if (isGenerating) "Generating tokens..." else "(Awaiting inference)" else streamingOutput,
                    modifier = Modifier.padding(12.dp),
                    fontSize = 13.sp,
                    fontFamily = FontFamily.Default
                )
            }
        }
    }
}


