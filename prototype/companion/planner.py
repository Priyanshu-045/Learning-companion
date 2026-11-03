"""Pure, deterministic planning: skill graph -> gaps -> weekly schedule -> adaptation."""
import json
import pathlib

SHARED = pathlib.Path(__file__).resolve().parents[2] / "shared"
EPS = 0.01


def list_domains():
    return sorted(p.stem for p in (SHARED / "skill_graphs").glob("*.json"))


def load_graph(domain):
    path = SHARED / "skill_graphs" / f"{domain}.json"
    if not path.exists():
        raise ValueError(f"unknown domain '{domain}'. Available: {', '.join(list_domains())}")
    return json.loads(path.read_text(encoding="utf-8"))


def topo_order(graph):
    nodes = {n["id"]: n for n in graph["nodes"]}
    order, seen = [], set()

    def visit(i, stack=()):
        if i in seen:
            return
        if i in stack:
            raise ValueError(f"cycle in skill graph at '{i}'")
        for p in nodes[i]["prereqs"]:
            visit(p, stack + (i,))
        seen.add(i)
        order.append(i)

    for n in graph["nodes"]:
        visit(n["id"])
    return order


def find_gaps(graph, known):
    known = set(known)
    return [i for i in topo_order(graph) if i not in known]


def known_from_quiz(graph, scores, threshold=0.6):
    """scores: {node_id: 0..1}. Nodes at/above threshold count as known."""
    return [n for n, s in scores.items() if s >= threshold]


def pack(queue, weekly_hours, start_week=1):
    """Pack queue items [{'node','hours','revision'}] into weeks; long items span weeks."""
    weeks, cur, room, week = [], [], float(weekly_hours), start_week
    for item in queue:
        left = float(item["hours"])
        while left > EPS:
            take = min(left, room)
            cur.append({"node": item["node"], "hours": round(take, 2),
                        "revision": bool(item.get("revision", False))})
            left -= take
            room -= take
            if room < EPS:
                weeks.append({"week": week, "items": cur})
                week, cur, room = week + 1, [], float(weekly_hours)
    if cur:
        weeks.append({"week": week, "items": cur})
    return weeks


def remaining_queue(weeks):
    """Re-merge items of not-yet-done weeks back into a queue."""
    queue = []
    for w in weeks:
        for it in w["items"]:
            if queue and queue[-1]["node"] == it["node"] and queue[-1]["revision"] == it["revision"]:
                queue[-1]["hours"] = round(queue[-1]["hours"] + it["hours"], 2)
            else:
                queue.append(dict(it))
    return queue


def adapt_queue(week_items, remaining, score, low=0.5, high=0.85):
    """Deterministic adaptation rules. Returns (new_queue, action)."""
    remaining = [dict(i) for i in remaining]
    if score < low:
        revs = [{"node": i["node"], "hours": max(1.0, round(i["hours"] * 0.5, 1)), "revision": True}
                for i in week_items if not i["revision"]]
        if revs:
            return revs + remaining, "revision_added"
    elif score >= high:
        for i in remaining:
            if not i["revision"]:
                i["hours"] = max(1.0, round(i["hours"] * 0.75, 1))
                return remaining, "accelerated"
    return remaining, "unchanged"
