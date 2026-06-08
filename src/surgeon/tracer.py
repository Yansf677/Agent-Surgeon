from __future__ import annotations

import contextvars
import functools
import inspect
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .insights import build_comparison, estimate_cost_usd, estimate_usage
from .storage import TraceStore


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_repr(value: Any, max_length: int = 220) -> str:
    try:
        rendered = repr(value)
    except Exception as exc:  # pragma: no cover
        rendered = f"<repr failed: {exc}>"
    if len(rendered) > max_length:
        return rendered[: max_length - 3] + "..."
    return rendered


def _safe_data(value: Any, max_depth: int = 4) -> Any:
    if max_depth <= 0:
        return _safe_repr(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _safe_data(item, max_depth=max_depth - 1) for key, item in list(value.items())[:24]}
    if isinstance(value, (list, tuple, set)):
        return [_safe_data(item, max_depth=max_depth - 1) for item in list(value)[:24]]
    return _safe_repr(value)


def _error_payload(exc: BaseException) -> Dict[str, Any]:
    details = getattr(exc, "details", None)
    return {
        "type": exc.__class__.__name__,
        "message": str(exc),
        "repr": _safe_repr(exc),
        "details": _safe_data(details),
    }


@dataclass
class SpanHandle:
    recorder: "TraceRecorder"
    event_id: str
    run_id: str
    parent_id: Optional[str]
    name: str
    category: str
    framework: str
    started_perf: float
    started_at: str
    args: List[Any] = field(default_factory=list)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    module: Optional[str] = None
    function: Optional[str] = None
    thread: str = "MainThread"
    stack_token: Any = None
    run_token: Any = None
    track_context: bool = False
    token_usage: Dict[str, Any] = field(default_factory=dict)
    comparison: Dict[str, Any] = field(default_factory=dict)
    _result: Any = None
    _closed: bool = False

    def set_result(self, result: Any) -> None:
        self._result = result

    def update_metadata(self, **metadata: Any) -> None:
        self.metadata.update(metadata)

    def capture_tokens(
        self,
        input_tokens: int,
        output_tokens: int,
        total_tokens: Optional[int] = None,
        cost_usd: Optional[float] = None,
        model: Optional[str] = None,
        estimation_mode: str = "mixed",
    ) -> None:
        usage = {
            "input_tokens": int(input_tokens),
            "output_tokens": int(output_tokens),
            "total_tokens": int(total_tokens or (input_tokens + output_tokens)),
            "cost_usd": round(float(cost_usd or 0.0), 6),
            "model": model,
            "estimation_mode": estimation_mode,
        }
        self.token_usage = {key: value for key, value in usage.items() if value not in (None, "")}

    def capture_comparison(self, before: Any, after: Any, title: str = "input_vs_output") -> None:
        self.comparison = build_comparison(before, after, title=title)

    def annotate_llm(
        self,
        input_payload: Any,
        output_payload: Any,
        model: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
        title: str = "llm_input_vs_output",
    ) -> None:
        computed = estimate_usage(input_payload, output_payload, usage)
        cost_usd = estimate_cost_usd(model, computed["input_tokens"], computed["output_tokens"])
        self.capture_tokens(
            input_tokens=computed["input_tokens"],
            output_tokens=computed["output_tokens"],
            total_tokens=computed["total_tokens"],
            cost_usd=cost_usd,
            model=model,
            estimation_mode=computed.get("estimation_mode", "mixed"),
        )
        self.capture_comparison(input_payload, output_payload, title=title)

    def finish(self, result: Any = None, error: Optional[Dict[str, Any]] = None) -> None:
        if self._closed:
            return
        final_result = self._result if result is None else result
        ended_at = _utc_now_iso()
        duration_ms = round((time.perf_counter() - self.started_perf) * 1000, 2)
        event = {
            "id": self.event_id,
            "run_id": self.run_id,
            "parent_id": self.parent_id,
            "depth": self.metadata.get("depth", 0),
            "name": self.name,
            "category": self.category,
            "framework": self.framework,
            "function": self.function,
            "module": self.module,
            "args": _safe_data(self.args),
            "kwargs": _safe_data(self.kwargs),
            "result": None if error else _safe_data(final_result),
            "error": error,
            "metadata": _safe_data(self.metadata),
            "token_usage": _safe_data(self.token_usage),
            "comparison": _safe_data(self.comparison),
            "started_at": self.started_at,
            "ended_at": ended_at,
            "duration_ms": duration_ms,
            "thread": self.thread,
            "status": "error" if error else "ok",
        }
        self.recorder.store.append(event)
        if self.track_context and self.stack_token is not None:
            self.recorder._stack.reset(self.stack_token)
        if self.track_context and self.run_token is not None:
            self.recorder._run_id.reset(self.run_token)
        self._closed = True

    def __enter__(self) -> "SpanHandle":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is not None:
            self.finish(error=_error_payload(exc))
            return False
        self.finish()
        return False


