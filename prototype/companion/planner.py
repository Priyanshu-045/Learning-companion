"""Pure, deterministic planning: skill graph -> gaps -> weekly schedule -> adaptation."""
import json
import math
import pathlib

SHARED = pathlib.Path(__file__).resolve().parents[2] / "shared"
EPS = 0.01
MAX_WEEKLY_HOURS = 100


def validate_hours(h):
    """Weekly study hours must be a finite number in (0, 100]. (0 or negative used to hang pack() forever.)"""
    if isinstance(h, bool) or not isinstance(h, (int, float)) or h != h or h in (float("inf"), float("-inf")):
        raise ValueError(f"weekly hours must be a number, got {h!r}")
    if not 0 < h <= MAX_WEEKLY_HOURS:
        raise ValueError(f"weekly hours must be between 0 and {MAX_WEEKLY_HOURS}, got {h}")
    return float(h)


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
    weekly_hours = validate_hours(weekly_hours)
    weeks, cur, room, week = [], [], weekly_hours, start_week
    for item in queue:
        left = float(item["hours"])
        total_hours = left
        if total_hours <= room + EPS:
            total_parts = 1
        else:
            rem = total_hours - room
            total_parts = 1 + math.ceil((rem - EPS) / weekly_hours)
        part = 1
        cum_start = 0.0
        while left > EPS:
            take = min(left, room)
            cum_end = round(cum_start + take, 2)
            packed_item = {
                "node": item["node"],
                "hours": round(take, 2),
                "revision": bool(item.get("revision", False)),
                "part": part,
                "total_parts": total_parts,
                "node_total_hours": round(total_hours, 2),
                "cumulative_hours_start": round(cum_start, 2),
                "cumulative_hours_end": round(cum_end, 2),
            }
            for extra in ("reinforce", "carried_forward", "prereq_reinforce"):
                if extra in item:
                    packed_item[extra] = item[extra]
            cur.append(packed_item)
            left -= take
            room -= take
            cum_start = cum_end
            part += 1
            if room < EPS:
                weeks.append({"week": week, "items": cur})
                week, cur, room = week + 1, [], weekly_hours
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


def adapt_queue(week_items, remaining, score=None, low=0.5, high=0.85,
                thresholds=None, incomplete_items=None, graph=None, prior_adaptations=None):
    """Deterministic adaptation rules with configurable mastery thresholds, prerequisite awareness,
    and incomplete task carry-forward.

    Mastery policy when thresholds given (e.g. thresholds={"mastery": 0.80, "reinforce": 0.60}):
    - score >= mastery: progression (or accelerated if score >= 0.90)
    - reinforce <= score < mastery: reinforce topic with targeted practice
    - score < reinforce: revision and prerequisite reinforcement before advancing

    Preserves exact backward compatibility with legacy calls (score, low, high).
    """
    remaining = [dict(i) for i in remaining]
    action = "unchanged"

    # 1. Carry forward incomplete work if provided
    carried = []
    if incomplete_items:
        for it in incomplete_items:
            carried.append({
                "node": it["node"],
                "hours": round(float(it["hours"]), 2),
                "revision": False,
                "carried_forward": True,
            })

    # If no score provided (e.g. hours or task-only update), return carried forward + remaining
    if score is None:
        return carried + remaining, "workload_updated" if (carried or incomplete_items is not None) else "unchanged"

    # Configure thresholds
    if thresholds is not None:
        mastery_th = thresholds.get("mastery", 0.80)
        reinforce_th = thresholds.get("reinforce", 0.60)
    else:
        # Backward-compatible default: use high and low
        mastery_th = high
        reinforce_th = low

    # Count prior revisions for these nodes to avoid infinite revision loops
    prior_rev_count = {}
    if prior_adaptations:
        for a in prior_adaptations:
            if a.get("action") in ("revision_added", "reinforced"):
                for n in a.get("revised_nodes", []):
                    prior_rev_count[n] = prior_rev_count.get(n, 0) + 1
            elif "mastery" in a.get("action", "") or a.get("action") == "accelerated":
                for n in a.get("mastered_nodes", []):
                    prior_rev_count.pop(n, None)

    revised_nodes = []

    # 2. Tier 1: High mastery (score >= mastery_th)
    if score >= mastery_th:
        if score >= 0.90:
            for i in remaining:
                if not i.get("revision"):
                    i["hours"] = max(1.0, round(i["hours"] * 0.75, 1))
                    action = "accelerated"
                    break
            else:
                action = "mastery_progression"
        else:
            action = "mastery_progression"

    # 3. Tier 2: Reinforce topic (reinforce_th <= score < mastery_th)
    elif thresholds is not None and score >= reinforce_th:
        reinforcements = []
        for i in week_items:
            nid = i["node"]
            # Avoid duplicate reinforcement if already queued
            if any(r.get("node") == nid and r.get("reinforce") for r in remaining):
                continue
            reinforce_hours = max(1.0, round(i["hours"] * 0.3, 1))
            reinforcements.append({
                "node": nid,
                "hours": reinforce_hours,
                "revision": True,
                "reinforce": True,
            })
            revised_nodes.append(nid)
        if reinforcements:
            action = "reinforced"
            return carried + reinforcements + remaining, action

    # 4. Tier 3: Low score (score < reinforce_th)
    elif score < (reinforce_th if thresholds is not None else low):
        revs = []
        for i in week_items:
            nid = i["node"]
            # Guard against infinite revision loop (cap at 2 revision cycles per topic)
            if prior_rev_count.get(nid, 0) >= 2:
                continue
            if any(r.get("node") == nid and r.get("revision") for r in remaining):
                continue

            # Foundational prerequisite review if graph available
            prereq_revs = []
            if graph:
                nodes_dict = {n["id"]: n for n in graph.get("nodes", [])}
                if nid in nodes_dict:
                    for p in nodes_dict[nid].get("prereqs", []):
                        if prior_rev_count.get(p, 0) == 0 and not any(r.get("node") == p for r in remaining):
                            prereq_revs.append({
                                "node": p,
                                "hours": 1.0,
                                "revision": True,
                                "prereq_reinforce": True,
                            })
                            revised_nodes.append(p)

            rev_hours = max(1.0, round(i["hours"] * 0.5, 1))
            revs.extend(prereq_revs)
            revs.append({"node": nid, "hours": rev_hours, "revision": True})
            revised_nodes.append(nid)

        if revs:
            action = "revision_added"
            return carried + revs + remaining, action

    return carried + remaining, action
