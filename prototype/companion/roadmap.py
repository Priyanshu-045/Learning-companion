"""LLM-driven week filling with validation, one retry, and a deterministic fallback."""
import json
import math
import re

from .lang import LANG_NAMES, script_ok
from .planner import SHARED, load_graph, find_gaps, pack, remaining_queue, adapt_queue, validate_hours

# M2.2C: Deterministic workload distribution
MAX_DAILY_MINUTES = 120   # Hard cap per study day (configurable at the module level)

SYSTEM_ROADMAP = (SHARED / "prompts" / "system_roadmap.txt").read_text(encoding="utf-8")
SYSTEM_QUIZ = (SHARED / "prompts" / "system_quiz.txt").read_text(encoding="utf-8")


class ValidationError(ValueError):
    pass


def extract_json(text):
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    a, b = t.find("{"), t.rfind("}")
    if a == -1 or b <= a:
        raise ValidationError("no JSON object found")
    json_str = t[a:b + 1]
    # Remove trailing commas before closing braces/brackets (common model syntax flaw)
    clean_str = re.sub(r",\s*([}\]])", r"\1", json_str)
    try:
        return json.loads(clean_str)
    except json.JSONDecodeError as e:
        raise ValidationError(f"invalid JSON: {e}")


def parse_minutes(mins):
    """Safely parse numeric minute values. Reject ambiguous, non-positive, or non-finite values."""
    if isinstance(mins, bool) or mins is None:
        raise ValidationError("'minutes' must be a positive, finite number")
    if isinstance(mins, (int, float)):
        if not math.isfinite(mins) or mins <= 0:
            raise ValidationError("'minutes' must be a positive, finite number")
        return float(mins)
    if isinstance(mins, str):
        s = mins.strip().lower()
        if not s:
            raise ValidationError("'minutes' must be a positive, finite number")
        # Hours: e.g. "1.5 hours", "2 hrs", "1 hour", "1.5 h"
        m_hr = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)", s)
        if m_hr:
            val = float(m_hr.group(1)) * 60.0
            if math.isfinite(val) and val > 0:
                return val
            raise ValidationError("'minutes' must be a positive, finite number")
        # Minutes: e.g. "60", "60 mins", "60 min", "60 minutes", "60 m"
        m_min = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:minutes?|mins?|m)?", s)
        if m_min:
            val = float(m_min.group(1))
            if math.isfinite(val) and val > 0:
                return val
            raise ValidationError("'minutes' must be a positive, finite number")
    raise ValidationError("'minutes' must be a positive, finite number")


GENERIC_MILESTONE_EXACT = {
    "complete week", "complete the week", "finish week", "finish the week",
    "complete topics", "complete the topics", "finish topics", "finish the topics",
    "finish all topics", "study scheduled material", "study material", "study the material",
    "study topics", "complete all tasks", "complete tasks", "finish tasks",
    "weekly milestone", "milestone", "goal", "tbd", "na", "n/a", "none",
    "complete the listed topics", "finish the listed topics",
}

GENERIC_MILESTONE_PATTERNS = [
    r"^(?:complete|finish|study|review|learn|cover)\s+(?:all\s+)?(?:the\s+)?(?:week|topics?|tasks?|material|scheduled material|content)(?:\s+\d+)?\.?$",
    r"^(?:week\s+\d+\s+milestone|weekly\s+milestone|milestone|goal|tbd|n/a|none)\.?$",
    r"^(?:complete|finish)\s+week(?:\s+\d+)?\.?$",
]


def is_generic_milestone(text):
    clean = re.sub(r"[^\w\s]", "", (text or "").strip().lower())
    if clean in GENERIC_MILESTONE_EXACT:
        return True
    for pat in GENERIC_MILESTONE_PATTERNS:
        if re.match(pat, (text or "").strip().lower()):
            return True
    words = clean.split()
    if len(words) <= 2 and any(w in words for w in ("complete", "finish", "week", "milestone")):
        return True
    return False


