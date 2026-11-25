package com.example.companion.core

/** LLM Engine interface. Implemented by ExecuTorchEngine and MockLlmEngine. */
interface LlmEngine {
    fun chat(messages: List<ChatMessage>, maxTokens: Int = 700): String
}

object Llama3Prompt {
    fun build(messages: List<ChatMessage>): String {
        val sb = StringBuilder("<|begin_of_text|>")
        for (m in messages) {
            sb.append("<|start_header_id|>${m.role}<|end_header_id|>\n\n${m.content}<|eot_id|>")
        }
        sb.append("<|start_header_id|>assistant<|end_header_id|>\n\n")
        return sb.toString()
    }
}

/** Offline engine for zero-dependency development, fast testing, and instant roadmap fallback. */
class MockLlmEngine : LlmEngine {
    override fun chat(messages: List<ChatMessage>, maxTokens: Int): String {
        // Returns empty to trigger high-quality localized deterministic generator
        return ""
    }
}

