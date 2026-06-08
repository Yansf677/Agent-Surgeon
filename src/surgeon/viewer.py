from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from .storage import TraceStore


def _status_text(event: Dict[str, Any]) -> Text:
    return Text("ERROR", style="bold red") if event.get("error") else Text("OK", style="bold green")


def _pretty(value: Any, width: int = 160) -> str:
    if value in (None, "", [], {}):
        return "-"
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    return text if len(text) <= width else text[: width - 3] + "..."


def _token_brief(event: Dict[str, Any]) -> str:
    usage = event.get("token_usage") or {}
    if not usage:
        return ""
    total = usage.get("total_tokens", 0)
    cost = usage.get("cost_usd", 0)
    return "  {} tok  ${}".format(total, cost)


def _event_label(event: Dict[str, Any]) -> Text:
    status_icon = "✖" if event.get("error") else "●"
    style = "bold red" if event.get("error") else "bold cyan"
    label = Text("{} {}".format(status_icon, event.get("name")), style=style)
    label.append("  {}ms".format(event.get("duration_ms", 0)), style="magenta")
    label.append("  [{}/{}]".format(event.get("framework", "generic"), event.get("category", "span")), style="yellow")
    brief = _token_brief(event)
    if brief:
        label.append(brief, style="green")
    if event.get("error"):
        err = event["error"]
        label.append("  {}: {}".format(err.get("type", "Error"), err.get("message", "")), style="red")
    return label


def _add_detail(branch: Tree, event: Dict[str, Any]) -> None:
    detail = Table.grid(padding=(0, 1))
    detail.add_column(style="bold yellow", no_wrap=True)
    detail.add_column(style="white")
    detail.add_row("framework", event.get("framework") or "-")
    detail.add_row("category", event.get("category") or "-")
    detail.add_row("module", "{}::{}".format(event.get("module") or "-", event.get("function") or "-"))
    detail.add_row("args", _pretty(event.get("args")))
    detail.add_row("kwargs", _pretty(event.get("kwargs")))
    detail.add_row("result", _pretty(event.get("result")))
    detail.add_row("tokens", _pretty(event.get("token_usage")))
    detail.add_row("compare", _pretty((event.get("comparison") or {}).get("diff_preview")))
    detail.add_row("metadata", _pretty(event.get("metadata")))
    detail.add_row("thread", event.get("thread") or "-")
    detail.add_row("started", event.get("started_at") or "-")
    detail.add_row("status", _status_text(event))
    branch.add(detail)


def _build_tree(node: Tree, event: Dict[str, Any], children: Dict[Optional[str], List[Dict[str, Any]]]) -> None:
    branch = node.add(_event_label(event))
    _add_detail(branch, event)
    for child in children.get(event["id"], []):
        _build_tree(branch, child, children)


def render(trace_path: Union[str, Path] = ".surgeon/trace.json") -> None:
    path = Path(trace_path)
    store = TraceStore(base_dir=path.parent, filename=path.name)
    events = store.load()

    console = Console()
    if not events:
        console.print(Panel("No trace data found. Run python example.py first.", title="Agent-Surgeon", border_style="yellow"))
        return

    events = sorted(events, key=lambda item: (item.get("started_at", ""), item.get("depth", 0)))
    children: Dict[Optional[str], List[Dict[str, Any]]] = defaultdict(list)
    for event in events:
        children[event.get("parent_id")].append(event)

    errors = sum(1 for event in events if event.get("error"))
    total_tokens = sum(int((event.get("token_usage") or {}).get("total_tokens", 0)) for event in events)
    total_cost = round(sum(float((event.get("token_usage") or {}).get("cost_usd", 0.0)) for event in events), 6)
    blocked_loops = sum(1 for event in events if event.get("error") and event["error"].get("type") == "DeadLoopError")
    slowest = max(events, key=lambda item: item.get("duration_ms", 0))

    header = Table.grid(expand=True)
    header.add_column(justify="left")
    header.add_column(justify="right")
    header.add_row("[bold bright_white]Agent-Surgeon Timeline[/bold bright_white]", "[cyan]{}[/cyan]".format(path))
    header.add_row(
        "[green]{} events[/green] · [red]{} errors[/red] · [yellow]{} loops blocked[/yellow]".format(len(events), errors, blocked_loops),
        "[magenta]slowest: {} ({}ms)[/magenta]".format(slowest.get("name"), slowest.get("duration_ms")),
    )
    header.add_row("[cyan]{} tokens[/cyan]".format(total_tokens), "[green]${} estimated cost[/green]".format(total_cost))
    console.print(Panel(header, border_style="bright_blue"))

    for root in children.get(None, []):
        tree = Tree(_event_label(root), guide_style="bright_blue")
        _add_detail(tree, root)
        for child in children.get(root["id"], []):
            _build_tree(tree, child, children)
        console.print(tree)
        console.print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay Agent-Surgeon traces in the terminal")
    parser.add_argument("trace_path", nargs="?", default=".surgeon/trace.json")
    args = parser.parse_args()
    render(args.trace_path)


if __name__ == "__main__":
    main()
