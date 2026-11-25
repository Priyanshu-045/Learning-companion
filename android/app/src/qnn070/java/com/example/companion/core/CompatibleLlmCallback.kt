package com.example.companion.core

import android.util.Log
import org.json.JSONObject
import org.pytorch.executorch.extension.llm.LlmCallback

abstract class CompatibleLlmCallback : LlmCallback {
    abstract fun onSpeedReported(speed: Double)

    override fun onStats(stats: String) {
        Log.i("CompatibleLlmCallback", "Raw stats from QNN: $stats")
        val speed = try {
            val obj = JSONObject(stats)
            val genTokens = obj.optInt("generated_tokens", 0)
            val firstTokenMs = obj.optLong("first_token_ms", 0L)
            val inferenceEndMs = obj.optLong("inference_end_ms", 0L)
            val decodeDurationMs = inferenceEndMs - firstTokenMs
            if (genTokens > 1 && decodeDurationMs > 0) {
                ((genTokens - 1).toDouble() * 1000.0) / decodeDurationMs
            } else {
                obj.optDouble(
                    "tokens_per_second",
                    obj.optDouble(
                        "generated_tokens_per_second",
                        obj.optDouble(
                            "generated_tokens_rate",
                            obj.optDouble("tps", 0.0)
                        )
                    )
                )
            }
        } catch (e: Exception) {
            Log.w("CompatibleLlmCallback", "Failed to parse QNN stats: ${e.message}")
            0.0
        }
        onSpeedReported(speed)
    }
}

