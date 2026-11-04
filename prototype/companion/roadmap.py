"""LLM-driven week filling with validation, one retry, and a deterministic fallback."""
import json
import math
import re

from .lang import LANG_NAMES, script_ok
from .planner import SHARED, load_graph, find_gaps, pack, remaining_queue, adapt_queue, validate_hours

SYSTEM_ROADMAP = (SHARED / "prompts" / "system_roadmap.txt").read_text(encoding="utf-8")
SYSTEM_QUIZ = (SHARED / "prompts" / "system_quiz.txt").read_text(encoding="utf-8")


class ValidationError(ValueError):
    pass


def extract_json(text):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    a, b = t.find("{"), t.rfind("}")
    if a == -1 or b <= a:
        raise ValidationError("no JSON object found")
    try:
        return json.loads(t[a:b + 1])
    except json.JSONDecodeError as e:
        raise ValidationError(f"invalid JSON: {e}")


def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def validate_week(obj, budget_minutes, allowed):
    """Strict schema check + deterministic clean-up (resource snapping, minutes rescaled to budget)."""
    if not isinstance(obj, dict):
        raise ValidationError("top level must be an object")
    title, ms, tasks = obj.get("title"), obj.get("milestone"), obj.get("tasks")
    if not isinstance(title, str) or not title.strip():
        raise ValidationError("missing 'title'")
    if not isinstance(ms, str) or not ms.strip():
        raise ValidationError("missing 'milestone'")
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 14:
        raise ValidationError("'tasks' must be a list of 1-14 items")
    clean = []
    for t in tasks:
        if not isinstance(t, dict):
            raise ValidationError("each task must be an object")
        day, text, mins, res = t.get("day"), t.get("task"), t.get("minutes"), t.get("resource")
        if not (isinstance(day, int) and not isinstance(day, bool) and 1 <= day <= 7):
            raise ValidationError("'day' must be an integer 1-7")
        if not isinstance(text, str) or not text.strip():
            raise ValidationError("task text missing")
        if not _is_num(mins) or not math.isfinite(mins) or mins <= 0:
            raise ValidationError("'minutes' must be a positive, finite number")
        if allowed and res not in allowed:
            res = allowed[0]  # never trust model-invented resources
        clean.append({"day": day, "task": text.strip(), "minutes": float(mins), "resource": res or ""})
    scale = budget_minutes / sum(t["minutes"] for t in clean)
    for t in clean:
        t["minutes"] = max(5, int(round(t["minutes"] * scale / 5)) * 5)
    clean.sort(key=lambda t: t["day"])
    return {"title": title.strip(), "tasks": clean, "milestone": ms.strip()}


def template_week(week, nodes):
    """Last-resort deterministic week (English only) so the app never crashes or shows nothing."""
    tasks, k = [], 0
    for it in week["items"]:
        n = nodes[it["node"]]
        total = it["hours"] * 60
        sessions = max(1, math.ceil(total / 60))
        for _ in range(sessions):
            tasks.append({"day": k % 5 + 1, "task": ("Revise " if it["revision"] else "Study ") + n["name"],
                          "minutes": int(round(total / sessions / 5)) * 5 or 5, "resource": n["resources"][0]})
            k += 1
    names = ", ".join(nodes[i["node"]]["name"] for i in week["items"])
    return {"title": f"Week {week['week']}: {names}", "tasks": tasks,
            "milestone": "Finish the listed topics and note one question for each"}


