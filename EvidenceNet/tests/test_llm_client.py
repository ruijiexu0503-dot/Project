import json

from evidence_graph.llm_client import TransformersLLM, extract_json


class Tensor:
    def __init__(self, values): self.values = values; self.shape = (1, len(values))
    def to(self, device): self.device = device; return self


class Generated:
    def __getitem__(self, key):
        _, columns = key
        return self.values[columns]


class Tokenizer:
    def apply_chat_template(self, messages, tokenize, add_generation_prompt): return "prompt"
    def __call__(self, values, padding, return_tensors): return {"input_ids": Tensor([1, 2]), "attention_mask": Tensor([1, 1])}
    def batch_decode(self, values, skip_special_tokens): return [json.dumps({"ok": True})]


class Model:
    device = "cuda:0"
    def generate(self, **kwargs):
        assert kwargs["input_ids"].device == "cuda:0"
        result = Generated(); result.values = [[1, 2, 3]]
        return result


def test_generation_uses_mapping_input_ids_after_device_transfer():
    client = object.__new__(TransformersLLM)
    client.tokenizer = Tokenizer(); client.model = Model(); client.model_name = "test"; client.max_new_tokens = 10
    result = client.generate_json("system", "prompt")
    assert result.parsed == {"ok": True}


def test_extract_json_repairs_unescaped_latex_commands():
    parsed = extract_json(r'{"concept": "a \mathcal{L} loss and \frac{x}{y}"}')
    assert parsed["concept"] == r"a \mathcal{L} loss and \frac{x}{y}"


def test_extract_json_preserves_real_json_escapes():
    parsed = extract_json('{"text": "line one\\nline two"}')
    assert parsed == {"text": "line one\nline two"}