def milestone_reflects_focus(ms, focus_items, node_names=None, node_resources=None, tasks=None):
    """Check whether an English milestone reflects the scheduled focus topics, resources, or tasks.

    Uses exact match, prefix match, and 5-character stem match to handle morphological variants
    (e.g. 'statistical' matching 'statistics', 'optimization' matching 'optimize').
    """
    ms_tokens = set(re.findall(r"\b[a-zA-Z]{3,}\b", ms.lower()))
    STOP_WORDS = {
        "the", "and", "for", "with", "from", "without", "that", "this", "week", "will", "able",
        "can", "build", "practice", "study", "learn", "understand", "solve", "create", "using",
        "write", "read", "goal", "part", "session", "exercises", "concepts",
    }
    ms_substantive = ms_tokens - STOP_WORDS
    if not ms_substantive:
        return True

    focus_tokens = set()
    for it in focus_items:
        nid = it["node"]
        focus_tokens.update(nid.split("_"))
        if node_names and nid in node_names:
            focus_tokens.update(re.findall(r"\b[a-zA-Z]{3,}\b", node_names[nid].lower()))
        if node_resources and nid in node_resources:
            for r in node_resources[nid]:
                focus_tokens.update(re.findall(r"\b[a-zA-Z]{3,}\b", r.lower()))
    if tasks:
        for t in tasks:
            task_text = t.get("task") or t.get("description") or ""
            focus_tokens.update(re.findall(r"\b[a-zA-Z]{3,}\b", task_text.lower()))

    focus_substantive = focus_tokens - STOP_WORDS

    _STEM_LEN = 5
    for m in ms_substantive:
        for f in focus_substantive:
            if m == f or m.startswith(f) or f.startswith(m):
                return True
            # Morphological stem check: e.g. 'statistical' and 'statistics' share 'stati'
            if len(m) >= _STEM_LEN and len(f) >= _STEM_LEN and m[:_STEM_LEN] == f[:_STEM_LEN]:
                return True
    return False


def redistribute_tasks(tasks, budget_minutes, max_daily=None):
    """Deterministically redistribute tasks so no day exceeds *max_daily* minutes.

    Rules:
    - Each task is split into sub-tasks of at most *max_daily* minutes where needed.
    - Sub-tasks inherit the parent task's ``node``, ``resource``, and task text.
    - The total study minutes is preserved exactly (equals *budget_minutes*).
    - Node and resource associations are preserved per sub-task.
    - Days are numbered 1 to 7; at most 7 days are used.
    - Minimum task fragment size is 5 minutes.
    - Preserves existing reasonable schedules when no day exceeds *max_daily*.
    - Packs tasks sequentially into days to preserve curriculum learning sequence
      and avoid excessive fragmentation into tiny tasks.

    Returns a new task list (sorted by day). Raises ``ValidationError`` if the
    weekly budget cannot be satisfied within 7 days under the daily cap.
    """
    if max_daily is None:
        max_daily = MAX_DAILY_MINUTES

    if not tasks:
        return []

    # Check whether redistribution is even needed
    already_ok = True
    day_load = {}
    for t in tasks:
        d = t.get("day")
        m = t.get("minutes", 0)
        if not (isinstance(d, int) and not isinstance(d, bool) and 1 <= d <= 7):
            already_ok = False
            break
        if m > max_daily:
            already_ok = False
            break
        day_load[d] = day_load.get(d, 0) + m

    if already_ok:
        for d, load in day_load.items():
            if load > max_daily:
                already_ok = False
                break

    if already_ok:
        return sorted(tasks, key=lambda t: t["day"])

    # --- Redistribution required ---
    # First, split any single task that exceeds max_daily into sub-tasks
    chunks = []
    for t in tasks:
        mins = t["minutes"]
        while mins > max_daily:
            take = max_daily
            if 0 < mins - take < 5:
                take = mins - 5
            chunks.append({**t, "minutes": int(take)})
            mins -= take
        if mins > 0:
            chunks.append({**t, "minutes": int(mins)})

    # Verify capacity: 7 days * max_daily >= total
    total_chunks = sum(c["minutes"] for c in chunks)
    max_capacity = 7 * max_daily
    if total_chunks > max_capacity:
        raise ValidationError(
            f"weekly budget {total_chunks} min exceeds maximum capacity of 7 days "
            f"({max_capacity} min = 7 × {max_daily} min/day)"
        )

    # Assign chunks to days greedily
    assigned = []
    cur_day = 1
    cur_day_mins = 0

    for idx, chunk in enumerate(chunks):
        cmins = chunk["minutes"]
        # Check if chunk fits on cur_day
        if cur_day_mins + cmins <= max_daily:
            assigned.append({**chunk, "day": cur_day})
            cur_day_mins += cmins
        else:
            # Check remaining budget against remaining days capacity
            rem_budget = sum(c["minutes"] for c in chunks[idx:])
            rem_days_capacity = (7 - cur_day) * max_daily
            room_on_cur_day = max_daily - cur_day_mins

            if cur_day_mins > 0 and rem_budget > rem_days_capacity and room_on_cur_day >= 5:
                # Need to use leftover room on cur_day to fit in 7 days
                take = room_on_cur_day
                if 0 < cmins - take < 5:
                    take = cmins - 5
                if take >= 5:
                    assigned.append({**chunk, "day": cur_day, "minutes": take})
                    cmins -= take
                cur_day += 1
                cur_day_mins = 0
            elif cur_day_mins > 0:
                cur_day += 1
                cur_day_mins = 0

            if cur_day > 7:
                raise ValidationError(
                    f"workload redistribution requires more than 7 days "
                    f"(budget {total_chunks} min, cap {max_daily} min/day)"
                )

            assigned.append({**chunk, "day": cur_day, "minutes": cmins})
            cur_day_mins += cmins

    assigned.sort(key=lambda t: t["day"])
    return assigned


