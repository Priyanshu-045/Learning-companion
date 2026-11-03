package com.example.companion

// API NOTE: the Java/Kotlin LLM API changed between ExecuTorch releases. This file targets the
// `org.pytorch.executorch.extension.llm` package (LlmModule / LlmCallback). Older releases expose
// `org.pytorch.executorch.LlamaModule` / `LlamaCallback` instead (and a constructor taking a model type).
// Open examples/demo-apps/android/LlamaDemo in YOUR ExecuTorch checkout and mirror how it constructs
// the module and calls generate(); adjust the 3-4 lines marked VERIFY below.
import org.pytorch.executorch.extension.llm.LlmCallback
import org.pytorch.executorch.extension.llm.LlmModule

class ExecuTorchEngine(
    modelPath: String,        // e.g. /data/local/tmp/llama/llama3_2.pte
    tokenizerPath: String,    // e.g. /data/local/tmp/llama/tokenizer.model
    temperature: Float = 0.3f // low temperature = more reliable JSON
) : LlmEngine {

    private val module = LlmModule(modelPath, tokenizerPath, temperature) // VERIFY constructor
    @Volatile var lastStats: String = ""
        private set

    fun load() { module.load() } // VERIFY: some versions load lazily on first generate()

    override fun chat(messages: List<ChatMessage>, maxTokens: Int): String {
        val out = StringBuilder()
        module.generate(Llama3Prompt.build(messages), maxTokens, object : LlmCallback { // VERIFY signature
            override fun onResult(result: String) { out.append(result) }
            override fun onStats(stats: String) { lastStats = stats } // contains tokens/sec; log it for your report
        })
        return out.toString()
    }

    fun stop() = module.stop()
}
