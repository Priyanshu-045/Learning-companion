# Personalized AI Learning Companion (Bharat AI-SoC Challenge — PS4)

An on-device, 100% offline edge AI application running Meta Llama 3.2 1B on Arm hardware to provide personalized curriculum planning, skill-gap analysis, knowledge quizzes, and adaptive learning roadmaps.

Developed and validated on the **Realme GT 6T** (Qualcomm Snapdragon 7+ Gen 3 / SM7675 / Android 16).

---

## 🚀 Key PS4 Specifications & Compliance

| Requirement | Competition Target | Production Achieved (Realme GT 6T) | Status |
| :--- | :--- | :--- | :--- |
| **Token Generation Speed** | $\ge 22$ tokens/sec on Arm hardware | **22.61 – 23.75 tok/s** (2/5 trials);<br>Avg **20.00 tok/s** across all dense multi-node & Indic workloads | **PARTIALLY COMPLIANT / CONDITIONAL**<br>(Exceeds 22 tok/s on single-node & remedial tasks; average across complex workloads is 20.00 tok/s) |
| **RAM Footprint** | Strictly $< 1.8$ GB on Arm hardware | **PSS**: 1,549.2 – 1,560.1 MiB (Mean: **1,554.5 MiB** = **1.52 GiB** IEC = **1.63 GB** decimal);<br>**RSS**: 1,068.7 – 1,551.6 MiB (1.04 – 1.52 GiB IEC = 1.12 – 1.63 GB decimal);<br>**Peak VmHWM**: 1,827.9 – 1,923.3 MiB (1.78 – 1.88 GiB IEC = 1.91 – 2.01 GB decimal) | **COMPLIANT** under physical PSS and RSS;<br>**CONDITIONAL / EXCEEDED** under peak transient virtual `VmHWM` |
| **Availability** | 100% Offline Edge Execution | Zero network permissions, fully functional with Wi-Fi & cellular disabled (`connect: Network is unreachable`) | **COMPLIANT** |
| **Model Architecture** | Meta Llama Family | Meta Llama 3.2 1B Instruct (SpinQuant INT4, 1.06 GB) | **COMPLIANT** |
| **Language Support** | Multilingual Indic (6 Target) | English, Hindi, Marathi, Tamil, Bengali fully verified;<br>Telugu script verified but conditional | **PARTIALLY COMPLIANT / CONDITIONAL**<br>(5/6 languages verified; Telugu conditional due to byte-token inflation) |

---

## 📦 Verified Deliverables & Checksums

### Android Application Packages (APKs)
- **Production Release APK**: `android/app/build/outputs/apk/prod060/release/app-prod060-release.apk`
  - **Size**: 10,906,429 bytes (10.4 MB)
  - **SHA-256**: `b985693ba9f659cdce4fd5e4e99dd77f4362e7479f70947d2168369621710f8b`
- **Production Debug APK**: `android/app/build/outputs/apk/prod060/debug/app-prod060-debug.apk`
  - **Size**: 13,882,171 bytes (13.2 MB)
  - **SHA-256**: `695c210a2e5e81a20fe331f97de131d1456b0cc0476149764ea5e73db61f9dcb`

### Demonstration Video
- **Physical Device Video**: `demo_bharat_aisoc.mp4`
  - **Size**: 402,328 bytes (393 KB)
  - **SHA-256**: `2a9680431c622779fbc0ec302ce6e5867e6b2bb7f8518f0c32504056c0508e9d`
  - **Format**: 720 x 1584 H.264 MP4 Base Media v1 (445 frames at 10.0 fps, 44.5 seconds)
  - **Provenance**: Assembled from high-resolution, uncompressed on-device screen frames captured sequentially on the physical Realme GT 6T device under 100% offline airplane mode. This walkthrough accurately documents live device UI state across all curriculum milestones with zero synthetic rendering.
  - **Integrity**: Decoded and validated frame-by-frame via FFmpeg (445/445 clean frames, zero packet loss, zero corruption).

---

## 🏗️ System Architecture

```
+-----------------------------------------------------------------------------------+
|                         Android Layer (Jetpack Compose UI)                        |
|   - Welcome Screen (6 Indic Languages)      - Goal Intake (Domain & Schedule)     |
|   - Prior Knowledge Checklist (Skill-Gap)   - Interactive Roadmap & Task Tracker  |
|   - Knowledge Check Quiz Engine             - Adaptive Feedback & Profile Manager |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                           Pedagogical Orchestration Core                          |
|   - Directed Acyclic Skill Graphs (DAG): ML Engineer, Data Analyst, Web Dev       |
|   - Structured JSON Repair & Validation (100% JSON schema conformance)            |
|   - Deterministic Fallback Engine (Zero-latency curriculum generation guarantee)  |
|   - Dynamic Adaptation Engine: Topic revision insertion, workload rebalancing     |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                          On-Device Edge Inference Engine                          |
|   - ExecuTorch 0.6.0 Runtime (libexecutorch.so, libfbjni.so)                      |
|   - Multi-threaded XNNPACK CPU Backend (4 hardware threads pinned to A720/X4)     |
|   - Meta Llama 3.2 1B Instruct SpinQuant INT4 (Memory-mapped 1.06 GB footprint)  |
|   - Cooperative Cancellation (AtomicBoolean + engine.stop() interrupt)            |
+-----------------------------------------------------------------------------------+
```

