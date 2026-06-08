from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from .tracer import SpanHandle, surgeon

try:  # pragma: no cover
    from langchain_core.callbacks import BaseCallbackHandler as _LangChainBase
except Exception:  # pragma: no cover
    class _LangChainBase(object):
        pass


class _CallbackRegistry:
    framework = "generic"

    def __init__(self, recorder=None) -> None:
        self.recorder = recorder or surgeon
        self._handles: Dict[str, SpanHandle] = {}

    def _normalize_id(self, value: Any) -> str:
        return str(value if value is not None else uuid.uuid4())

    def _handle(self, run_id: Any) -> Optional[SpanHandle]:
        if run_id is None:
            return None
        return self._handles.get(str(run_id))

    def _parent_handle(self, parent_run_id: Any) -> Optional[SpanHandle]:
        return self._handle(parent_run_id)

    def _start(
        self,
        run_id: Any,
        name: str,
        category: str,
        parent_run_id: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        external_id = self._normalize_id(run_id)
        handle = self.recorder.start_span(
            name=name,
            category=category,
            framework=self.framework,
            metadata=metadata,
            parent=self._parent_handle(parent_run_id),
        )
        self._handles[external_id] = handle
        return external_id

    def _finish(self, run_id: Any, result: Any = None, error: Optional[BaseException] = None, metadata: Optional[Dict[str, Any]] = None) -> None:
        external_id = str(run_id)
        handle = self._handles.pop(external_id, None)
        if handle is None:
            return
        if metadata:
            handle.update_metadata(**metadata)
        if error is not None:
            handle.finish(error={
                "type": error.__class__.__name__,
                "message": str(error),
                "repr": repr(error),
            })
            return
        handle.finish(result=result)


class LangChainTraceHandler(_LangChainBase, _CallbackRegistry):
    framework = "langchain"

    def __init__(self, recorder=None) -> None:
        _CallbackRegistry.__init__(self, recorder=recorder)

    def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], run_id: Any, parent_run_id: Any = None, **kwargs: Any) -> None:
        name = serialized.get("name") or "/".join(serialized.get("id", ["chain"])) or "chain"
        self._start(run_id, f"chain:{name}", "chain", parent_run_id=parent_run_id, metadata={"inputs": inputs, "serialized": serialized, "extra": kwargs})

    def on_chain_end(self, outputs: Dict[str, Any], run_id: Any, **kwargs: Any) -> None:
        self._finish(run_id, result=outputs, metadata={"extra": kwargs})

    def on_chain_error(self, error: BaseException, run_id: Any, **kwargs: Any) -> None:
        self._finish(run_id, error=error, metadata={"extra": kwargs})

    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, run_id: Any, parent_run_id: Any = None, **kwargs: Any) -> None:
        name = serialized.get("name") or "/".join(serialized.get("id", ["tool"])) or "tool"
        self._start(run_id, f"tool:{name}", "tool", parent_run_id=parent_run_id, metadata={"input": input_str, "serialized": serialized, "extra": kwargs})

    def on_tool_end(self, output: Any, run_id: Any, **kwargs: Any) -> None:
        self._finish(run_id, result=output, metadata={"extra": kwargs})

    def on_tool_error(self, error: BaseException, run_id: Any, **kwargs: Any) -> None:
        self._finish(run_id, error=error, metadata={"extra": kwargs})

    def on_llm_start(self, serialized: Dict[str, Any], prompts: Any, run_id: Any, parent_run_id: Any = None, **kwargs: Any) -> None:
        name = serialized.get("name") or serialized.get("model") or "llm"
        self._start(
            run_id,
            f"llm:{name}",
            "llm",
            parent_run_id=parent_run_id,
            metadata={"prompts": prompts, "serialized": serialized, "model": name, "extra": kwargs},
        )

    def on_llm_end(self, response: Any, run_id: Any, **kwargs: Any) -> None:
        handle = self._handle(run_id)
        if handle is not None:
            handle.annotate_llm(
                input_payload=handle.metadata.get("prompts"),
                output_payload=response,
                model=handle.metadata.get("model"),
                usage=kwargs.get("usage") or (response.get("usage") if isinstance(response, dict) else None),
                title="langchain_llm_delta",
            )
        self._finish(run_id, result=response, metadata={"extra": kwargs})

    def on_llm_error(self, error: BaseException, run_id: Any, **kwargs: Any) -> None:
        self._finish(run_id, error=error, metadata={"extra": kwargs})


