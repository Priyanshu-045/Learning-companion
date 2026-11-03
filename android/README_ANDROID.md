# Android: run Llama on-device with ExecuTorch

Status: the Kotlin files in `core/` are a direct port of the tested Python logic but have NOT been compiled
or run (no Android toolchain was available when they were written). Expect to fix small compile errors.
Exact ExecuTorch commands and flags change between releases — treat the steps below as the outline and follow
the README inside your ExecuTorch checkout when they differ.

## 0. Prerequisites
- Android Studio (latest), Android SDK + NDK (versions per ExecuTorch's Android docs), JDK 17
- Python 3.10–3.12 (conda or venv), git
- A physical Arm Android phone with USB debugging on (`adb devices` must list it). Emulators are not valid for benchmarks.
- Hugging Face / Meta access to the Llama 3.2 weights (accept the license first)

## 1. Get ExecuTorch and a runnable baseline
```bash
git clone https://github.com/pytorch/executorch.git
cd executorch
git submodule update --init --recursive
./install_executorch.sh          # older versions: ./install_requirements.sh
```
Then read `examples/models/llama/README.md` and do two things from it:
1. Download Llama 3.2 1B Instruct (the pre-quantized SpinQuant/QLoRA INT4 variants are the quickest start).
2. Export it to a `.pte` file with the XNNPACK backend (command is in that README; it is long and version-specific).

Then build/open the reference app `examples/demo-apps/android/LlamaDemo` (its README explains getting the
`executorch.aar` and building). Push the files:
```bash
adb shell mkdir -p /data/local/tmp/llama
adb push llama3_2.pte      /data/local/tmp/llama/
adb push tokenizer.model   /data/local/tmp/llama/
```
Run the demo app, load the model, and chat. **Record tokens/sec and peak RAM now** (Android Studio Profiler → Memory).
Targets: 22+ tok/s, under 1.8 GB. If you miss them, fix that before adding features.

## 2. Plug in our logic
In the LlamaDemo project (or your copy of it):
1. Copy `core/*.kt` into `app/src/main/java/com/example/companion/`.
2. Copy `shared/skill_graphs/` and `shared/prompts/` into `app/src/main/assets/`.
3. In `ExecuTorchEngine.kt`, fix the lines marked `VERIFY` so they match how the demo app creates `LlmModule`/`LlamaModule`.
4. Add `implementation("org.json:json:20240303")` ONLY to JVM unit tests (`testImplementation`); Android already ships org.json.
5. Call it from a background thread:
```kotlin
val engine = ExecuTorchEngine("/data/local/tmp/llama/llama3_2.pte", "/data/local/tmp/llama/tokenizer.model").also { it.load() }
val system = assets.open("prompts/system_roadmap.txt").bufferedReader().readText()
val graph  = SkillGraph.parse(assets.open("skill_graphs/ml_engineer.json").bufferedReader().readText())
val lang   = LanguageDetector.detect(userText)
val gen    = RoadmapGenerator(engine, system)

val gaps   = Planner.findGaps(graph, knownSkillIds)
val queue  = gaps.map { id -> PlanItem(id, graph.nodes.first { it.id == id }.hours) }
val weeks  = Planner.pack(queue, weeklyHours).map { gen.fillWeek(graph, it, lang, graph.title, weeklyHours) }
```
6. Adaptation after a quiz: `Planner.adaptQueue(...)` → `Planner.pack(..., startWeek)` → `fillWeek` for each new week
   (same flow as `adapt_plan` in `prototype/companion/roadmap.py`).

## 3. Next things to build (in order)
1. Compose screens: profile intake, roadmap list, quiz, progress chart (Room/SQLite for storage)
2. Stream tokens to the UI + cancel button
3. Benchmark log screen (tok/s, RAM, temperature) for the technical report
4. Indic LoRA fine-tune, then re-export the model
5. Translated UI strings for the English fallback week
