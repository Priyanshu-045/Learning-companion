package com.example.companion.core

import org.pytorch.executorch.extension.llm.LlmCallback

abstract class CompatibleLlmCallback : LlmCallback {
    abstract fun onSpeedReported(speed: Double)

    override fun onStats(stats: Float) {
        onSpeedReported(stats.toDouble())
    }
}

