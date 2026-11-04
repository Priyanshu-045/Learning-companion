# Audit and implementation plan (Milestone 0)

Audited commit `cc77452` ("baseline"). Method: read every file, ran the tests, probed suspected edge cases
with a script, and checked the ExecuTorch Android API against docs.pytorch.org/executorch/main (Nov 2026).
Anything not run is marked UNVERIFIED.

## 1. What exists

| Area | Files | Reality |
|---|---|---|
| `shared/` | 3 skill graphs (ML engineer, web dev, data analyst), roadmap + quiz prompts | Valid, acyclic, tested. Only 3 of the ~8 domains PS4 mentions (no exam prep, language learning, cybersecurity, graphic design). |
| `prototype/` | Python engine + CLI: language detection, gap analysis, weekly packing, LLM week-filling with validate/retry/fallback, adaptation, quiz generation | Logic works (17 tests passed). Defects below. |
| `android/core/` | 7 Kotlin files: port of the Python logic + `ExecuTorchEngine` | **Never compiled or run.** No UI, no Room, no tests, no benchmarks. |
| READMEs | root + `android/README_ANDROID.md` | Python steps correct; Android steps partly stale (K8). |

## 2. What was verified working (baseline)
Prerequisite ordering, week packing hours conservation, JSON extraction/validation, resource snapping, retry on bad
JSON, fallback on backend failure, wrong-script rejection, deterministic adaptation rules, quiz validation.
All exercised only against `MockLLM`, never a real Llama model.

## 3. Defects found

Confirmed by running code (Python):

| ID | Defect | Severity |
|---|---|---|
| D1 | `pack()` loops forever when weekly hours is 0 or negative (would freeze the app) | High |
| D2 | Unknown skill ids in `known` silently ignored | Medium |
| D3 | Knowing every skill gives an empty plan and a confusing error on adapt | Medium |
| D4 | `adapt_plan` accepted score 5 and NaN, any week order, and re-scoring a week | Medium |
| D5 | `minutes: Infinity` raised a raw ValueError, skipping the retry path | Low |
| D6 | `generate_quiz` leaked raw backend exceptions | Low |
| D7 | Nothing enforced Llama-only: Ollama and llama.cpp backends accepted `qwen2.5:1.5b` or any GGUF | **High (PS4 rule)** |
| D8 | `MockLLM` was the default backend and could serve real runs | **High (PS4 rule)** |
| D9 | "Goal understanding" was never implemented: the CLI required `--domain`; no free-text goal, hours or known-skill extraction | **High (core capability 1)** |

Found by reading the Kotlin (UNVERIFIED, cannot compile here):

| ID | Defect |
|---|---|
| K1 | `load()` return code ignored; docs say it returns an Int status |
| K2 | `LlmCallback.onError` not implemented; may not compile if abstract, and errors are lost |
| K3 | `chat()` blocks and returns one string: no token streaming |
| K4 | `maxTokens` is passed as `seqLen`; likely total length including prompt, so long prompts truncate output. Docs offer `LlmGenerationConfig.maxNewTokens` |
| K5 | BOS handling unverified: template adds `<|begin_of_text|>` manually, docs expose `numBos` |
| K6 | No lifecycle (stop, resetContext, release), no serialization of concurrent calls |
| K7 | Intake, model policy and quiz generation were never ported to Kotlin |
| K8 | `README_ANDROID.md` points to `examples/demo-apps/android/LlamaDemo` and `export_llama`; the docs now point to the executorch-examples repo and `export_llm` |
| K9 | Offline guarantee not enforced (no manifest check) |

Known limitations not yet fixed: romanized Hindi ("mujhe plan chahiye") is detected as English; fallback weeks are
English even for regional-language users (violates the same-language rule); script validation cannot judge fluency
or correctness (needs M2).

## 4. PS4 compliance gaps

| Requirement | Status |
|---|---|
| Llama family only | Enforced for desktop backends (M1). Android model check pending (M3) |
| ExecuTorch on Arm Android | UNVERIFIED: no device run yet |
| INT4/INT8 export | Not done |
| 22+ tok/s, under 1.8 GB RAM | **Unmeasured. No claim made.** |
| 100% offline | Design is offline; enforcement and test pending (M3) |
| Goal understanding, skill gaps, adaptive plans | Gap analysis and adaptation done; intake added in M1; conversational layer pending (M4) |
| Six languages, same-language reply | Pipeline supports them; quality unmeasured; English fallback is non-compliant (M2, M5) |
| Quizzes, Room DB, dashboard, tutor chat, benchmark screen, UI | Not started (M4, M5) |
| APK, report, demo video | Not started (M8) |

## 5. Implementation plan

Constraint: this environment has no Android SDK, no network for downloads and no device. Python milestones are
built and tested here. Android milestones are written here but must be compiled and run on your machine; I
iterate on the errors you report. Nothing is called "done" until it has run.

| Milestone | Scope | Exit criterion |
|---|---|---|
| **M1 (done)** | Fix D1-D9, Llama-only guards, quarantine mock, intake, regression tests, docs | 50 Python tests pass; regression tests fail on baseline |
| **M2** | Multilingual evaluation harness: per-language JSON validity, fallback rate, language ID, topic coverage, human rating sheet; run on real Llama 3.2 1B (Ollama) | Baseline numbers from a real run committed. Fine-tune decision gate |
| **M3** | Android core: pin ExecuTorch version, read its Java source, fix K1-K9, streaming API, lifecycle, JVM unit tests, no INTERNET permission | `gradle test` green on your machine; model loads and generates on a phone |
| **M4** | Room schema, repositories, adaptive loop, tutor chat prompt, quiz scoring (Kotlin) | Instrumented tests pass |
| **M5** | Compose UI: onboarding, dashboard, roadmap, daily tasks, quiz, tutor, benchmark screen | Runs on device, airplane mode |
| **M6** | Real benchmarks: tok/s (prefill and decode), PSS RAM, thermals, 2 devices; optimization | Numbers recorded with method; targets met or honestly missed |
| **M7** | Indic LoRA fine-tune of Llama, only if M2 baseline fails the quality gate | Beats baseline on the same eval |
| **M8** | Hardening, translated fallback strings, report, demo | Zero-crash 30 min offline run |

Decision gates: do not start M7 before M2 numbers exist. Do not claim any competition target before M6.