class TraceRecorder:
    def __init__(self, store: Optional[TraceStore] = None) -> None:
        self.store = store or TraceStore()
        self._stack = contextvars.ContextVar("surgeon_stack", default=())
        self._run_id = contextvars.ContextVar("surgeon_run_id", default=None)

    def _build_handle(
        self,
        name: str,
        category: str,
        framework: str,
        args: Optional[List[Any]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        module: Optional[str] = None,
        function: Optional[str] = None,
        parent: Optional[SpanHandle] = None,
        run_id: Optional[str] = None,
        track_context: bool = False,
    ) -> SpanHandle:
        event_id = str(uuid.uuid4())
        current_stack = self._stack.get()
        parent_id = parent.event_id if parent is not None else (current_stack[-1] if current_stack else None)
        resolved_run_id = run_id or (parent.run_id if parent is not None else None) or self._run_id.get() or event_id

        run_token = None
        stack_token = None
        if track_context:
            if self._run_id.get() is None:
                run_token = self._run_id.set(resolved_run_id)
            stack_token = self._stack.set(current_stack + (event_id,))

        base_metadata = dict(metadata or {})
        base_metadata.setdefault("depth", len(current_stack) if parent is None else int(parent.metadata.get("depth", 0)) + 1)

        return SpanHandle(
            recorder=self,
            event_id=event_id,
            run_id=resolved_run_id,
            parent_id=parent_id,
            name=name,
            category=category,
            framework=framework,
            started_perf=time.perf_counter(),
            started_at=_utc_now_iso(),
            args=list(args or []),
            kwargs=dict(kwargs or {}),
            metadata=base_metadata,
            module=module,
            function=function,
            thread=threading.current_thread().name,
            stack_token=stack_token,
            run_token=run_token,
            track_context=track_context,
        )

    def trace(
        self,
        name: Optional[str] = None,
        category: str = "function",
        framework: str = "python",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            if inspect.iscoroutinefunction(func):
                raise TypeError("Agent-Surgeon currently supports sync functions only.")

            label = name or func.__name__

            @functools.wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                handle = self._build_handle(
                    name=label,
                    category=category,
                    framework=framework,
                    args=list(args),
                    kwargs=dict(kwargs),
                    metadata=metadata,
                    module=func.__module__,
                    function=func.__qualname__,
                    track_context=True,
                )
                result = None
                error = None
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as exc:
                    error = _error_payload(exc)
                    raise
                finally:
                    handle.finish(result=result, error=error)

            return wrapper

        return decorator

    def span(
        self,
        name: str,
        category: str = "span",
        framework: str = "generic",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SpanHandle:
        return self._build_handle(
            name=name,
            category=category,
            framework=framework,
            metadata=metadata,
            track_context=True,
        )

    def start_span(
        self,
        name: str,
        category: str = "span",
        framework: str = "generic",
        metadata: Optional[Dict[str, Any]] = None,
        parent: Optional[SpanHandle] = None,
        run_id: Optional[str] = None,
    ) -> SpanHandle:
        return self._build_handle(
            name=name,
            category=category,
            framework=framework,
            metadata=metadata,
            parent=parent,
            run_id=run_id,
            track_context=False,
        )

    def record_event(
        self,
        name: str,
        category: str = "event",
        framework: str = "generic",
        metadata: Optional[Dict[str, Any]] = None,
        result: Any = None,
        parent: Optional[SpanHandle] = None,
        run_id: Optional[str] = None,
    ) -> None:
        handle = self.start_span(
            name=name,
            category=category,
            framework=framework,
            metadata=metadata,
            parent=parent,
            run_id=run_id,
        )
        handle.finish(result=result)


surgeon = TraceRecorder()
