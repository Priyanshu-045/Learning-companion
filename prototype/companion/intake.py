"""Goal understanding: free text -> learner profile, plus the next scripted intake question.
Deterministic by design (fast, offline, testable); the LLM is only used later for tutoring.
Question strings and non-English keywords NEED NATIVE-SPEAKER REVIEW before release."""
import re
import unicodedata

from .lang import detect_language
from .planner import list_domains, load_graph

DOMAIN_KEYWORDS = {
    "ml_engineer": ["machine learning", "ml", "deep learning", "artificial intelligence", "ai", "neural network",
                    "pytorch", "tensorflow", "मशीन लर्निंग", "डीप लर्निंग", "कृत्रिम बुद्धिमत्ता", "एआई",
                    "இயந்திர கற்றல்", "மெஷின் லேர்னிங்", "செயற்கை நுண்ணறிவு",
                    "మెషిన్ లెర్నింగ్", "కృత్రిమ మేధ", "డీప్ లెర్నింగ్",
                    "মেশিন লার্নিং", "কৃত্রিম বুদ্ধিমত্তা", "ডিপ লার্নিং"],
    "web_dev": ["web developer", "web development", "website", "frontend", "front-end", "backend", "react", "html",
                "css", "javascript", "node.js", "full stack", "fullstack", "वेब", "வலை", "இணையதள", "வெப்",
                "వెబ్", "ওয়েব"],
    "data_analysis": ["data analysis", "data analyst", "data science", "data scientist", "analytics", "excel", "sql",
                      "power bi", "tableau", "dashboard", "डेटा", "डाटा", "தரவு", "டேட்டா", "డేటా", "ডেটা", "ডাটা"],
}

HOUR_WORDS = ["hour", "hr", "घंटे", "घंटा", "घण्टे", "तास", "மணி", "గంట", "ঘণ্টা", "ঘন্টা"]
DAY_WORDS = ["day", "daily", "दिन", "रोज", "தினம்", "రోజు", "দিন"]
KNOW_CUES = ["know", "knew", "already", "familiar", "experience", "comfortable", "learned", "learnt", "studied",
             "completed", "finished", "good at", "आता है", "आती है", "पता है", "जानता", "जानती", "पहले से",
             "सीख चुका", "सीख चुकी"]
WANT_CUES = ["want", "wish", "need", "learn", "planning", "plan to", "interested", "start", "beginner",
             "new to", "सीखना", "चाहता", "चाहती", "चाहिए"]
NEGATIONS = ["don't know", "do not know", "dont know", "no idea", "not familiar", "never"]
_STOP = {"and", "basics", "fundamentals", "with", "of", "to", "the", "refresher", "introduction", "on-device"}

QUESTIONS = {
    "en": {"goal": "What do you want to achieve? (for example: become a Machine Learning Engineer)",
           "hours": "How many hours per week can you study?",
           "known": "Which of these skills do you already know?"},
    "hi": {"goal": "आप क्या हासिल करना चाहते हैं? (जैसे: मशीन लर्निंग इंजीनियर बनना)",
           "hours": "आप हफ़्ते में कितने घंटे पढ़ाई कर सकते हैं?",
           "known": "इनमें से कौन-से कौशल आपको पहले से आते हैं?"},
    "mr": {"goal": "तुम्हाला काय साध्य करायचे आहे? (उदा. मशीन लर्निंग इंजिनिअर होणे)",
           "hours": "तुम्ही आठवड्यात किती तास अभ्यास करू शकता?",
           "known": "यापैकी कोणती कौशल्ये तुम्हाला आधीपासून येतात?"},
    "ta": {"goal": "நீங்கள் எதை அடைய விரும்புகிறீர்கள்? (எ.கா: இயந்திர கற்றல் பொறியாளர் ஆவது)",
           "hours": "வாரத்திற்கு எத்தனை மணிநேரம் படிக்க முடியும்?",
           "known": "இவற்றில் எந்த திறன்கள் உங்களுக்கு ஏற்கனவே தெரியும்?"},
    "te": {"goal": "మీరు ఏమి సాధించాలనుకుంటున్నారు? (ఉదా: మెషిన్ లెర్నింగ్ ఇంజనీర్ కావడం)",
           "hours": "వారానికి ఎన్ని గంటలు చదవగలరు?",
           "known": "వీటిలో ఏ నైపుణ్యాలు మీకు ఇప్పటికే తెలుసు?"},
    "bn": {"goal": "আপনি কী অর্জন করতে চান? (যেমন: মেশিন লার্নিং ইঞ্জিনিয়ার হওয়া)",
           "hours": "সপ্তাহে কত ঘণ্টা পড়াশোনা করতে পারবেন?",
           "known": "এর মধ্যে কোন দক্ষতাগুলো আপনার আগে থেকেই জানা আছে?"},
}


