#!/usr/bin/env python3
"""Desktop prototype of the learning companion. Examples:
  python cli.py domains
  python cli.py plan --domain ml_engineer --hours 5 --known python_basics --prompt "Plan my ML career"
  python cli.py plan --domain data_analysis --hours 6 --prompt "मुझे 1 महीने का डेटा साइंस प्लान चाहिए"
  python cli.py quiz --topic "NumPy and Pandas" --lang hi
  python cli.py adapt --week 1 --score 0.4
  python cli.py show
Add --backend ollama (needs `ollama pull llama3.2:1b`) to use a real model."""
import argparse
import json
import pathlib
import sys

from companion.lang import detect_language, LANG_NAMES
from companion.llm import make_llm
from companion.planner import list_domains
from companion.roadmap import build_plan, adapt_plan, generate_quiz

STATE = pathlib.Path("companion_state.json")


def show(plan):
    print(f"\nGoal: {plan['goal']} | {plan['weekly_hours']} h/week | language: {LANG_NAMES[plan['language']]}")
    print(f"Skill gaps: {', '.join(plan['skill_gaps']) or 'none'}")
    for w in plan["weeks"]:
        tag = "" if w["source"] == "llm" else f"  [{w['source']}]"
        sc = f"  (quiz {w['score']:.0%})" if "score" in w else ""
        print(f"\n#{w['week']}  {w['title']}{sc}{tag}")
        for t in w["tasks"]:
            print(f"  Day {t['day']}  {t['minutes']:>3} min  {t['task']}  <{t['resource']}>")
        print(f"  Milestone: {w['milestone']}")
    for a in plan.get("adaptations", []):
        print(f"\nAdaptation: week {a['week']} scored {a['score']:.0%} -> {a['action']}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["domains", "plan", "adapt", "show", "quiz"])
    ap.add_argument("--domain", default="ml_engineer")
    ap.add_argument("--hours", type=float, default=5)
    ap.add_argument("--known", default="", help="comma-separated skill ids you already know")
    ap.add_argument("--prompt", default="", help="user's free text; used to detect language")
    ap.add_argument("--lang", choices=list(LANG_NAMES))
    ap.add_argument("--backend", default="mock", choices=["mock", "ollama", "llamacpp"])
    ap.add_argument("--model", help="ollama model name or path to .gguf")
    ap.add_argument("--week", type=int)
    ap.add_argument("--score", type=float, help="0..1")
    ap.add_argument("--topic")
    a = ap.parse_args(argv)

    if a.cmd == "domains":
        print("\n".join(list_domains()))
        return 0
    if a.cmd == "show":
        show(json.loads(STATE.read_text(encoding="utf-8")))
        return 0
    llm = make_llm(a.backend, a.model)
    if a.cmd == "plan":
        lang = a.lang or detect_language(a.prompt)
        known = [k for k in a.known.split(",") if k]
        plan = build_plan(llm, a.domain, a.hours, known, lang)
    elif a.cmd == "adapt":
        if a.week is None or a.score is None:
            ap.error("adapt needs --week and --score")
        plan = adapt_plan(llm, json.loads(STATE.read_text(encoding="utf-8")), a.week, a.score)
    else:
        lang = a.lang or detect_language(a.prompt)
        for i, q in enumerate(generate_quiz(llm, a.topic or "Python Basics", lang), 1):
            print(f"{i}. {q['q']}")
            for j, o in enumerate(q["options"]):
                print(f"   {'ABCD'[j]}) {o}")
        return 0
    STATE.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    show(plan)
    return 0


if __name__ == "__main__":
    sys.exit(main())
