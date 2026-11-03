# Personalized AI Learning Companion — starter kit

```
shared/        skill graphs (JSON), system prompts  -> used by BOTH the prototype and the Android app
prototype/     Python desktop prototype (tested, zero dependencies) — build/tune logic here first
android/       Kotlin core logic + ExecuTorch engine wrapper (to drop into the ExecuTorch Llama demo app)
```

## Part A — Run the prototype on your computer (5 minutes)

Needs only Python 3.10+. No pip installs.

```bash
cd learning-companion/prototype

# 1. Run the tests (should print "OK", 17 tests)
python3 -m unittest discover -s tests -v

# 2. Full pipeline with the built-in mock model (no download)
python3 cli.py domains
python3 cli.py plan --domain ml_engineer --hours 5 --known python_basics --prompt "Plan my ML career"
python3 cli.py adapt --week 1 --score 0.4      # fail a quiz -> revision week inserted, later weeks shift
python3 cli.py adapt --week 2 --score 0.95     # ace a quiz  -> next topic shortened
python3 cli.py show

# 3. Regional language (language auto-detected from the prompt)
python3 cli.py plan --domain data_analysis --hours 6 --prompt "मुझे 1 महीने का डेटा साइंस प्लान चाहिए"
python3 cli.py quiz --topic "NumPy and Pandas" --lang ta
```
On Windows use `python` instead of `python3`.

### Use a real Llama model on your PC (prompt/JSON tuning)
1. Install Ollama from https://ollama.com
2. `ollama pull llama3.2:1b`
3. `python3 cli.py plan --backend ollama --domain ml_engineer --hours 5 --prompt "Plan my ML career"`

Look at the `[fallback]` tag in the output: it marks weeks where the model failed validation twice.
That fallback rate (and the Hindi/Tamil/Telugu/Bengali/Marathi pass rate) is your first real quality metric.
The mock backend does NOT translate; it only proves the pipeline. Real regional-language quality
needs the model (and later the LoRA fine-tune).

State is saved to `companion_state.json` in the folder you run from.

### Add a new domain
Copy `shared/skill_graphs/web_dev.json`, edit nodes (id, name, prereqs, hours, resources), save. It shows up in
`cli.py domains` automatically; `tests` will check it has no cycles and every prereq exists.
Use real resource *titles* only (no invented URLs).

## Part B — Android (on-device ExecuTorch)

See `android/README_ANDROID.md`.
