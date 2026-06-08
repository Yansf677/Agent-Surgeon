from __future__ import annotations

import uuid
from functools import wraps
from typing import Any, Dict, Optional

from .insights import flatten_text
from .tracer import SpanHandle, surgeon

try:
    from langchain_core.callbacks import BaseCallbackHandler as _LangChainBase
except Exception:
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

    @property
    def always_verbose(self) -> bool:
        return True

    def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], run_id: Any, parent_run_id: Any = None, **kwargs: Any) -> None:
        serialized = serialized or {}
        name = serialized.get("name") or "/".join(serialized.get("id", ["chain"])) or "chain"
        self._start(run_id, "chain:{}".format(name), "chain", parent_run_id=parent_run_id, metadata={"inputs": inputs, "serialized": serialized, "extra": kwargs})

    def on_chain_end(self, outputs: Dict[str, Any], run_id: Any, **kwargs: Any) -> None:
        self._finish(run_id, result=outputs, metadata={"extra": kwargs})

    def on_chain_error(self, error: BaseException, run_id: Any, **kwargs: Any) -> None:
        self._finish(run_id, error=error, metadata={"extra": kwargs})

    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, run_id: Any, parent_run_id: Any = None, **kwargs: Any) -> None:
        serialized = serialized or {}
        name = serialized.get("name") or "/".join(serialized.get("id", ["tool"])) or "tool"
        self._start(run_id, "tool:{}".format(name), "tool", parent_run_id=parent_run_id, metadata={"input": input_str, "serialized": serialized, "extra": kwargs})

    def on_tool_end(self, output: Any, run_id: Any, **kwargs: Any) -> None:
        self._finish(run_id, result=output, metadata={"extra": kwargs})

    def on_tool_error(self, error: BaseException, run_id: Any, **kwargs: Any) -> None:
        self._finish(run_id, error=error, metadata={"extra": kwargs})

    def on_llm_start(self, serialized: Dict[str, Any], prompts: Any, run_id: Any, parent_run_id: Any = None, **kwargs: Any) -> None:
        serialized = serialized or {}
        name = serialized.get("name") or serialized.get("model_name") or serialized.get("model") or "llm"
        self._start(run_id, "llm:{}".format(name), "llm", parent_run_id=parent_run_id, metadata={"prompts": prompts, "serialized": serialized, "model": name, "extra": kwargs})

    def on_chat_model_start(self, serialized: Dict[str, Any], messages: Any, run_id: Any, parent_run_id: Any = None, **kwargs: Any) -> None:
        serialized = serialized or {}
        name = serialized.get("name") or serialized.get("model_name") or serialized.get("model") or "chat_model"
        self._start(run_id, "chat_model:{}".format(name), "llm", parent_run_id=parent_run_id, metadata={"messages": messages, "serialized": serialized, "model": name, "extra": kwargs})

    def on_llm_end(self, response: Any, run_id: Any, **kwargs: Any) -> None:
        handle = self._handle(run_id)
        if handle is not None:
            usage = None
            if isinstance(response, dict):
                usage = response.get("usage")
            handle.annotate_llm(
                input_payload=handle.metadata.get("prompts") or handle.metadata.get("messages"),
                output_payload=response,
                model=handle.metadata.get("model"),
                usage=usage,
                title="langchain_llm_delta",
            )
        self._finish(run_id, result=response, metadata={"extra": kwargs})

    def on_llm_error(self, error: BaseException, run_id: Any, **kwargs: Any) -> None:
        self._finish(run_id, error=error, metadata={"extra": kwargs})


