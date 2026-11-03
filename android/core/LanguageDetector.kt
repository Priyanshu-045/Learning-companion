package com.example.companion

enum class Lang(val code: String, val displayName: String, val script: String?) {
    EN("en", "English", null), HI("hi", "Hindi", "deva"), MR("mr", "Marathi", "deva"),
    TA("ta", "Tamil", "taml"), TE("te", "Telugu", "telu"), BN("bn", "Bengali", "beng");
    companion object { fun fromCode(c: String) = values().first { it.code == c } }
}

/** Deterministic language detection (no model). Port of prototype/companion/lang.py. */
object LanguageDetector {
    private val ranges = linkedMapOf("deva" to 0x0900..0x097F, "beng" to 0x0980..0x09FF,
        "taml" to 0x0B80..0x0BFF, "telu" to 0x0C00..0x0C7F)
    private val mrMarkers = listOf("आहे", "आहेत", "मला", "माझ", "पाहिजे", "करायच", "साठी", "आणि", "काय", "कसा", "कसे", "नाही")
    private val hiMarkers = listOf("है", "हैं", "मुझे", "चाहिए", "और", "के लिए", "में", "का ", "की ", "को ", "नहीं", "क्या")

    fun scriptCounts(text: String): Map<String, Int> {
        val c = linkedMapOf("deva" to 0, "beng" to 0, "taml" to 0, "telu" to 0, "latin" to 0)
        for (ch in text) {
            if (!ch.isLetter()) continue
            val o = ch.code
            val key = ranges.entries.firstOrNull { o in it.value }?.key ?: (if (o < 0x250) "latin" else null)
            if (key != null) c[key] = c.getValue(key) + 1
        }
        return c
    }

    private fun count(text: String, m: String) = text.split(m).size - 1

    fun detect(text: String): Lang {
        val indic = scriptCounts(text).filterKeys { it != "latin" }
        val top = indic.maxByOrNull { it.value }!!
        if (top.value < 3) return Lang.EN
        return when (top.key) {
            "deva" -> if (mrMarkers.sumOf { count(text, it) } > hiMarkers.sumOf { count(text, it) }) Lang.MR else Lang.HI
            "beng" -> Lang.BN
            "taml" -> Lang.TA
            else -> Lang.TE
        }
    }

    /** Coarse guard for the "respond entirely in the user's language" rule. */
    fun scriptOk(text: String, lang: Lang): Boolean {
        val c = scriptCounts(text)
        val indic = c.filterKeys { it != "latin" }
        if (lang == Lang.EN) return indic.values.sum() == 0
        val total = c.values.sum()
        val want = indic.getValue(lang.script!!)
        val foreign = indic.filterKeys { it != lang.script }.values.sum()
        return foreign == 0 && total > 0 && want.toDouble() / total >= 0.15
    }
}