def fill_week(llm, graph, week, meta, attempts=2):
    nodes = {n["id"]: n for n in graph["nodes"]}
    lang = meta["language"]
    allowed = []
    for it in week["items"]:
        for r in nodes[it["node"]]["resources"]:
            if r not in allowed:
                allowed.append(r)
    budget = int(round(sum(i["hours"] for i in week["items"]) * 60))
    payload = {"task": "fill_week", "language": lang, "goal": meta["goal"], "week": week["week"],
               "weekly_hours": meta["weekly_hours"],
               "focus": [{"node": i["node"], "name": nodes[i["node"]]["name"], "hours": i["hours"],
                          "revision": i["revision"]} for i in week["items"]],
               "allowed_resources": allowed}
    messages = [{"role": "system", "content": SYSTEM_ROADMAP.replace("{LANGUAGE_NAME}", LANG_NAMES[lang])},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
    err = None
    for _ in range(attempts):
        raw = ""
        try:
            raw = llm.chat(messages)
            data = validate_week(extract_json(raw), budget, allowed)
            text = " ".join([data["title"], data["milestone"]] + [t["task"] for t in data["tasks"]])
            for term in sorted([n["name"] for n in nodes.values()] + allowed, key=len, reverse=True):
                text = text.replace(term, " ")  # English topic names / resource titles are allowed technical terms
            if not script_ok(text, lang):
                raise ValidationError(f"all text values must be written only in {LANG_NAMES[lang]}")
            return {**week, **data, "source": "llm"}
        except ValidationError as e:
            err = e
            messages += [{"role": "assistant", "content": raw},
                         {"role": "user", "content": f"Invalid output: {e}. Return only the corrected JSON object."}]
        except Exception as e:  # backend failure (model not loaded, server down...)
            err = e
            break
    return {**week, **template_week(week, nodes), "source": "fallback", "error": str(err)}


def build_plan(llm, domain, weekly_hours, known, lang):
    if lang not in LANG_NAMES:
        raise ValueError(f"unsupported language '{lang}'. Supported: {', '.join(LANG_NAMES)}")
    weekly_hours = validate_hours(weekly_hours)
    graph = load_graph(domain)
    unknown = sorted(set(known) - {n["id"] for n in graph["nodes"]})
    if unknown:
        raise ValueError(f"unknown skill id(s) for {domain}: {', '.join(unknown)}")
    gaps = find_gaps(graph, known)
    nodes = {n["id"]: n for n in graph["nodes"]}
    meta = {"domain": domain, "goal": graph["title"], "language": lang, "weekly_hours": weekly_hours,
            "known": sorted(known), "skill_gaps": gaps, "adaptations": [],
            "status": "active" if gaps else "complete",
            "generated_by": getattr(llm, "model_id", "unknown")}
    queue = [{"node": g, "hours": nodes[g]["hours"], "revision": False} for g in gaps]
    return {**meta, "weeks": [fill_week(llm, graph, w, meta) for w in pack(queue, weekly_hours)]}


def adapt_plan(llm, plan, week_no, score):
    """Record a weekly quiz score; deterministically re-plan later weeks; LLM only re-fills them."""
    weeks = plan["weeks"]
    if not weeks:
        raise ValueError("this plan has no weeks to adapt (all skills were already known)")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0.0 <= score <= 1.0:
        raise ValueError(f"score must be a number between 0 and 1, got {score!r}")
    if not 1 <= week_no <= len(weeks):
        raise ValueError(f"week must be 1..{len(weeks)}")
    if any("score" not in w for w in weeks[:week_no - 1]):
        raise ValueError(f"record the quiz for earlier weeks first (weeks are adapted in order)")
    if "score" in weeks[week_no - 1]:
        raise ValueError(f"week {week_no} already has a recorded score")
    graph = load_graph(plan["domain"])
    done = [dict(w) for w in weeks[:week_no]]
    done[-1]["score"] = score
    queue, action = adapt_queue(weeks[week_no - 1]["items"], remaining_queue(weeks[week_no:]), score)
    new = [fill_week(llm, graph, w, plan) for w in pack(queue, plan["weekly_hours"], start_week=week_no + 1)]
    return {**plan, "weeks": done + new,
            "adaptations": plan.get("adaptations", []) + [{"week": week_no, "score": score, "action": action}]}


def validate_quiz(obj, count):
    qs = obj.get("questions") if isinstance(obj, dict) else None
    if not isinstance(qs, list) or not qs:
        raise ValidationError("'questions' must be a non-empty list")
    out = []
    for q in qs[:count]:
        if not (isinstance(q, dict) and isinstance(q.get("q"), str) and isinstance(q.get("options"), list)
                and len(q["options"]) == 4 and all(isinstance(o, str) for o in q["options"])
                and isinstance(q.get("answer_index"), int) and 0 <= q["answer_index"] <= 3):
            raise ValidationError("each question needs q, 4 string options, answer_index 0-3")
        out.append({"q": q["q"], "options": q["options"], "answer_index": q["answer_index"]})
    if len(out) < count:
        raise ValidationError(f"expected {count} questions, got {len(out)}")
    return out


def generate_quiz(llm, topic, lang, count=5, attempts=2):
    messages = [{"role": "system", "content": SYSTEM_QUIZ.replace("{LANGUAGE_NAME}", LANG_NAMES[lang])},
                {"role": "user", "content": json.dumps({"topic": topic, "language": lang, "count": count},
                                                       ensure_ascii=False)}]
    err = None
    for _ in range(attempts):
        try:
            raw = llm.chat(messages)
        except Exception as e:
            raise ValidationError(f"quiz generation failed: model backend error: {e}")
        try:
            qs = validate_quiz(extract_json(raw), count)
            if not script_ok(" ".join(q["q"] for q in qs), lang):
                raise ValidationError(f"questions must be written only in {LANG_NAMES[lang]}")
            return qs
        except ValidationError as e:
            err = e
            messages += [{"role": "assistant", "content": raw},
                         {"role": "user", "content": f"Invalid output: {e}. Return only the corrected JSON object."}]
    raise ValidationError(f"quiz generation failed: {err}")
