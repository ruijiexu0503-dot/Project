from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def _repair_json_backslashes(text: str) -> str:
    """Escape model-emitted LaTeX backslashes inside JSON strings."""
    out: list[str] = []
    quoted = False
    i = 0
    while i < len(text):
        char = text[i]
        if char == '"':
            run = 0
            j = i - 1
            while j >= 0 and text[j] == "\\":
                run += 1
                j -= 1
            if run % 2 == 0:
                quoted = not quoted
            out.append(char)
            i += 1
            continue
        if quoted and char == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            valid = nxt in '"\\/'
            valid = valid or (nxt in "bfnrt" and not (i + 2 < len(text) and text[i + 2].isalpha()))
            valid = valid or (nxt == "u" and i + 5 < len(text)
                              and all(c in "0123456789abcdefABCDEF" for c in text[i + 2:i + 6]))
            if not valid:
                out.append("\\")
        out.append(char)
        i += 1
    return "".join(out)


def _loads_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(_repair_json_backslashes(text))


def extract_json(text: str) -> Any:
    text = re.sub(r"^\s*```(?:json)?", "", text.strip(), flags=re.I)
    text = re.sub(r"```\s*$", "", text).strip()
    try:
        return _loads_json(text)
    except json.JSONDecodeError:
        starts = [(text.find("["), "[", "]"), (text.find("{"), "{", "}")]
        starts = [x for x in starts if x[0] >= 0]
        if not starts: raise
        start, opener, closer = min(starts)
        depth = 0; quoted = False; escaped = False
        for i in range(start, len(text)):
            char = text[i]
            if quoted:
                if escaped: escaped = False
                elif char == "\\": escaped = True
                elif char == '"': quoted = False
            elif char == '"': quoted = True
            elif char == opener: depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0: return _loads_json(text[start:i+1])
        raise ValueError("No complete JSON value in model output")


@dataclass
class Generation:
    parsed: Any
    raw: str
    model: str
    timestamp: str


class TransformersLLM:
    def __init__(self, model: str, dtype: str = "auto", max_new_tokens: int = 2048,
                 device_map: str = "auto", require_cuda: bool = False,
                 enable_thinking: bool = False):
        import torch
        from transformers import AutoConfig, AutoModelForCausalLM, AutoModelForImageTextToText, AutoTokenizer
        if require_cuda and not torch.cuda.is_available():
            raise RuntimeError("CUDA is required by configuration, but no GPU is visible")
        requested = getattr(torch, dtype) if dtype not in {"auto", "float32"} else ("auto" if dtype == "auto" else torch.float32)
        self.model_name = model
        self.tokenizer = AutoTokenizer.from_pretrained(model, trust_remote_code=True, local_files_only=True)
        model_config = AutoConfig.from_pretrained(model, trust_remote_code=True, local_files_only=True)
        self.model_type = model_config.model_type
        self.enable_thinking = enable_thinking
        # Qwen2.5-VL and Qwen3.5 use the multimodal auto class. Text-only
        # variants (and future remote-code checkpoints) use the causal class.
        # Selecting from config avoids hard-coding one Qwen generation.
        multimodal_types = {"qwen2_5_vl", "qwen3_5", "qwen3_5_moe", "qwen3_vl", "qwen3_vl_moe"}
        auto_class = AutoModelForImageTextToText if model_config.model_type in multimodal_types else AutoModelForCausalLM
        self.model = auto_class.from_pretrained(
            model, torch_dtype=requested, device_map=device_map, trust_remote_code=True,
            low_cpu_mem_usage=True, local_files_only=True)
        self.model.eval(); self.max_new_tokens = max_new_tokens
        self._image_processor = None

    def generate_json(self, system: str, prompt: str, max_new_tokens: int | None = None) -> Generation:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        rendered = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True,
            enable_thinking=self.enable_thinking)
        inputs = self.tokenizer([rendered], padding=True, return_tensors="pt")
        prompt_length = inputs["input_ids"].shape[1]
        # device_map="auto" places this model on CUDA, while tokenizers return CPU tensors.
        # Keeping them together avoids slow/undefined cross-device generation behaviour.
        inputs = {name: tensor.to(self.model.device) for name, tensor in inputs.items()}
        generated = self.model.generate(**inputs, max_new_tokens=max_new_tokens or self.max_new_tokens,
                                        do_sample=False, repetition_penalty=1.05)
        trimmed = generated[:, prompt_length:]
        raw = self.tokenizer.batch_decode(trimmed, skip_special_tokens=True)[0].strip()
        return Generation(extract_json(raw), raw, self.model_name, datetime.now(timezone.utc).isoformat())

    def generate_json_with_images(self, system: str, prompt: str, image_paths: list[str],
                                  max_new_tokens: int | None = None) -> Generation:
        """Generate grounded JSON from local images using the checkpoint processor."""
        from PIL import Image
        from transformers import AutoProcessor
        if self._image_processor is None:
            self._image_processor = AutoProcessor.from_pretrained(
                self.model_name, trust_remote_code=True, local_files_only=True)
        images = []
        content = []
        for path in image_paths:
            image = Image.open(path).convert("RGB")
            image.thumbnail((1100, 1100))
            images.append(image)
            content.append({"type": "image", "image": image})
        content.append({"type": "text", "text": prompt})
        messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
        inputs = self._image_processor.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True, return_dict=True,
            return_tensors="pt", enable_thinking=self.enable_thinking)
        prompt_length = inputs["input_ids"].shape[1]
        inputs = {name: tensor.to(self.model.device) for name, tensor in inputs.items()}
        generated = self.model.generate(**inputs, max_new_tokens=max_new_tokens or self.max_new_tokens,
                                        do_sample=False, repetition_penalty=1.05)
        raw = self._image_processor.batch_decode(
            generated[:, prompt_length:], skip_special_tokens=True)[0].strip()
        for image in images:
            image.close()
        return Generation(extract_json(raw), raw, self.model_name, datetime.now(timezone.utc).isoformat())


def create_llm(config: dict[str, Any]) -> TransformersLLM:
    provider = config.get("provider")
    if provider != "transformers": raise ValueError(f"Unsupported LLM provider: {provider!r}")
    if not config.get("model"): raise ValueError("LLM model must be configured")
    return TransformersLLM(config["model"], config.get("dtype", "auto"), config.get("max_new_tokens", 2048),
                           config.get("device_map", "auto"), config.get("require_cuda", False),
                           config.get("enable_thinking", False))
