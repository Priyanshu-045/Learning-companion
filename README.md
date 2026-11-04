# Personalized AI Learning Companion — starter kit

```
shared/        skill graphs (JSON), system prompts  -> used by BOTH the prototype and the Android app
prototype/     Python desktop prototype (tested, zero dependencies) — build/tune logic here first
android/       Kotlin core logic + ExecuTorch engine wrapper (to drop into the ExecuTorch Llama demo app)
```

## Part A: Run the Python engine on your computer

Needs Python 3.10+, no pip installs. Models: **Meta Llama only** (default `llama3.2:1b`).

```bash
cd learning-companion/prototype
python3 -m unittest discover -s tests          # expect: 50 tests, OK
```

### With a real Llama model (needed for real output)
1. Install Ollama from https://ollama.com, then `ollama pull llama3.2:1b`
2. ```bash
   python3 cli.py intake --text "I want to become an ML engineer, 5 hours a week"
   python3 cli.py plan --domain ml_engineer --hours 5 --known python_basics --prompt "Plan my ML career"
   python3 cli.py adapt --week 1 --score 0.4      # weeks are scored in order
   python3 cli.py plan --domain data_analysis --hours 6 --prompt "मुझे 1 महीने का डेटा साइंस प्लान चाहिए"
   python3 cli.py quiz --topic "NumPy and Pandas" --lang ta
   ```
Other backends: `--backend llamacpp --model path/to/Llama-3.2-1B-Instruct-Q4_K_M.gguf`. Non-Llama models are refused.
Your own Llama fine-tune needs `--llama-derivative`.

If the model server is down, the CLI prints a WARNING and shows English template weeks, which are not model output.

### Pipeline smoke test without a model (tests only)
`COMPANION_ALLOW_MOCK=1 python3 cli.py plan --backend mock --domain web_dev --hours 8`
The mock is not a Llama model and is never valid for the demo or the report.

See `AUDIT.md` (findings and plan), `CHANGELOG.md`, `CHECKLIST.md` (what is verified vs not).

## Part B — Android (on-device ExecuTorch)

See `android/README_ANDROID.md`.
