# Changelog

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
- Tests: `test_regression.py` (12), `test_models.py` (13), `test_intake.py` (12).
### Changed
- `MockLLM` moved to `companion/testing.py`; the `mock` backend needs `COMPANION_ALLOW_MOCK=1`.
- CLI default backend is `ollama` with `llama3.2:1b`.
### Not verified
- GGUF reader was tested only against synthetic files written to the public spec, not a real Llama GGUF.
- Ollama and llama.cpp backends were not run against a live model here (no model available).
- Mutation check: 10 of 12 regression tests fail on the baseline engine (the other two are guards).

## M0: baseline (`cc77452`)
Starter kit as first delivered.