class OpenAITracePatch:
    def __init__(self, recorder=None) -> None:
        self.recorder = recorder or surgeon
        self._patched = []

    def patch(self, client: Any) -> Any:
        self._patch_method(client.chat.completions, "create", endpoint="chat.completions")
        responses_api = getattr(client, "responses", None)
        if responses_api is not None:
            self._patch_method(responses_api, "create", endpoint="responses")
        return client

    def _patch_method(self, owner: Any, method_name: str, endpoint: str) -> None:
        if owner is None or not hasattr(owner, method_name):
            return
        original = getattr(owner, method_name)
        recorder = self.recorder

        @wraps(original)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            model = kwargs.get("model") or "openai"
            input_payload = kwargs.get("messages") or kwargs.get("input") or kwargs
            handle = recorder.start_span(
                name="openai:{}".format(endpoint),
                category="llm",
                framework="openai_sdk",
                metadata={"endpoint": endpoint, "model": model, "request": kwargs},
            )
            try:
                response = original(*args, **kwargs)
                output_payload, usage = self._extract_response(endpoint, response)
                handle.annotate_llm(
                    input_payload=input_payload,
                    output_payload=output_payload,
                    model=model,
                    usage=usage,
                    title="openai_sdk_delta",
                )
                handle.finish(result={
                    "endpoint": endpoint,
                    "model": model,
                    "output_preview": flatten_text(output_payload)[:600],
                })
                return response
            except Exception as exc:
                handle.finish(error={"type": exc.__class__.__name__, "message": str(exc), "repr": repr(exc)})
                raise

        setattr(owner, method_name, wrapped)
        self._patched.append((owner, method_name, original))

    def unpatch(self) -> None:
        for owner, method_name, original in reversed(self._patched):
            setattr(owner, method_name, original)
        self._patched = []

    def _extract_response(self, endpoint: str, response: Any) -> Any:
        usage = self._extract_usage(response)
        if endpoint == "chat.completions":
            content = []
            for choice in getattr(response, "choices", []) or []:
                message = getattr(choice, "message", None)
                content.append(getattr(message, "content", None))
            return content, usage
        if endpoint == "responses":
            text = getattr(response, "output_text", None)
            if text:
                return text, usage
        return repr(response), usage

    def _extract_usage(self, response: Any) -> Dict[str, Any]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return {}
        if isinstance(usage, dict):
            return usage
        return {
            "input_tokens": getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None) or getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }


def patch_openai_client(client: Any, recorder=None) -> OpenAITracePatch:
    patcher = OpenAITracePatch(recorder=recorder)
    patcher.patch(client)
    return patcher


class OpenAIAgentsTracer(_CallbackRegistry):
    framework = "openai_agents"

    def on_agent_start(self, agent_name: str, input_payload: Any, run_id: Any = None, parent_run_id: Any = None, **kwargs: Any) -> str:
        external_id = self._normalize_id(run_id)
        return self._start(external_id, "agent:{}".format(agent_name), "agent", parent_run_id=parent_run_id, metadata={"input": input_payload, "extra": kwargs})

    def on_agent_end(self, run_id: Any, output: Any, **kwargs: Any) -> None:
        self._finish(run_id, result=output, metadata={"extra": kwargs})

    def on_tool_start(self, tool_name: str, input_payload: Any, run_id: Any = None, parent_run_id: Any = None, **kwargs: Any) -> str:
        external_id = self._normalize_id(run_id)
        return self._start(external_id, "tool:{}".format(tool_name), "tool", parent_run_id=parent_run_id, metadata={"input": input_payload, "extra": kwargs})

    def on_tool_end(self, run_id: Any, output: Any, **kwargs: Any) -> None:
        self._finish(run_id, result=output, metadata={"extra": kwargs})

    def on_llm_start(self, model: str, messages: Any, run_id: Any = None, parent_run_id: Any = None, **kwargs: Any) -> str:
        external_id = self._normalize_id(run_id)
        return self._start(external_id, "llm:{}".format(model), "llm", parent_run_id=parent_run_id, metadata={"messages": messages, "model": model, "extra": kwargs})

    def on_llm_end(self, run_id: Any, output: Any, usage: Optional[Dict[str, Any]] = None, **kwargs: Any) -> None:
        handle = self._handle(run_id)
        if handle is not None:
            handle.annotate_llm(input_payload=handle.metadata.get("messages"), output_payload=output, model=handle.metadata.get("model"), usage=usage, title="openai_agents_llm_delta")
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
        return self._start(external_id, "conversation:{}".format(agent_name), "conversation", parent_run_id=parent_run_id, metadata={"task": task, "extra": kwargs})

    def on_message(self, role: str, content: str, run_id: Any = None, parent_run_id: Any = None, **kwargs: Any) -> str:
        parent = self._parent_handle(parent_run_id)
        self.recorder.record_event(name="message:{}".format(role), category="message", framework=self.framework, metadata={"content": content, "extra": kwargs}, parent=parent, run_id=parent.run_id if parent is not None else None)
        return self._normalize_id(run_id)

    def on_tool_start(self, tool_name: str, payload: Any, run_id: Any = None, parent_run_id: Any = None, **kwargs: Any) -> str:
        external_id = self._normalize_id(run_id)
        return self._start(external_id, "tool:{}".format(tool_name), "tool", parent_run_id=parent_run_id, metadata={"input": payload, "extra": kwargs})

    def on_tool_end(self, run_id: Any, output: Any, **kwargs: Any) -> None:
        self._finish(run_id, result=output, metadata={"extra": kwargs})

    def on_conversation_end(self, run_id: Any, summary: Any, **kwargs: Any) -> None:
        self._finish(run_id, result=summary, metadata={"extra": kwargs})

    def on_error(self, run_id: Any, error: BaseException, **kwargs: Any) -> None:
        self._finish(run_id, error=error, metadata={"extra": kwargs})