def validate_workload(tasks, budget_minutes, max_daily=None, focus_items=None, node_resources=None, original_tasks=None):
    """Validate that tasks satisfy workload constraints; raise ``ValidationError`` if not."""
    if max_daily is None:
        max_daily = MAX_DAILY_MINUTES

    if not isinstance(tasks, list):
        raise ValidationError("workload validation: tasks must be a list")

    total = sum(t.get("minutes", 0) for t in tasks)
    if abs(total - budget_minutes) > 0.5:
        raise ValidationError(
            f"workload validation: task minutes total {total} != weekly budget {budget_minutes}"
        )

    day_load = {}
    for t in tasks:
        d = t.get("day")
        if not (isinstance(d, int) and not isinstance(d, bool) and 1 <= d <= 7):
            raise ValidationError(f"workload validation: invalid day {d!r}")
        m = t.get("minutes", 0)
        if not (isinstance(m, (int, float)) and m >= 5):
            raise ValidationError(f"workload validation: task minutes must be >= 5, got {m!r}")
        if m > max_daily:
            raise ValidationError(f"workload validation: task duration {m} exceeds daily cap {max_daily}")
        day_load[d] = day_load.get(d, 0) + m

    for d, load in day_load.items():
        if load > max_daily:
            raise ValidationError(
                f"workload validation: day {d} has {load} min which exceeds daily cap {max_daily} min"
            )

    # Validate topic and resource preservation if provided
    if focus_items is not None:
        focus_nodes = {it["node"] for it in focus_items}
        covered = {t.get("node") for t in tasks}
        missing = focus_nodes - covered
        if missing:
            raise ValidationError(f"workload validation: missing focus topic(s) after redistribution: {sorted(missing)}")
        for t in tasks:
            node = t.get("node")
            if node not in focus_nodes:
                raise ValidationError(f"workload validation: unexpected node '{node}' after redistribution")
            if node_resources and node in node_resources:
                valid_res = node_resources[node]
                res = t.get("resource")
                if res not in valid_res:
                    raise ValidationError(
                        f"workload validation: invalid resource '{res}' for node '{node}' after redistribution. Allowed: {valid_res}"
                    )

    # Validate that no topic lost minutes during redistribution if original tasks given
    if original_tasks is not None and focus_items is not None:
        orig_node_mins = {}
        for t in original_tasks:
            n = t.get("node")
            if n:
                orig_node_mins[n] = orig_node_mins.get(n, 0) + t.get("minutes", 0)
        new_node_mins = {}
        for t in tasks:
            n = t.get("node")
            if n:
                new_node_mins[n] = new_node_mins.get(n, 0) + t.get("minutes", 0)
        for n, orig_m in orig_node_mins.items():
            new_m = new_node_mins.get(n, 0)
            if abs(new_m - orig_m) > 5:
                raise ValidationError(
                    f"workload validation: node '{n}' minutes changed from {orig_m} to {new_m} during redistribution"
                )


