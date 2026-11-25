package com.example.companion.core

import android.util.Log
import org.pytorch.executorch.extension.llm.LlmCallback
import org.pytorch.executorch.extension.llm.LlmModule
import java.io.File
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit

data class InferenceMetrics(
    val modelLoadTimeMs: Long,
    val ttftMs: Long,
    val totalTimeMs: Long,
    val reportedTokPerSec: Double,
    val generatedCallbacks: Int,
    val promptChars: Int,
    val outputChars: Int
)

/**
 * ExecuTorch 0.6.0 on-device LLM Engine implementing [LlmEngine].
 * Reuses a single loaded [LlmModule] instance across generation calls, keeps heavy
 * execution off the Android main thread, strips prompt echo and Llama 3 special tokens,
 * enforces timeout/cancellation, and exposes inference diagnostics.
 */
class ExecuTorchEngine(
    val modelPath: String,
    val tokenizerPath: String,
    val temperature: Float = 0.0f,
    val inferenceTimeoutMs: Long = 60_000L,
    private val storageVerifier: (() -> Boolean)? = null
) : LlmEngine {

    companion object {
        private const val TAG = "ExecuTorchEngine"
        const val MAX_MODEL_SEQ_LEN = 2048
        private const val ASSISTANT_HEADER = "<|start_header_id|>assistant<|end_header_id|>"
        private val SPECIAL_TOKENS = listOf(
            "<|eot_id|>",
            "<|end_of_text|>",
            "<|eom_id|>",
            "<|begin_of_text|>"
        )

        /**
         * Conservative upper-bound BPE token estimate to safely bound ExecuTorch's per-request
         * seq_len (= prompt tokens + max new tokens) below [MAX_MODEL_SEQ_LEN] without triggering
         * native assert(num_prompt_tokens < seq_len).
         */
        internal fun estimateUpperPromptTokens(prompt: String): Int {
            var ascii = 0
            var nonAscii = 0
            for (ch in prompt) {
                if (ch.code < 128) ascii++ else nonAscii++
            }
            return kotlin.math.ceil(ascii * 0.45).toInt() + kotlin.math.ceil(nonAscii * 2.5).toInt() + 64
        }

        internal fun computeBoundedSeqLen(prompt: String, maxNewTokens: Int): Int {
            val budgetNew = maxOf(1, maxNewTokens)
            val total = estimateUpperPromptTokens(prompt) + budgetNew
            return minOf(MAX_MODEL_SEQ_LEN, maxOf(128, total))
        }

        /**
         * Removes echoed Llama 3 input prompt and trailing/special control tokens
         * from raw LlmModule callback accumulation.
         */
        internal fun stripPromptEchoAndSpecialTokens(raw: String, prompt: String): String {
            if (raw.isEmpty()) return ""

            var text = when {
                prompt.isNotEmpty() && raw.startsWith(prompt) -> {
                    raw.substring(prompt.length)
                }
                prompt.isNotEmpty() -> {
                    // Handle cases where runner omitted <|begin_of_text|> or whitespace around echo
                    val noBosPrompt = prompt.removePrefix("<|begin_of_text|>")
                    when {
                        noBosPrompt.isNotEmpty() && raw.startsWith(noBosPrompt) -> {
                            raw.substring(noBosPrompt.length)
                        }
                        raw.contains(ASSISTANT_HEADER) -> {
                            val idx = raw.lastIndexOf(ASSISTANT_HEADER)
                            raw.substring(idx + ASSISTANT_HEADER.length).trimStart('\n', '\r')
                        }
                        else -> raw
                    }
                }
                else -> raw
            }

            // Cut at first EOT / end_of_text if any spurious text follows stop token
            for (stopTok in listOf("<|eot_id|>", "<|end_of_text|>", "<|eom_id|>")) {
                val stopIdx = text.indexOf(stopTok)
                if (stopIdx >= 0) {
                    text = text.substring(0, stopIdx)
                }
            }
            for (tok in SPECIAL_TOKENS) {
                text = text.replace(tok, "")
            }
            return text.trim()
        }

        private fun safeLogI(msg: String) {
            try { Log.i(TAG, msg) } catch (_: RuntimeException) {}
        }

        private fun safeLogW(msg: String) {
            try { Log.w(TAG, msg) } catch (_: RuntimeException) {}
        }

        private fun safeLogE(msg: String, t: Throwable? = null) {
            try {
                if (t != null) Log.e(TAG, msg, t) else Log.e(TAG, msg)
            } catch (_: RuntimeException) {}
        }
    }

    private val moduleLock = Any()
    private val watchdogExecutor = Executors.newSingleThreadScheduledExecutor { r ->
        Thread(r, "ExecuTorch-Watchdog").apply { isDaemon = true }
    }

    private var module: LlmModule? = null

    @Volatile var isLoaded: Boolean = false
        private set

    @Volatile var modelLoadTimeMs: Long = 0L
        private set

    @Volatile var lastStats: String = ""
        private set

    @Volatile var lastMetrics: InferenceMetrics? = null
        private set

    @Volatile var lastError: String? = null
        private set

    @Volatile private var cancelled: Boolean = false

    /**
     * Loads the model once if not already loaded. Safe to call repeatedly from background threads.
     */
    fun load(): Boolean {
        synchronized(moduleLock) {
            if (isLoaded && module != null) {
                return true
            }
            lastError = null

            if (storageVerifier != null) {
                val ok = try {
                    storageVerifier.invoke()
                } catch (t: Throwable) {
                    lastError = "Model storage verification failed: ${t.message}"
                    safeLogE(lastError!!, t)
                    return false
                }
                if (!ok) {
                    lastError = "Model files missing or failed integrity check at $modelPath"
                    safeLogW(lastError!!)
                    return false
                }
            }

            val mFile = File(modelPath)
            val tFile = File(tokenizerPath)
            if (!mFile.exists() || mFile.length() <= 0L) {
                lastError = "Model file unavailable at $modelPath"
                safeLogW(lastError!!)
                return false
            }
            if (!tFile.exists() || tFile.length() <= 0L) {
                lastError = "Tokenizer file unavailable at $tokenizerPath"
                safeLogW(lastError!!)
                return false
            }

            return try {
                safeLogI("Loading ExecuTorch 0.6.0 LlmModule from $modelPath (${mFile.length()} bytes)")
                val t0 = System.currentTimeMillis()
                val instance = LlmModule(modelPath, tokenizerPath, temperature)
                val rc = instance.load()
                val elapsed = System.currentTimeMillis() - t0
                if (rc != 0) {
                    lastError = "LlmModule.load() failed with status code $rc"
                    safeLogE(lastError!!)
                    isLoaded = false
                    module = null
                    false
                } else {
                    module = instance
                    modelLoadTimeMs = elapsed
                    isLoaded = true
                    safeLogI("ExecuTorch model loaded once in ${elapsed}ms")
                    true
                }
            } catch (t: Throwable) {
                lastError = "ExecuTorch load error (${t.javaClass.simpleName}): ${t.message}"
                safeLogE(lastError!!, t)
                isLoaded = false
                module = null
                false
            }
        }
    }

    fun resetCancellation() {
        cancelled = false
    }

    override fun chat(messages: List<ChatMessage>, maxTokens: Int): String {
        return chatWithStreaming(messages, maxTokens, onToken = null)
    }

    fun chatWithStreaming(
        messages: List<ChatMessage>,
        maxTokens: Int = RoadmapGenerator.DEFAULT_WEEK_MAX_TOKENS,
        onToken: ((String) -> Unit)? = null
    ): String {
        if (cancelled) {
            throw IllegalStateException("Inference cancelled by user")
        }
        if (!load()) {
            throw IllegalStateException(lastError ?: "ExecuTorch model is not loaded")
        }

        val activeModule = module ?: throw IllegalStateException("ExecuTorch module instance is null")
        val prompt = Llama3Prompt.build(messages)

        synchronized(moduleLock) {
            if (cancelled) {
                throw IllegalStateException("Inference cancelled by user")
            }

            val rawBuffer = StringBuilder()
            var firstAssistantTokenTs = 0L
            var assistantCallbacks = 0
            var reportedTokPerSec = 0.0
            var timedOut = false
            var stoppedAtTokenCap = false

            val startTs = System.currentTimeMillis()
            val watchdog: ScheduledFuture<*> = watchdogExecutor.schedule({
                timedOut = true
                safeLogW("Inference exceeded ${inferenceTimeoutMs}ms timeout; stopping LlmModule")
                try {
                    activeModule.stop()
                } catch (_: Throwable) {}
            }, inferenceTimeoutMs, TimeUnit.MILLISECONDS)

            val callback = object : CompatibleLlmCallback() {
                override fun onResult(result: String) {
                    val now = System.currentTimeMillis()
                    if (stoppedAtTokenCap || cancelled || timedOut) return

                    rawBuffer.append(result)
                    if (firstAssistantTokenTs == 0L && result.isNotEmpty()) {
                        firstAssistantTokenTs = now
                    }
                    assistantCallbacks++
                    onToken?.invoke(result)

                    if (maxTokens > 0 && assistantCallbacks >= maxTokens) {
                        stoppedAtTokenCap = true
                        safeLogI("Reached new-token cap ($maxTokens); stopping generation")
                        try {
                            activeModule.stop()
                        } catch (_: Throwable) {}
                    }
                }

                override fun onSpeedReported(speed: Double) {
                    reportedTokPerSec = speed
                }
            }

            val boundedSeqLen = computeBoundedSeqLen(prompt, maxTokens)
            val genRet: Int
            try {
                // ExecuTorch 0.6.0 LlmModule.generate(prompt, seqLen, callback, echo) takes total seq_len
                // (prompt + generated tokens <= MAX_MODEL_SEQ_LEN), NOT max_new_tokens. Pass echo=false
                // so callbacks deliver assistant tokens directly without prompt echo inflation.
                safeLogI("Starting generation: promptChars=${prompt.length}, seqLen=$boundedSeqLen, maxNewTokens=$maxTokens")
                genRet = activeModule.generate(prompt, boundedSeqLen, callback, false)
            } catch (t: Throwable) {
                watchdog.cancel(false)
                lastError = "LlmModule.generate failed (${t.javaClass.simpleName}): ${t.message}"
                safeLogE(lastError!!, t)
                throw RuntimeException(lastError, t)
            } finally {
                watchdog.cancel(false)
            }

            val endTs = System.currentTimeMillis()
            val totalMs = endTs - startTs
            val ttftMs = if (firstAssistantTokenTs > 0L) firstAssistantTokenTs - startTs else totalMs

            if (timedOut) {
                lastError = "Inference timed out after ${inferenceTimeoutMs}ms"
                throw RuntimeException(lastError)
            }
            if (cancelled && !stoppedAtTokenCap) {
                lastError = "Inference stopped before completion"
                throw RuntimeException(lastError)
            }
            if (genRet != 0 && !stoppedAtTokenCap) {
                lastError = "LlmModule.generate returned non-zero status code $genRet"
                safeLogW(lastError!!)
                throw RuntimeException(lastError)
            }

            val cleaned = stripPromptEchoAndSpecialTokens(rawBuffer.toString(), prompt)
            val metrics = InferenceMetrics(
                modelLoadTimeMs = modelLoadTimeMs,
                ttftMs = ttftMs,
                totalTimeMs = totalMs,
                reportedTokPerSec = reportedTokPerSec,
                generatedCallbacks = assistantCallbacks,
                promptChars = prompt.length,
                outputChars = cleaned.length
            )
            lastMetrics = metrics
            lastStats = "TTFT=${ttftMs}ms, total=${totalMs}ms, speed=%.2f tok/s, callbacks=$assistantCallbacks, outChars=${cleaned.length}".format(reportedTokPerSec)
            safeLogI("LLM generation finished: $lastStats")

            if (cleaned.isBlank()) {
                lastError = "Model returned blank output after stripping prompt echo"
                throw IllegalStateException(lastError)
            }
            return cleaned
        }
    }

    fun stop() {
        cancelled = true
        try {
            module?.stop()
        } catch (t: Throwable) {
            safeLogW("Error stopping module: ${t.message}")
        }
    }
}
