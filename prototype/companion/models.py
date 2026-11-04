"""Llama-only policy for the final reasoning pipeline (PS4 requirement).

These checks are a SAFETY NET against accidentally wiring in Qwen/Gemma/etc. They are name- and
metadata-based, so they cannot prove provenance. Record the exact model card / file hash in the
technical report as the real evidence.
"""
import re
import struct


class ModelPolicyError(ValueError):
    pass


# Official Ollama tags for Meta Llama 3.x, e.g. llama3.2:1b, llama3.2:1b-instruct-q4_K_M, llama3.1:8b
_OLLAMA_META = re.compile(r"^(?:library/)?llama3(?:\.[123])?(?::[\w.\-]+)?$", re.I)
_NOT_META = re.compile(r"tinyllama|mistral|vicuna|alpaca|qwen|gemma|phi|deepseek", re.I)


def check_ollama_model(name, allow_derivative=False):
    """Return 'meta' or 'derivative'. Derivatives (e.g. our own Indic LoRA merge) need explicit opt-in."""
    if not isinstance(name, str) or not name.strip():
        raise ModelPolicyError("model name is empty")
    if _OLLAMA_META.match(name.strip()):
        return "meta"
    if allow_derivative and "llama" in name.lower() and not _NOT_META.search(name):
        return "derivative"
    raise ModelPolicyError(
        f"'{name}' is not a recognised Meta Llama 3.x model (expected e.g. llama3.2:1b). "
        "If this is your own Llama fine-tune, pass allow_derivative=True / --llama-derivative.")


_SCALARS = {0: ("<B", 1), 1: ("<b", 1), 2: ("<H", 2), 3: ("<h", 2), 4: ("<I", 4), 5: ("<i", 4),
            6: ("<f", 4), 7: ("<?", 1), 10: ("<Q", 8), 11: ("<q", 8), 12: ("<d", 8)}


def read_gguf_general(path):
    """Read only the leading `general.*` metadata of a GGUF v2/v3 file (never loads weights)."""
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            raise ModelPolicyError(f"{path} is not a GGUF file")
        (version,) = struct.unpack("<I", f.read(4))
        if version not in (2, 3):
            raise ModelPolicyError(f"unsupported GGUF version {version}")
        _tensors, kv_count = struct.unpack("<QQ", f.read(16))

        def rd_str():
            (n,) = struct.unpack("<Q", f.read(8))
            return f.read(n).decode("utf-8", "replace")

        def rd_val(t):
            if t == 8:
                return rd_str()
            if t == 9:
                (et,) = struct.unpack("<I", f.read(4))
                (n,) = struct.unpack("<Q", f.read(8))
                for _ in range(n):
                    rd_val(et)
                return None
            if t not in _SCALARS:
                raise ModelPolicyError(f"unknown GGUF value type {t}")
            fmt, size = _SCALARS[t]
            return struct.unpack(fmt, f.read(size))[0]

        found = {}
        for _ in range(kv_count):
            key = rd_str()
            if found.get("general.architecture") and not key.startswith("general."):
                break  # general.* keys come first by convention; don't parse big tokenizer arrays
            (t,) = struct.unpack("<I", f.read(4))
            val = rd_val(t)
            if key.startswith("general."):
                found[key] = val
        return found


def check_gguf(path, allow_derivative=False):
    meta = read_gguf_general(path)
    arch = meta.get("general.architecture")
    if arch != "llama":
        raise ModelPolicyError(f"GGUF architecture is '{arch}', expected 'llama' (Qwen/Gemma/Phi etc. are not allowed)")
    blob = " ".join(str(meta.get(k, "")) for k in ("general.name", "general.basename")) + " " + str(path)
    if _NOT_META.search(blob):
        raise ModelPolicyError(f"model metadata/name looks like a non-Meta model: {blob.strip()[:120]}")
    if "llama" not in blob.lower():
        raise ModelPolicyError("architecture is 'llama' but the name does not say Llama "
                               "(Mistral and others share this architecture)")
    return "meta" if re.search(r"llama[-_ ]?3", blob, re.I) and not allow_derivative else "derivative"


def assert_final_pipeline_llm(llm):
    """Call before serving real users / recording the demo. Mock and unknown backends are refused."""
    fam = getattr(llm, "family", None)
    if fam != "llama":
        raise ModelPolicyError(f"final pipeline requires a Llama backend, got family={fam!r} "
                               f"({getattr(llm, 'model_id', type(llm).__name__)})")
