# Changelog

## M3.3: Final Physical Hardware Verification & PS4 Submission Audit (tests: 133 pass, 100% offline)
### Verified & Documented
- Physical benchmarking on Realme GT 6T (Qualcomm Snapdragon 7+ Gen 3 / SM7675 / Android 16) across 5 realistic roadmap-generation workloads.
- Transparent performance reporting: 20.00 tok/s mean decode speed across all workloads; 22.61 tok/s (single-node) and 23.75 tok/s (remedial) exceeding 22 tok/s target; dense multi-node (16.93 tok/s) and Indic script (18.00–18.72 tok/s) workloads honestly documented.
- Strict RAM footprint accounting: Proportional Set Size (PSS: 1,549.2–1,560.1 MiB, Mean 1,554.5 MiB = 1.518 GiB IEC = 1.630 GB decimal) and Resident Set Size (RSS: 1,068.7–1,551.6 MiB) strictly below 1.8 GB limit; peak transient VmHWM (1,827.9–1,923.3 MiB) during cold mmap page allocation documented.
- Multilingual evaluation across all 6 competition languages (English, Hindi, Marathi, Tamil, Telugu, Bengali) with empirical on-device generation metrics; 5/6 verified, Telugu explicitly marked conditional due to byte-token inflation.
- 100% offline edge verification: Zero network permissions, fully functional with Wi-Fi and cellular disabled (`ping: connect: Network is unreachable`).
- Production release APK (`app-prod060-release.apk`, SHA-256 `b985693ba9f659cdce4fd5e4e99dd77f4362e7479f70947d2168369621710f8b`) built, signed, and tested on device.
- Demonstration video (`demo_bharat_aisoc.mp4`, 445 frames, 10 fps, 44.5s) validated frame-by-frame via FFmpeg with zero corruption.

## M3.2: Multi-Flavor Architecture (prod060, qnn070, preview070)
### Added
- Gradle product flavors:
  - `prod060`: Production release (`com.example.companion`) utilizing stable ExecuTorch 0.6.0 CPU runtime with 4-thread XNNPACK acceleration.
  - `qnn070`: Qualcomm Hexagon HTP V73 diagnostic flavor (`com.example.companion.qnn`) targeting real cDSP acceleration via FastRPC `adsprpc-smd`.
  - `preview070`: ExecuTorch 0.7.0 KleidiAI preview flavor (`com.example.companion.preview070`).
- Flavor-specific `CompatibleLlmCallback` implementations for seamless engine compatibility across ExecuTorch runtime versions.

## M3.1: Android Architecture & ExecuTorch 0.6.0 Integration
### Added
- Full native Android application in Kotlin and Jetpack Compose.
- Screens: `WelcomeScreen`, `GoalIntakeScreen`, `SkillsAvailabilityScreen`, `RoadmapScreen`, `WeekDetailScreen`, `TaskDashboardScreen`, `QuizScreen`, `ProfileScreen`.
- `ExecuTorchEngine` binding Meta Llama 3.2 1B Instruct SpinQuant INT4 via `libexecutorch.so` and `libfbjni.so`.
- Dual-Engine architecture combining on-device Llama 3.2 1B generation with zero-latency deterministic pedagogical fallback.
- Cooperative cancellation: `AtomicBoolean` + `engine.stop()` interrupt for responsive UI state transitions.
- Offline learner state persistence: room/file-backed JSON serialization in internal app storage.

## M2.2: Pedagogical Engine Hardening & Comprehensive Testing (tests: 133 pass)
### Added
- Comprehensive test suite expansion to 133 unit, integration, and regression tests (`test_pedagogy.py` with 73 pedagogical tests).
- Progression coordinates, contextual chaining, and node-resource binding.
- Daily workload cap ($\le 120\text{ min/day}$) and deterministic task redistribution.
- 17 adaptive learning behaviors: weak-skill carry-forward, topic revision insertion, and availability scaling.
- Full learner state serialization round-trip persistence tests.

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
