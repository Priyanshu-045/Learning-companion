"""Deterministic language detection + one-language-rule check (no model needed)."""
LANG_NAMES = {"en": "English", "hi": "Hindi", "mr": "Marathi",
              "ta": "Tamil", "te": "Telugu", "bn": "Bengali"}
RANGES = {"deva": (0x0900, 0x097F), "beng": (0x0980, 0x09FF),
          "taml": (0x0B80, 0x0BFF), "telu": (0x0C00, 0x0C7F)}
SCRIPT_OF = {"hi": "deva", "mr": "deva", "ta": "taml", "te": "telu", "bn": "beng"}
MR_MARKERS = ["आहे", "आहेत", "मला", "माझ", "पाहिजे", "करायच", "साठी", "आणि", "काय", "कसा", "कसे", "नाही"]
HI_MARKERS = ["है", "हैं", "मुझे", "चाहिए", "और", "के लिए", "में", "का ", "की ", "को ", "नहीं", "क्या"]


def script_counts(text):
    counts = {k: 0 for k in RANGES}
    counts["latin"] = 0
    for ch in text:
        if not ch.isalpha():
            continue
        o = ord(ch)
        for k, (a, b) in RANGES.items():
            if a <= o <= b:
                counts[k] += 1
                break
        else:
            if o < 0x250:
                counts["latin"] += 1
    return counts


def detect_language(text):
    """Return 'en','hi','mr','ta','te','bn'. Romanized Hindi (e.g. 'mujhe plan chahiye') is NOT detected."""
    c = script_counts(text)
    indic = {k: v for k, v in c.items() if k != "latin"}
    top = max(indic, key=indic.get)
    if indic[top] < 3:
        return "en"
    if top == "deva":
        mr = sum(text.count(m) for m in MR_MARKERS)
        hi = sum(text.count(m) for m in HI_MARKERS)
        return "mr" if mr > hi else "hi"
    return {"beng": "bn", "taml": "ta", "telu": "te"}[top]


def script_ok(text, lang):
    """Coarse guard for the 'respond entirely in the user's language' rule.
    Fails on any letters from a different Indic script. Latin words are allowed
    (technical terms) as long as the target script is at least 15% of letters."""
    c = script_counts(text)
    indic = {k: v for k, v in c.items() if k != "latin"}
    if lang == "en":
        return sum(indic.values()) == 0
    want = SCRIPT_OF[lang]
    total = sum(c.values())
    foreign = sum(v for k, v in indic.items() if k != want)
    return foreign == 0 and total > 0 and indic[want] / total >= 0.15