def validate_week(obj, budget_minutes, allowed, focus_items=None, node_resources=None, node_names=None, prior_milestone=None, lang="en"):
    """Strict schema check + deterministic clean-up (topic-resource binding, mandatory coverage, minutes rescaled)."""
    if not isinstance(obj, dict):
        raise ValidationError("top level must be an object")
    norm = {k.strip().lower(): v for k, v in obj.items() if isinstance(k, str)}
    title = obj.get("title") if "title" in obj else norm.get("title")
    ms = obj.get("milestone") if "milestone" in obj else norm.get("milestone")
    tasks = obj.get("tasks") if "tasks" in obj else norm.get("tasks")

    if ms is None:
        ms = norm.get("weekly_milestone") or norm.get("milestone_goal") or norm.get("goal") or norm.get("project")
    if title is None:
        title = norm.get("week_title") or norm.get("topic")

    if isinstance(ms, list):
        ms = " ".join(str(x).strip() for x in ms if str(x).strip())
    if not isinstance(title, str) or not title.strip():
        raise ValidationError("missing 'title'")
    if not isinstance(ms, str) or not ms.strip():
        raise ValidationError("missing 'milestone'")
    if is_generic_milestone(ms):
        raise ValidationError(f"generic placeholder milestone '{ms}' is not acceptable; describe a concrete, measurable learning outcome")
    if prior_milestone and ms.strip().lower() == prior_milestone.strip().lower():
        raise ValidationError("milestone cannot be identical to the previous week's milestone; describe the specific outcome for this week's topics")
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 14:
        raise ValidationError("'tasks' must be a list of 1-14 items")

    focus_node_ids = set()
    if focus_items is not None:
        focus_node_ids = {it["node"] for it in focus_items}

    clean = []
    covered_nodes = set()
    for t in tasks:
        if not isinstance(t, dict):
            raise ValidationError("each task must be an object")
        text = t.get("task") or t.get("description") or t.get("activity")
        mins_raw = t.get("minutes") if "minutes" in t else t.get("mins") if "mins" in t else t.get("duration")
        res = (t.get("resource") or t.get("resource_name") or "").strip()
        day = t.get("day")
        if isinstance(day, str) and day.strip().isdigit():
            day = int(day.strip())
        if not (isinstance(day, int) and not isinstance(day, bool) and 1 <= day <= 7):
            raise ValidationError("'day' must be an integer 1-7")
        if not isinstance(text, str) or not text.strip():
            raise ValidationError("task text missing")
        mins = parse_minutes(mins_raw)

        node = t.get("node") or t.get("node_id") or t.get("skill")
        if focus_items is not None:
            if not isinstance(node, str) or not node.strip():
                raise ValidationError("task missing 'node'")
            node = node.strip()
            if node not in focus_node_ids:
                raise ValidationError(f"task node '{node}' is not in current week's focus topics: {sorted(focus_node_ids)}")
            covered_nodes.add(node)

        # Resource validation
        if node_resources is not None and node is not None:
            valid_res = node_resources.get(node, [])
            if not res:
                raise ValidationError(f"task for node '{node}' missing 'resource'")
            ci_map = {r.lower().strip(): r for r in valid_res}
            if res in valid_res:
                matched_res = res
            elif res.lower().strip() in ci_map:
                matched_res = ci_map[res.lower().strip()]
            else:
                all_allowed_ci = {a.lower().strip(): a for a in (allowed or [])}
                if res.lower().strip() in all_allowed_ci:
                    raise ValidationError(f"task for node '{node}' used resource '{res}' which belongs to a different topic. Allowed resources for '{node}': {valid_res}")
                raise ValidationError(f"resource '{res}' is not an allowed resource for node '{node}'. Allowed: {valid_res}")
        elif allowed:
            matched_res = res if res in allowed else allowed[0]
        else:
            matched_res = res

        clean_task = {"day": day}
        if node is not None:
            clean_task["node"] = node
        clean_task["task"] = text.strip()
        clean_task["minutes"] = mins
        clean_task["resource"] = matched_res or ""
        clean.append(clean_task)

    if focus_items is not None:
        missing = [it["node"] for it in focus_items if it["node"] not in covered_nodes]
        if missing:
            missing_names = [node_names.get(m, m) if node_names else m for m in missing]
            names_str = ", ".join(missing_names)
            ids_str = ", ".join(missing)
            raise ValidationError(f"missing tasks for scheduled focus topic(s): {names_str} ({ids_str})")

    if focus_items is not None and lang == "en":
        if not milestone_reflects_focus(ms, focus_items, node_names, node_resources, clean):
            scheduled = [it["node"] for it in focus_items]
            raise ValidationError(f"milestone '{ms}' does not reflect current week's focus topic(s): {', '.join(scheduled)}")

    scale = budget_minutes / sum(t["minutes"] for t in clean)
    for t in clean:
        t["minutes"] = max(5, int(round(t["minutes"] * scale / 5)) * 5)
    # Correct any rounding drift so total exactly equals budget (adjust last task)
    drift = sum(t["minutes"] for t in clean) - budget_minutes
    if drift != 0 and clean:
        clean[-1]["minutes"] = max(5, clean[-1]["minutes"] - drift)
    # M2.2C: Deterministic workload redistribution — enforce daily cap
    orig_clean = [dict(t) for t in clean]
    clean = redistribute_tasks(clean, budget_minutes)
    validate_workload(
        clean,
        budget_minutes,
        focus_items=focus_items,
        node_resources=node_resources,
        original_tasks=orig_clean,
    )
    return {"title": title.strip(), "milestone": ms.strip(), "tasks": clean}


