package com.example.companion

/** Anything that can answer a chat. Real implementation: ExecuTorchEngine. Tests can use a fake. */
interface LlmEngine {
    /** Blocking. Call from a background thread / Dispatchers.Default, never the UI thread. */
    fun chat(messages: List<ChatMessage>, maxTokens: Int = 700): String
}

object Llama3Prompt {
    /** Llama 3.x chat template. NOTE: some ExecuTorch runner versions add <|begin_of_text|> themselves;
     *  if you see it twice in the logs, remove it here. */
    fun build(messages: List<ChatMessage>): String {
        val sb = StringBuilder("<|begin_of_text|>")
        for (m in messages) sb.append("<|start_header_id|>${m.role}<|end_header_id|>\n\n${m.content}<|eot_id|>")
        sb.append("<|start_header_id|>assistant<|end_header_id|>\n\n")
        return sb.toString()
    }
}
