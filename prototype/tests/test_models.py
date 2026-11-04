import os
import struct
import tempfile
import unittest

from companion.llm import make_llm, OllamaLLM
from companion.models import (check_ollama_model, check_gguf, read_gguf_general, assert_final_pipeline_llm,
                              ModelPolicyError)
from companion.testing import MockLLM


def _s(x):
    b = x.encode()
    return struct.pack("<Q", len(b)) + b


def write_gguf(path, arch, name, version=3):
    """Synthetic GGUF per the public spec (header + KV metadata only). NOT a real model file."""
    kvs = [("general.architecture", 8, _s(arch)), ("general.name", 8, _s(name)),
           ("tokenizer.ggml.tokens", 9, struct.pack("<I", 8) + struct.pack("<Q", 2) + _s("a") + _s("b"))]
    body = b"".join(_s(k) + struct.pack("<I", t) + v for k, t, v in kvs)
    with open(path, "wb") as f:
        f.write(b"GGUF" + struct.pack("<I", version) + struct.pack("<QQ", 0, len(kvs)) + body)


class OllamaPolicy(unittest.TestCase):
    def test_meta_llama_accepted(self):
        for ok in ("llama3.2:1b", "llama3.2:1b-instruct-q4_K_M", "llama3.2:3b", "llama3.1:8b", "llama3", "llama3.3:70b"):
            self.assertEqual(check_ollama_model(ok), "meta", ok)

    def test_other_families_rejected(self):
        for bad in ("qwen2.5:1.5b", "gemma2:2b", "phi3:mini", "mistral:7b", "tinyllama", "llama3.2-vision",
                    "codegemma", "deepseek-r1:1.5b", "", "gemma-llama-mix"):
            with self.assertRaises(ModelPolicyError, msg=bad):
                check_ollama_model(bad)

    def test_derivative_needs_opt_in(self):
        with self.assertRaises(ModelPolicyError):
            check_ollama_model("myorg/llama3.2-indic-lora")
        self.assertEqual(check_ollama_model("myorg/llama3.2-indic-lora", allow_derivative=True), "derivative")
        with self.assertRaises(ModelPolicyError):  # opt-in does not let other families through
            check_ollama_model("myorg/qwen-llama-merge", allow_derivative=True)

    def test_backend_constructor_enforces(self):
        with self.assertRaises(ModelPolicyError):
            OllamaLLM("qwen2.5:1.5b")
        o = OllamaLLM()
        self.assertEqual((o.family, o.model), ("llama", "llama3.2:1b"))
        assert_final_pipeline_llm(o)


class GgufPolicy(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.d.cleanup()

    def p(self, fname, arch, name):
        path = os.path.join(self.d.name, fname)
        write_gguf(path, arch, name)
        return path

    def test_reads_general_metadata_and_skips_arrays(self):
        m = read_gguf_general(self.p("a.gguf", "llama", "Llama 3.2 1B Instruct"))
        self.assertEqual((m["general.architecture"], m["general.name"]), ("llama", "Llama 3.2 1B Instruct"))

    def test_llama_gguf_accepted(self):
        self.assertEqual(check_gguf(self.p("Llama-3.2-1B-Instruct-Q4_K_M.gguf", "llama", "Llama 3.2 1B Instruct")), "meta")

    def test_other_architectures_rejected(self):
        for arch, name in (("qwen2", "Qwen2.5 1.5B"), ("gemma2", "Gemma 2 2B"), ("phi3", "Phi 3 mini")):
            with self.assertRaises(ModelPolicyError, msg=arch):
                check_gguf(self.p(f"{arch}.gguf", arch, name))

    def test_llama_architecture_but_not_meta_rejected(self):
        for name in ("Mistral 7B Instruct", "TinyLlama 1.1B Chat", "Some Model"):
            with self.assertRaises(ModelPolicyError, msg=name):
                check_gguf(self.p("x.gguf", "llama", name))

    def test_bad_files(self):
        junk = os.path.join(self.d.name, "junk.gguf")
        with open(junk, "wb") as f:
            f.write(b"NOPE" + b"\0" * 32)
        with self.assertRaises(ModelPolicyError):
            check_gguf(junk)
        bad_ver = os.path.join(self.d.name, "v9.gguf")
        write_gguf(bad_ver, "llama", "Llama", version=9)
        with self.assertRaises(ModelPolicyError):
            check_gguf(bad_ver)


class FinalPipelineGuard(unittest.TestCase):
    def test_mock_and_unknown_refused(self):
        with self.assertRaises(ModelPolicyError):
            assert_final_pipeline_llm(MockLLM())
        with self.assertRaises(ModelPolicyError):
            assert_final_pipeline_llm(object())


if __name__ == "__main__":
    unittest.main()
