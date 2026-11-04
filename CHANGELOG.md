# Changelog

## M2.1: Output Reliability (tests: 68 pass, fallback rate: 0/21)
### Fixed
- Roadmap schema inversion: moved `milestone` before `tasks` in `system_roadmap.txt`, eliminating token cutoffs and premature JSON closure in Llama 3.2 1B.
- Safe minute parsing: `parse_minutes()` safely parses `"60"`, `"60 mins"`, `"1.5 hours"`, while strictly rejecting non-positive, non-finite, or ambiguous inputs.
- Non-clamping day validation: rejects days outside 1-7 (0, 8, 9, -1) and triggers retry instead of silent corruption.
- Anti-reinforcement retry messages: retry prompt no longer repeats malformed/truncated assistant outputs into context; provides clear schema reminder.
- Trailing comma tolerance in `extract_json()`.
- Key normalization: handles synonym keys (`weekly_milestone`, `milestone_goal`, `goal`, `project`) and list milestones.
### Added
- Localized fallback templates (`FALLBACK_TEMPLATES`) in `roadmap.py` supporting all 6 languages (`en`, `hi`, `mr`, `ta`, `te`, `bn`), all verified via `script_ok`.
- Attempt tracking: records `"attempts"` count and `"source"` on each week (`source == "llm"` vs `"fallback"`).
- CLI reliability reporting: shows first attempt, retry, and localized fallback metrics.
- Tests: `test_reliability.py` with 18 tests covering minute parsing, day rejection without clamping, trailing commas, key normalization, all 6 localized fallbacks, attempt tracking, and retry message hygiene.
### Verified
- 68/68 Python tests passing (`test_core.py`: 17, `test_regression.py`: 12, `test_models.py`: 10, `test_intake.py`: 11, `test_reliability.py`: 18).
- Live CLI run with Meta Llama 3.2 1B (Ollama): `python3 cli.py plan --domain ml_engineer --hours 5 --known python_basics --prompt "Plan my ML career"`.
- Fallback rate dropped from baseline 6/21 (28.6%) down to **0/21 (0.0%)**, with **21/21 weeks succeeding on first attempt**.

## M1: Python engine hardening, Llama-only, intake (tests: 50 pass)
### Fixed
- D1 `pack()` no longer hangs on weekly hours <= 0; hours must be finite and in (0, 100].
- D2 unknown skill ids, languages and domains raise clear errors.
- D3 plans where everything is known return `status: "complete"` with no weeks.
- D4 `adapt_plan` validates score in [0, 1], enforces in-order weeks, rejects re-scoring, preserves earlier scores.
- D5 non-finite `minutes` is a ValidationError (goes through retry).
- D6 quiz backend errors become a clear ValidationError.
- CLI shows a loud warning when weeks used the template fallback instead of the model.
### Added
- `companion/models.py`: Llama-only policy. Ollama tag allow-list (Llama 3.x), GGUF header reader
  (`general.architecture == llama` plus name check), explicit opt-in for your own Llama fine-tunes,
  `assert_final_pipeline_llm`.
- `companion/intake.py`: goal understanding in six languages (domain, weekly hours, known skills, scripted
  follow-up questions). Question strings and non-English keywords need native-speaker review.
- Every plan records `generated_by` (model id). Ollama backend records its own eval stats.
- Tests: `test_regression.py` (12), `test_models.py` (10), `test_intake.py` (11).
### Changed
- `MockLLM` moved to `companion/testing.py`; the `mock` backend needs `COMPANION_ALLOW_MOCK=1`.
- CLI default backend is `ollama` with `llama3.2:1b`.
### Not verified
- GGUF reader was tested only against synthetic files written to the public spec, not a real Llama GGUF.
- Ollama and llama.cpp backends were not run against a live model here (no model available).
- Mutation check: 10 of 12 regression tests fail on the baseline engine (the other two are guards).

## M0: baseline (`cc77452`)
Starter kit as first delivered.