def normalize_digits(text):
    return "".join(str(unicodedata.digit(c)) if c.isdigit() else c for c in text)


def _hit(kw, text):
    if kw.isascii():
        return re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", text) is not None
    return kw in text


def infer_domain(text):
    t = text.lower()
    scores = {d: sum(_hit(k, t) for k in kws) for d, kws in DOMAIN_KEYWORDS.items() if d in list_domains()}
    best = max(scores.values(), default=0)
    if best == 0:
        return None, []
    top = [d for d, s in scores.items() if s == best]
    return (top[0] if len(top) == 1 else None), top


def extract_hours(text):
    """Weekly hours from phrases like '5 hours a week', '2 hrs per day' (x7), '5 घंटे'. None if absent."""
    t = normalize_digits(text.lower())
    for m in re.finditer(r"(\d+(?:\.\d+)?)", t):
        after = t[m.end():m.end() + 30]
        near = after.lstrip(" -")[:8]
        if any(near.startswith(w) for w in HOUR_WORDS):
            h = float(m.group(1))
            if any(w in after for w in DAY_WORDS) and not re.search(r"week|हफ़?्त|आठवड|வார|వార|সপ্তাহ", after):
                h *= 7
            return h
    return None


def _aliases(graph):
    nodes = graph["nodes"]
    toks = {n["id"]: [w for w in re.findall(r"[a-z0-9.+#]+", n["name"].lower()) if w not in _STOP] for n in nodes}
    freq = {}
    for ws in toks.values():
        for w in set(ws):
            freq[w] = freq.get(w, 0) + 1
    out = {}
    for nid, ws in toks.items():
        a = {" ".join(ws)} | {w for w in ws if freq[w] == 1 and len(w) >= 3}
        out[nid] = a
    return out


def extract_known(text, domain, answering=False):
    """Skills the learner says they already know. Conservative: 'I want to learn Python' is NOT known."""
    graph = load_graph(domain)
    aliases = _aliases(graph)
    t = text.lower()
    for n in NEGATIONS:
        t = t.replace(n, " WANTCUE ")
    known = set()
    for clause in re.split(r"[.;!\n]| but | और |, ", t):
        for nid, als in aliases.items():
            for a in als:
                m = re.search(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", clause)
                if not m:
                    continue
                if answering:
                    if not re.search(r"wantcue", clause[:m.start()]):
                        known.add(nid)
                    continue
                before = clause[:m.start()]
                k = max([before.rfind(c) for c in KNOW_CUES], default=-1)
                w = max([before.rfind(c) for c in WANT_CUES + ["wantcue"] if not (c == "learn")]
                        + [mm.start() for mm in re.finditer(r"learn(?!ed|t)", before)], default=-1)
                if k > w and k >= 0:
                    known.add(nid)
    return sorted(known)


def understand(text, prior=None, answering=None):
    """Merge one learner message into the profile. answering: 'goal' | 'hours' | 'known' | None."""
    p = dict(prior or {})
    p.setdefault("language", None)
    p.setdefault("domain", None)
    p.setdefault("weekly_hours", None)
    p.setdefault("known", [])
    p.setdefault("known_answered", False)
    if p["language"] is None or answering in (None, "goal"):
        p["language"] = detect_language(text) if text.strip() else (p["language"] or "en")
    if p["domain"] is None:
        d, cands = infer_domain(text)
        p["domain"], p["domain_candidates"] = d, cands
    h = extract_hours(text)
    if h is not None and 0 < h <= 100:
        p["weekly_hours"] = h
    elif answering == "hours":
        m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*", normalize_digits(text))
        if m and 0 < float(m.group(1)) <= 100:
            p["weekly_hours"] = float(m.group(1))
    if p["domain"]:
        found = extract_known(text, p["domain"], answering=(answering == "known"))
        p["known"] = sorted(set(p["known"]) | set(found))
    if answering == "known":
        p["known_answered"] = True
    p["missing"] = [k for k, absent in (("goal", p["domain"] is None), ("hours", p["weekly_hours"] is None),
                                        ("known", not p["known_answered"])) if absent]
    return p


def next_question(profile):
    """The next scripted question in the learner's language, or None when intake is complete."""
    if not profile["missing"]:
        return None
    key = profile["missing"][0]
    q = QUESTIONS[profile.get("language") or "en"][key]
    if key == "known" and profile.get("domain"):
        names = ", ".join(n["name"] for n in load_graph(profile["domain"])["nodes"])
        q += f"\n{names}"
    return q
