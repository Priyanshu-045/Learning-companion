# Implementation checklist
`[x]` = built AND verified as stated. `[~]` = written, not verified. `[ ]` = not started.

## Models and policy
- [x] Llama-only guard for Ollama tags (unit-tested)
- [x] Llama-only guard for GGUF files (unit-tested on synthetic GGUF only)
- [x] MockLLM quarantined to tests
- [ ] Android: verify the `.pte` is a Llama export (M3)
- [ ] Export Llama 3.2 1B INT4 with ExecuTorch (M3, needs your machine)

## Python engine
- [x] Language detection (script + Hindi/Marathi markers); romanized Hindi NOT supported
- [x] Goal understanding / intake (deterministic, 3 domains)
- [x] Skill graphs (3 domains); [ ] more domains: exam prep, languages, cybersecurity, design
- [x] Gap analysis, weekly packing, adaptation rules, quiz generation
- [x] JSON validation, retry, fallback, input validation
- [x] Regression tests for D1-D9
- [x] Output reliability & safe minute/day parsing (M2.1)
- [x] Localized deterministic fallback templates in 6 languages (M2.1)
- [ ] Multilingual quality evaluation on a real Llama (M2)

## Android
- [~] Kotlin port of logic (uncompiled)
- [ ] Pin ExecuTorch version and verify API from its source (M3)
- [ ] Fix K1-K9 (M3)
- [ ] Token streaming, lifecycle, cancel (M3)
- [ ] No INTERNET permission, airplane-mode test (M3)
- [ ] Room database (M4)
- [ ] Onboarding, dashboard, roadmap, daily tasks, quiz, tutor chat, benchmark screen (M4-M5)

## Competition targets (NO claims until measured on a device)
- [ ] 22+ tokens/sec decode
- [ ] RAM under 1.8 GB (method: peak PSS via /proc/self/smaps_rollup)
- [ ] 100% offline verified
- [ ] INT4/INT8 verified in the exported file
- [ ] Arm acceleration (XNNPACK/Neon, NPU delegate if supported) measured
- [ ] 30-minute zero-crash run

## Deliverables
- [ ] Public GitHub repo, signed APK, demo video, technical report