FALLBACK_TEMPLATES = {
    "en": {
        "title": "Week {week}: {names}",
        "study": "Study {name}",
        "revise": "Revise {name}",
        "milestone": "Finish the listed topics and note one question for each",
    },
    "hi": {
        "title": "सप्ताह {week}: {names}",
        "study": "{name} का अध्ययन करें",
        "revise": "{name} का दोहराव करें",
        "milestone": "सूचीबद्ध विषयों को पूरा करें और प्रत्येक के लिए एक प्रश्न नोट करें",
    },
    "mr": {
        "title": "आठवडा {week}: {names}",
        "study": "{name} चा अभ्यास करा",
        "revise": "{name} ची उजळणी करा",
        "milestone": "दिलेले विषय पूर्ण करा आणि प्रत्येकासाठी एक प्रश्न नोंदवा",
    },
    "ta": {
        "title": "வாரம் {week}: {names}",
        "study": "{name} கற்க",
        "revise": "{name} திருப்புதல் செய்க",
        "milestone": "பட்டியலிடப்பட்ட தலைப்புகளை முடித்து ஒவ்வொன்றிற்கும் ஒரு குறிப்பை எழுதவும்",
    },
    "te": {
        "title": "వారం {week}: {names}",
        "study": "{name} అధ్యయనం చేయండి",
        "revise": "{name} పునశ్చరణ చేయండి",
        "milestone": "జాబితా చేయబడిన అంశాలను పూర్తి చేసి ప్రతిదానికి ఒక ప్రశ్న రాయండి",
    },
    "bn": {
        "title": "সপ্তাহ {week}: {names}",
        "study": "{name} অধ্যয়ন করুন",
        "revise": "{name} পুনরাবৃত্তি করুন",
        "milestone": "তালিকাভুক্ত বিষয়গুলি শেষ করুন এবং প্রতিটির জন্য একটি প্রশ্ন লিখুন",
    },
}


def template_week(week, nodes, lang="en"):
    """Deterministic fallback week localized to the requested language so the app never crashes.

    M2.2C: Sessions are sized to respect MAX_DAILY_MINUTES; redistribute_tasks enforces the cap.
    """
    tmpl = FALLBACK_TEMPLATES.get(lang, FALLBACK_TEMPLATES["en"])
    tasks, k = [], 0
    budget = int(round(sum(it["hours"] for it in week["items"]) * 60))
    for it in week["items"]:
        n = nodes[it["node"]]
        total = round(it["hours"] * 60)
        # Size sessions so each fits within the daily cap (at most MAX_DAILY_MINUTES)
        sessions = max(1, math.ceil(total / MAX_DAILY_MINUTES))
        per_session = int(round(total / sessions / 5)) * 5 or 5
        for s_idx in range(sessions):
            # Last session absorbs rounding remainder for this item
            if s_idx == sessions - 1:
                mins = max(5, total - per_session * s_idx)
            else:
                mins = per_session
            action = tmpl["revise"] if it["revision"] else tmpl["study"]
            tasks.append({
                "day": k % 5 + 1,
                "node": it["node"],
                "task": action.format(name=n["name"]),
                "minutes": mins,
                "resource": n["resources"][0],
            })
            k += 1
    # Correct any rounding drift so total exactly equals budget (adjust last task)
    drift = sum(t["minutes"] for t in tasks) - budget
    if drift != 0 and tasks:
        tasks[-1]["minutes"] = max(5, tasks[-1]["minutes"] - drift)
    # Apply deterministic redistribution to enforce daily cap
    orig_tasks = [dict(t) for t in tasks]
    tasks = redistribute_tasks(tasks, budget)
    validate_workload(
        tasks,
        budget,
        focus_items=week["items"],
        node_resources={it["node"]: list(nodes[it["node"]]["resources"]) for it in week["items"]},
        original_tasks=orig_tasks,
    )
    names = ", ".join(nodes[i["node"]]["name"] for i in week["items"])
    return {
        "title": tmpl["title"].format(week=week["week"], names=names),
        "milestone": tmpl["milestone"],
        "tasks": tasks,
    }


