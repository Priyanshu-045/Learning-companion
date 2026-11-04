#!/usr/bin/env python3
"""Desktop prototype of the learning companion. Examples:
  python cli.py intake --text "I want to be an ML engineer, 5 hours a week"
  python cli.py domains
  python cli.py plan --domain ml_engineer --hours 5 --known python_basics --prompt "Plan my ML career"
  python cli.py plan --domain data_analysis --hours 6 --prompt "मुझे 1 महीने का डेटा साइंस प्लान चाहिए"
  python cli.py quiz --topic "NumPy and Pandas" --lang hi
  python cli.py adapt --week 1 --score 0.4
  python cli.py show
Default backend: ollama with Meta Llama 3.2 1B (`ollama pull llama3.2:1b`). Llama-family models only.
Unit-test smoke runs: COMPANION_ALLOW_MOCK=1 python cli.py ... --backend mock"""
import argparse
import json
import pathlib
import sys

from companion.lang import detect_language, LANG_NAMES
from companion.intake import understand, next_question
from companion.llm import make_llm, DEFAULT_MODEL
from companion.models import assert_final_pipeline_llm, ModelPolicyError
from companion.planner import list_domains
from companion.roadmap import build_plan, adapt_plan, generate_quiz

STATE = pathlib.Path("companion_state.json")


def show(plan):
    print(f"\nModel: {plan.get('generated_by', 'unknown')}")
    print(f"Goal: {plan['goal']} | {plan['weekly_hours']} h/week | language: {LANG_NAMES[plan['language']]}")
    print(f"Skill gaps: {', '.join(plan['skill_gaps']) or 'none'}")
    for w in plan["weeks"]:
        tag = "" if w["source"] == "llm" else f"  [{w['source']}]"
        sc = f"  (quiz {w['score']:.0%})" if "score" in w else ""
        print(f"\n#{w['week']}  {w['title']}{sc}{tag}")
        for t in w["tasks"]:
            print(f"  Day {t['day']}  {t['minutes']:>3} min  {t['task']}  <{t['resource']}>")
        print(f"  Milestone: {w['milestone']}")
    fb = [w for w in plan["weeks"] if w["source"] != "llm"]
    if fb:
        print(f"\nWARNING: {len(fb)}/{len(plan['weeks'])} weeks used the English template fallback, not the model. "
              f"First error: {fb[0].get('error')}")
    for a in plan.get("adaptations", []):
        print(f"\nAdaptation: week {a['week']} scored {a['score']:.0%} -> {a['action']}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["domains", "intake", "plan", "adapt", "show", "quiz"])
    ap.add_argument("--domain", default="ml_engineer")
    ap.add_argument("--hours", type=float, default=5)
    ap.add_argument("--known", default="", help="comma-separated skill ids you already know")
    ap.add_argument("--prompt", default="", help="user's free text; used to detect language")
    ap.add_argument("--lang", choices=list(LANG_NAMES))
    ap.add_argument("--backend", default="ollama", choices=["ollama", "llamacpp", "mock"])
    ap.add_argument("--model", help=f"Llama model: ollama tag (default {DEFAULT_MODEL}) or path to a Llama .gguf")
    ap.add_argument("--llama-derivative", action="store_true", help="allow your own Llama fine-tune")
    ap.add_argument("--text", help="free text for the intake command")
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
    if a.cmd == "intake":
        p = understand(a.text or a.prompt)
        print(json.dumps(p, ensure_ascii=False, indent=2))
        print("\nNext question:", next_question(p) or "(intake complete)")
        return 0
    try:
        llm = make_llm(a.backend, a.model, a.llama_derivative)
        if a.backend != "mock":
            assert_final_pipeline_llm(llm)
    except (ModelPolicyError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"[model: {llm.model_id}]")
    if a.cmd in ("plan", "adapt"):
        try:
            if a.cmd == "plan":
                lang = a.lang or detect_language(a.prompt)
                known = [k for k in a.known.split(",") if k]
                plan = build_plan(llm, a.domain, a.hours, known, lang)
            else:
                if a.week is None or a.score is None:
                    ap.error("adapt needs --week and --score")
                plan = adapt_plan(llm, json.loads(STATE.read_text(encoding="utf-8")), a.week, a.score)
        except (ValueError, FileNotFoundError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        if plan["status"] == "complete":
            print("You already know every skill in this path. Nothing to plan.")
            return 0
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