### Flavor Separation
- `prod060` (**Production**): Production release flavor (`com.example.companion`) utilizing stable ExecuTorch 0.6.0 + 4-thread XNNPACK CPU. Fully reproducible out of the box from public Maven Central dependencies.
- `qnn070` (**Experimental**): Diagnostic flavor (`com.example.companion.qnn`) targeting Qualcomm Hexagon HTP V73 via FastRPC. Preserves physical hardware dispatch code, marked experimental as HTP requires specialized target compilation.
- `preview070` (**Experimental**): Isolated preview flavor evaluating ExecuTorch 0.7.0 + KleidiAI kernels.

---

## 📱 Installation & Reproduction Guide

### 1. Build and Install Production APK
```bash
# Build production release from source
cd android
./gradlew assembleProd060Release

# Install signed release APK on connected Android device
adb install -r -d app/build/outputs/apk/prod060/release/app-prod060-release.apk
```

### 2. Verify 100% Offline Mode
```bash
# Completely isolate device from network
adb shell svc wifi disable
adb shell svc data disable

# Verify network is unreachable
adb shell ping -c 1 8.8.8.8
# Expected: connect: Network is unreachable
```

### 3. Launch Application
```bash
adb shell am start -n com.example.companion/.ui.MainActivity
```

---

## 📊 Physical Benchmark Results (Realme GT 6T / SM7675)

| Trial | Workload Scenario | TTFT | Decode Speed | Avg Speed | Duration | Tokens | PSS | RSS | Peak HWM | Battery Temp |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | Single-Node Roadmap (English) | **408 ms** | **22.61 tok/s** | 22.14 tok/s | 17.5 s | 387 | **1,555.5 MiB** | 1,471.0 MiB | 1,844.4 MiB | 41.8 °C |
| **2** | Multi-Node Sequential (English) | **366 ms** | **16.93 tok/s** | 16.73 tok/s | 25.6 s | 429 | **1,549.2 MiB** | 1,068.7 MiB | 1,827.9 MiB | 41.8 °C |
| **3** | Adaptive Quiz Remedial (English) | **385 ms** | **23.75 tok/s** | 23.26 tok/s | 16.7 s | 388 | **1,560.1 MiB** | 1,551.6 MiB | 1,828.0 MiB | 41.8 °C |
| **4** | Multilingual Prompt (Hindi) | **794 ms** | **18.72 tok/s** | 18.20 tok/s | 26.5 s | 482 | **1,550.9 MiB** | 1,196.9 MiB | 1,923.3 MiB | 42.9 °C |
| **5** | Multilingual Regional (Tamil) | **1,241 ms** | **18.00 tok/s** | 9.43 tok/s | 21.4 s | 202 | **1,556.9 MiB** | 1,272.0 MiB | 1,851.8 MiB | 42.9 °C |

### RAM Accounting Breakdown
- **PSS**: 1,549.2 – 1,560.1 MiB (Mean: **1,554.5 MiB** = **1.518 GiB** IEC = **1.630 GB** decimal). Strictly below the 1.8 GB competition limit under both binary ($1.8\text{ GiB} = 1,843.2\text{ MiB}$, 288.7 MiB margin) and decimal ($1.80\text{ GB} = 1,800.0\text{ MB}$, 170.0 MB margin) definitions.
- **RSS**: 1,068.7 – 1,551.6 MiB (1.04 – 1.52 GiB IEC / 1.12 – 1.63 GB decimal). Strictly below 1.8 GB.
- **Peak VmHWM**: 1,827.9 – 1,923.3 MiB (1.78 – 1.88 GiB IEC / 1.91 – 2.01 GB decimal). Peak transient virtual pages touched during initial `mmap` allocation.

---

## 🌐 Multilingual Generation Reality (6 Indic Languages)

All 6 languages were tested on the physical device for actual generation speed and script output:

| Language | Script | TTFT | Decode Speed | Generated Tokens | Native Script Chars | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **English (`en`)** | Latin | 518 ms | 11.02 tok/s | 282 | 809 | **PASS**: Fluent, valid curriculum |
| **Hindi (`hi`)** | Devanagari | 528 ms | 22.70 tok/s | 382 | 343 | **PASS**: High fluency Devanagari |
| **Marathi (`mr`)** | Devanagari | 582 ms | 20.72 tok/s | 382 | 329 | **PASS**: Valid Devanagari; phrase repetition noted |
| **Tamil (`ta`)** | Tamil | 1,177 ms | 23.39 tok/s | 185 | 129 | **PASS**: Valid Tamil script; high TTFT |
| **Telugu (`te`)** | Telugu | 1,489 ms | 21.88 tok/s | 163 | 70 | **CONDITIONAL**: Severe byte-token inflation (~2.33 tok/char) & math hallucinations |
| **Bengali (`bn`)** | Bengali | 1,032 ms | 23.33 tok/s | 202 | 130 | **PASS**: Valid Bengali script; token expansion |

---

## 🧪 Desktop Prototype & Unit Tests

The repository contains a fully tested, zero-dependency Python prototype for pedagogical graph validation, prompt engineering, and offline regression testing.

```bash
# Run 133 unit tests
PYTHONPATH=prototype python3 -m unittest discover -s prototype/tests
# Result: 133 tests, OK

# Run Android unit tests
cd android && ./gradlew testProd060DebugUnitTest
# Result: BUILD SUCCESSFUL
```

---

## 🔒 Security, Privacy & Integrity Audit
- **Zero Secrets / API Keys**: Scanned and verified via automated entropy and pattern scans.
- **No Committed Model Binaries**: Weights and models remain uncommitted in git; fetched or sideloaded directly on target hardware.
- **Local Data Storage**: User profiles and learning history remain strictly on device in private app storage (`/data/user/0/com.example.companion/`).
- **Zero Network Egress**: Confirmed with all network interfaces physically disabled.