def fill_week(llm, graph, week, meta, attempts=2, prior_context=None, prior_summary=None, prior_milestone=None):
    nodes = {n["id"]: n for n in graph["nodes"]}
    lang = meta["language"]
    allowed = []
    for it in week["items"]:
        for r in nodes[it["node"]]["resources"]:
            if r not in allowed:
                allowed.append(r)
    budget = int(round(sum(i["hours"] for i in week["items"]) * 60))
    focus = []
    for i in week["items"]:
        f_item = {
            "node": i["node"],
            "name": nodes[i["node"]]["name"],
            "hours": i["hours"],
            "revision": i["revision"],
        }
        if "part" in i:
            f_item["part"] = i["part"]
            f_item["total_parts"] = i["total_parts"]
            f_item["cumulative_hours_start"] = i["cumulative_hours_start"]
            f_item["cumulative_hours_end"] = i["cumulative_hours_end"]
            f_item["node_total_hours"] = i["node_total_hours"]
        f_item["allowed_resources"] = list(nodes[i["node"]]["resources"])
        focus.append(f_item)
    payload = {
        "task": "fill_week",
        "language": lang,
        "goal": meta["goal"],
        "week": week["week"],
        "weekly_hours": meta["weekly_hours"],
        "focus": focus,
        "allowed_resources": allowed,
    }
    # Planner-derived previous week context (never use LLM-generated milestone/title)
    ctx = prior_context or prior_summary
    if ctx and isinstance(ctx, dict):
        payload["previous_week"] = {
            "week": ctx.get("week"),
            "nodes": ctx.get("nodes", []),
        }
    messages = [{"role": "system", "content": SYSTEM_ROADMAP.replace("{LANGUAGE_NAME}", LANG_NAMES[lang])},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
    node_resources = {it["node"]: list(nodes[it["node"]]["resources"]) for it in week["items"]}
    node_names = {it["node"]: nodes[it["node"]]["name"] for it in week["items"]}
    err = None
    for attempt in range(1, attempts + 1):
        raw = ""
        try:
            raw = llm.chat(messages)
            data = validate_week(
                extract_json(raw),
                budget,
                allowed,
                focus_items=week["items"],
                node_resources=node_resources,
                node_names=node_names,
                prior_milestone=prior_milestone,
                lang=lang,
            )
            text = " ".join([data["title"], data["milestone"]] + [t["task"] for t in data["tasks"]])
            for term in sorted([n["name"] for n in nodes.values()] + allowed, key=len, reverse=True):
                text = text.replace(term, " ")  # English topic names / resource titles are allowed technical terms
            if not script_ok(text, lang):
                raise ValidationError(f"all text values must be written only in {LANG_NAMES[lang]}")
            return {**week, **data, "source": "llm", "attempts": attempt}
        except ValidationError as e:
            err = e
            # Do NOT reinforce broken output by appending malformed raw text.
            # Give clear corrective instruction with schema and topic-resource reminder.
            focus_nodes = [it["node"] for it in week["items"]]
            node_specs = []
            for it in week["items"]:
                nid = it["node"]
                nname = nodes[nid]["name"]
                res_list = [f'"{r}"' for r in nodes[nid]["resources"]]
                node_specs.append(f"- node '{nid}' ({nname}): [{', '.join(res_list)}]")
            specs_text = "; ".join(node_specs)
            names_title = " and ".join(nodes[it["node"]]["name"] for it in week["items"])

            if len(focus_nodes) == 1:
                node_instruction = f"The ONLY permitted value for \"node\" in EVERY task this week is '{focus_nodes[0]}'. Do NOT use previous topics or any other node name."
            else:
                allowed_str = ", ".join(f"'{n}'" for n in focus_nodes)
                node_instruction = f"The ONLY permitted values for \"node\" are [{allowed_str}]. You MUST assign at least one task to EACH scheduled topic node: {specs_text}."

            week_label = {"en": "Week", "hi": "सप्ताह", "mr": "आठवडा", "ta": "வாரம்", "te": "వారం", "bn": "সপ্তাহ"}.get(lang, "Week")
            title_prefix = f'{week_label} {week["week"]}: {names_title}'

            messages = [
                messages[0],
                messages[1],
                {"role": "assistant", "content": "I understand the JSON formatting, schema, and topic-resource binding requirements."},
                {"role": "user", "content": (
                    f"Your previous output failed validation: {e}.\n"
                    "Return ONLY a single valid JSON object.\n"
                    'Schema: {"title": string, "milestone": string, "tasks": [{"day": 1-7, "node": string, "task": string, "minutes": integer, "resource": string}]}\n'
                    f'Start with "title": "{title_prefix}".\n'
                    f"{node_instruction}\n"
                    f"Ensure every task's 'node' is valid, 'resource' is copied from that node's allowed resources, 'milestone' is a concrete outcome, and all text is written in {LANG_NAMES[lang]} (no English explanations)."
                )},
            ]
        except Exception as e:  # backend failure (model not loaded, server down...)
            err = e
            return {**week, **template_week(week, nodes, lang), "source": "fallback", "attempts": attempt, "error": str(err)}
    return {**week, **template_week(week, nodes, lang), "source": "fallback", "attempts": attempts, "error": str(err)}


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
    weeks = []
    prior_context = None
    prior_milestone = None
    for w in pack(queue, weekly_hours):
        filled = fill_week(llm, graph, w, meta, prior_context=prior_context, prior_milestone=prior_milestone)
        weeks.append(filled)
        prior_milestone = filled.get("milestone")
        prior_context = {
            "week": w["week"],
            "nodes": [
                {
                    "node": it["node"],
                    "part": it.get("part", 1),
                    "total_parts": it.get("total_parts", 1),
                    "hours_completed": it.get("cumulative_hours_end", it["hours"]),
                }
                for it in w["items"]
            ],
        }
    return {**meta, "weeks": weeks}


def generate_adaptation_feedback(llm, plan, adaptation_record, lang="en"):
    """Use Llama to produce personalized encouraging feedback explaining the adaptation in the learner's language."""
    if not llm:
        return None
    if getattr(llm, "family", None) == "mock" or "Mock" in getattr(llm, "model_id", ""):
        act = adaptation_record.get("action", "updated")
        sc = adaptation_record.get("score")
        hours_str = ""
        if "new_weekly_hours" in adaptation_record:
            hours_str = f" Weekly study time updated to {adaptation_record['new_weekly_hours']:.1f}h/week."
        if sc is not None and sc >= 0.8:
            return f"Great progress! You demonstrated mastery with {sc:.0%} on Week {adaptation_record['week']}.{hours_str}"
        elif sc is not None and sc < 0.6:
            return f"Keep going! Review sessions have been scheduled for Week {adaptation_record['week']}'s topics.{hours_str}"
        return f"Study plan adapted successfully ({act}).{hours_str}"

    prompt = {
        "role": "user",
        "content": (
            f"The learner's study plan in {LANG_NAMES.get(lang, 'English')} for goal '{plan.get('goal')}' was adapted. "
            f"Week {adaptation_record['week']} adaptation action: '{adaptation_record.get('action')}'. "
            f"Score: {adaptation_record.get('score')}. "
            f"Write 1-2 encouraging, motivating feedback sentences in {LANG_NAMES.get(lang, 'English')} to guide the learner."
        )
    }
    try:
        res = llm.chat([
            {"role": "system", "content": f"You are an encouraging learning companion tutor. Respond in {LANG_NAMES.get(lang, 'English')}."},
            prompt
        ])
        return res.strip()
    except Exception:
        return None


def adapt_plan(llm, plan, week_no, score=None, completed_tasks=None, new_weekly_hours=None, thresholds=None):
    """Deterministically re-plan later weeks based on quiz performance, task completions, and availability changes.

    - score: optional 0..1 quiz score.
    - completed_tasks: optional list/set of task indices completed in week_no.
    - new_weekly_hours: optional new weekly study availability.
    - thresholds: optional dict e.g. {"mastery": 0.80, "reinforce": 0.60}.
    """
    weeks = plan["weeks"]
    if not weeks:
        raise ValueError("this plan has no weeks to adapt (all skills were already known)")
    if score is not None:
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise ValueError(f"score must be a finite number between 0 and 1, got {score!r}")
    if not 1 <= week_no <= len(weeks):
        raise ValueError(f"week must be 1..{len(weeks)}")
    if any("score" not in w for w in weeks[:week_no - 1]):
        raise ValueError("record the quiz for earlier weeks first (weeks are adapted in order)")
    if score is not None and "score" in weeks[week_no - 1]:
        raise ValueError(f"week {week_no} already has a recorded score")

    if new_weekly_hours is not None:
        plan["weekly_hours"] = validate_hours(new_weekly_hours)

    graph = load_graph(plan["domain"])
    done = [dict(w) for w in weeks[:week_no]]
    if score is not None:
        done[-1]["score"] = score

    # Track task completions
    incomplete_items = None
    if completed_tasks is not None:
        tasks = done[-1].get("tasks", [])
        for idx, t in enumerate(tasks):
            t["completed"] = (idx in completed_tasks) if isinstance(completed_tasks, (list, set, tuple)) else bool(t.get("completed", False))

        incomp_by_node = {}
        for t in tasks:
            if not t.get("completed", False):
                nid = t.get("node")
                if nid:
                    incomp_by_node[nid] = incomp_by_node.get(nid, 0) + t.get("minutes", 0)
        incomplete_items = [{"node": n, "hours": round(m / 60.0, 2)} for n, m in incomp_by_node.items() if m > 0]

    # Track weak skills
    if score is not None and score < 0.60:
        weak_skills = dict(plan.get("weak_skills", {}))
        for it in done[-1].get("items", []):
            weak_skills[it["node"]] = score
        plan["weak_skills"] = weak_skills

    queue, action = adapt_queue(
        done[-1]["items"],
        remaining_queue(weeks[week_no:]),
        score=score,
        thresholds=thresholds,
        incomplete_items=incomplete_items,
        graph=graph,
        prior_adaptations=plan.get("adaptations", []),
    )

    # Reflect availability change in action label
    if new_weekly_hours is not None:
        if score is None:
            action = "availability_updated"
        else:
            action = f"{action}_hours_updated"

    prior_milestone = done[-1].get("milestone") if done else None
    prior_context = {
        "week": done[-1].get("week", week_no),
        "nodes": [
            {
                "node": it["node"],
                "part": it.get("part", 1),
                "total_parts": it.get("total_parts", 1),
                "hours_completed": it.get("cumulative_hours_end", it["hours"]),
            }
            for it in done[-1].get("items", [])
        ],
    }
    new = []
    for w in pack(queue, plan["weekly_hours"], start_week=week_no + 1):
        filled = fill_week(llm, graph, w, plan, prior_context=prior_context, prior_milestone=prior_milestone)
        new.append(filled)
        prior_milestone = filled.get("milestone")
        prior_context = {
            "week": w["week"],
            "nodes": [
                {
                    "node": it["node"],
                    "part": it.get("part", 1),
                    "total_parts": it.get("total_parts", 1),
                    "hours_completed": it.get("cumulative_hours_end", it["hours"]),
                }
                for it in w["items"]
            ],
        }

    adaptation_record = {"week": week_no, "action": action}
    if score is not None:
        adaptation_record["score"] = score
        if score >= 0.80:
            adaptation_record["mastered_nodes"] = [it["node"] for it in done[-1].get("items", [])]
        elif score < 0.60:
            adaptation_record["revised_nodes"] = [it["node"] for it in done[-1].get("items", [])]
    if new_weekly_hours is not None:
        adaptation_record["new_weekly_hours"] = new_weekly_hours
    if completed_tasks is not None:
        adaptation_record["completed_task_indices"] = list(completed_tasks)
        if incomplete_items:
            adaptation_record["incomplete_carried_forward"] = incomplete_items

    feedback = generate_adaptation_feedback(llm, plan, adaptation_record, lang=plan.get("language", "en"))
    if feedback:
        adaptation_record["feedback"] = feedback

    return {**plan, "weeks": done + new,
            "adaptations": plan.get("adaptations", []) + [adaptation_record]}


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
