from __future__ import annotations

import difflib
import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Dict, Optional

PRICING_PER_1K = {
    "gpt-4.1": {"input": 0.01, "output": 0.03},
    "gpt-4.1-mini": {"input": 0.002, "output": 0.008},
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "claude-sonnet": {"input": 0.003, "output": 0.015},
    "default": {"input": 0.001, "output": 0.003},
}


def flatten_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        preferred = []
        for key in ["content", "text", "output", "result", "message", "messages", "prompt", "prompts", "input"]:
            if key in value:
                preferred.append(flatten_text(value[key]))
        if preferred:
            return "\n".join(part for part in preferred if part)
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, (list, tuple, set)):
        return "\n".join(flatten_text(item) for item in value)
    return repr(value)


def estimate_tokens(text: str) -> int:
    normalized = (text or "").strip()
    if not normalized:
        return 0
    word_guess = len(normalized.split())
    char_guess = math.ceil(len(normalized) / 4)
    return max(word_guess, char_guess, 1)


def estimate_usage(input_payload: Any, output_payload: Any, usage: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    usage = dict(usage or {})
    input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    input_text = flatten_text(input_payload)
    output_text = flatten_text(output_payload)
    if input_tokens <= 0:
        input_tokens = estimate_tokens(input_text)
    if output_tokens <= 0:
        output_tokens = estimate_tokens(output_text)
    total_tokens = int(usage.get("total_tokens") or (input_tokens + output_tokens))
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "estimation_mode": "heuristic" if not usage else "mixed",
    }


def estimate_cost_usd(model: Optional[str], input_tokens: int, output_tokens: int) -> float:
    pricing = PRICING_PER_1K.get(model or "", PRICING_PER_1K["default"])
    cost = (input_tokens / 1000.0) * pricing["input"] + (output_tokens / 1000.0) * pricing["output"]
    return round(cost, 6)


def build_comparison(before: Any, after: Any, title: str = "input_vs_output") -> Dict[str, Any]:
    before_text = flatten_text(before)
    after_text = flatten_text(after)
    diff_lines = list(
        difflib.unified_diff(
            before_text.splitlines(),
            after_text.splitlines(),
            fromfile="input",
            tofile="output",
            lineterm="",
            n=1,
        )
    )
    preview = "\n".join(diff_lines[:24]) if diff_lines else "No textual delta detected."
    return {
        "title": title,
        "before_preview": before_text[:600],
        "after_preview": after_text[:600],
        "diff_preview": preview,
        "changed": before_text != after_text,
    }


@dataclass
class DeadLoopError(RuntimeError):
    details: Dict[str, Any]

    def __str__(self) -> str:
        return self.details.get("message", "dead loop intercepted")


class LoopGuard:
    def __init__(self, max_repeats: int = 3) -> None:
        self.max_repeats = max_repeats
        self._counts: Dict[str, int] = {}

    def observe(self, key: str, payload: Any = None) -> Dict[str, Any]:
        signature_source = flatten_text(payload)
        signature = hashlib.sha1(signature_source.encode("utf-8")).hexdigest()[:10]
        bucket = f"{key}:{signature}"
        repeat_count = self._counts.get(bucket, 0) + 1
        self._counts[bucket] = repeat_count
        details = {
            "loop_key": key,
            "signature": signature,
            "repeat_count": repeat_count,
            "max_repeats": self.max_repeats,
            "intercepted": repeat_count > self.max_repeats,
            "message": f"dead loop intercepted for {key} after {repeat_count} identical hops",
        }
        if details["intercepted"]:
            raise DeadLoopError(details)
        return details