class OpenAIAgentsTracer(_CallbackRegistry):
    framework = "openai_agents"

    def on_agent_start(self, agent_name: str, input_payload: Any, run_id: Any = None, parent_run_id: Any = None, **kwargs: Any) -> str:
        external_id = self._normalize_id(run_id)
        return self._start(external_id, f"agent:{agent_name}", "agent", parent_run_id=parent_run_id, metadata={"input": input_payload, "extra": kwargs})

    def on_agent_end(self, run_id: Any, output: Any, **kwargs: Any) -> None:
        self._finish(run_id, result=output, metadata={"extra": kwargs})

    def on_tool_start(self, tool_name: str, input_payload: Any, run_id: Any = None, parent_run_id: Any = None, **kwargs: Any) -> str:
        external_id = self._normalize_id(run_id)
        return self._start(external_id, f"tool:{tool_name}", "tool", parent_run_id=parent_run_id, metadata={"input": input_payload, "extra": kwargs})

    def on_tool_end(self, run_id: Any, output: Any, **kwargs: Any) -> None:
        self._finish(run_id, result=output, metadata={"extra": kwargs})

    def on_llm_start(self, model: str, messages: Any, run_id: Any = None, parent_run_id: Any = None, **kwargs: Any) -> str:
        external_id = self._normalize_id(run_id)
        return self._start(external_id, f"llm:{model}", "llm", parent_run_id=parent_run_id, metadata={"messages": messages, "model": model, "extra": kwargs})

    def on_llm_end(self, run_id: Any, output: Any, usage: Optional[Dict[str, Any]] = None, **kwargs: Any) -> None:
        handle = self._handle(run_id)
        if handle is not None:
            handle.annotate_llm(
                input_payload=handle.metadata.get("messages"),
                output_payload=output,
                model=handle.metadata.get("model"),
                usage=usage,
                title="openai_agents_llm_delta",
            )
        extra = dict(kwargs)
        if usage:
            extra["usage"] = usage
        self._finish(run_id, result=output, metadata={"extra": extra})

    def on_error(self, run_id: Any, error: BaseException, **kwargs: Any) -> None:
        self._finish(run_id, error=error, metadata={"extra": kwargs})


class AutoGenTraceBridge(_CallbackRegistry):
    framework = "autogen"

    def on_conversation_start(self, agent_name: str, task: str, run_id: Any = None, parent_run_id: Any = None, **kwargs: Any) -> str:
        external_id = self._normalize_id(run_id)
        return self._start(external_id, f"conversation:{agent_name}", "conversation", parent_run_id=parent_run_id, metadata={"task": task, "extra": kwargs})

    def on_message(self, role: str, content: str, run_id: Any = None, parent_run_id: Any = None, **kwargs: Any) -> str:
        parent = self._parent_handle(parent_run_id)
        self.recorder.record_event(
            name=f"message:{role}",
            category="message",
            framework=self.framework,
            metadata={"content": content, "extra": kwargs},
            parent=parent,
            run_id=parent.run_id if parent is not None else None,
        )
        return self._normalize_id(run_id)

    def on_tool_start(self, tool_name: str, payload: Any, run_id: Any = None, parent_run_id: Any = None, **kwargs: Any) -> str:
        external_id = self._normalize_id(run_id)
        return self._start(external_id, f"tool:{tool_name}", "tool", parent_run_id=parent_run_id, metadata={"input": payload, "extra": kwargs})

    def on_tool_end(self, run_id: Any, output: Any, **kwargs: Any) -> None:
        self._finish(run_id, result=output, metadata={"extra": kwargs})

    def on_conversation_end(self, run_id: Any, summary: Any, **kwargs: Any) -> None:
        self._finish(run_id, result=summary, metadata={"extra": kwargs})

    def on_error(self, run_id: Any, error: BaseException, **kwargs: Any) -> None:
        self._finish(run_id, error=error, metadata={"extra": kwargs})
