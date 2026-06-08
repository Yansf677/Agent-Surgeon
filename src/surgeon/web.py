from __future__ import annotations

import argparse
import json
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Union

from .storage import TraceStore


def _load_events(trace_path: Union[str, Path]) -> List[Dict[str, Any]]:
    path = Path(trace_path)
    store = TraceStore(base_dir=path.parent, filename=path.name)
    return sorted(store.load(), key=lambda item: (item.get("started_at", ""), item.get("depth", 0)))


def _html(events: List[Dict[str, Any]], title: str) -> str:
    payload = json.dumps(events, ensure_ascii=False)
    template = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>__TITLE__</title>
  <style>
    :root { --ink:#182230; --muted:#667085; --accent:#6d5efc; --accent2:#ff7b72; --ok:#0f9f6e; --error:#e5484d; --paper:rgba(255,255,255,0.8); --shadow:0 20px 50px rgba(80,64,140,0.12); }
    * { box-sizing:border-box; }
    body { margin:0; font-family:Inter,ui-sans-serif,system-ui,-apple-system; color:var(--ink); background:radial-gradient(circle at top left, rgba(109,94,252,0.22), transparent 28%), radial-gradient(circle at top right, rgba(255,123,114,0.18), transparent 25%), linear-gradient(180deg, #fbfaf7 0%, #f6f3ee 100%); min-height:100vh; }
    .shell { max-width:1440px; margin:0 auto; padding:32px 24px 48px; }
    .hero,.panel { background:var(--paper); border:1px solid rgba(255,255,255,0.8); border-radius:28px; box-shadow:var(--shadow); backdrop-filter:blur(18px); }
    .hero { padding:28px; margin-bottom:20px; }
    .eyebrow { display:inline-flex; padding:8px 14px; border-radius:999px; background:rgba(109,94,252,0.1); color:var(--accent); font-size:13px; font-weight:700; letter-spacing:0.04em; text-transform:uppercase; }
    h1 { font-size:clamp(38px, 5vw, 74px); line-height:0.95; margin:18px 0 14px; max-width:920px; }
    .subcopy { color:var(--muted); font-size:18px; line-height:1.6; margin:0; max-width:900px; }
    .stats { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; margin-top:24px; }
    .stat { background:rgba(255,255,255,0.7); border:1px solid rgba(255,255,255,0.9); border-radius:22px; padding:18px; }
    .stat span { display:block; color:var(--muted); font-size:12px; letter-spacing:0.08em; text-transform:uppercase; }
    .stat strong { display:block; margin-top:8px; font-size:28px; }
    .toolbar { display:grid; grid-template-columns:1.4fr 1fr 1fr; gap:14px; margin-bottom:18px; }
    .panel { padding:18px; }
    input { width:100%; border:1px solid rgba(109,94,252,0.16); border-radius:16px; background:rgba(255,255,255,0.9); padding:14px 16px; font-size:15px; }
    .chipset { display:flex; flex-wrap:wrap; gap:10px; margin-top:12px; }
    .chip { border:0; cursor:pointer; border-radius:999px; padding:10px 14px; font-weight:600; color:var(--muted); background:rgba(109,94,252,0.08); }
    .chip.active { background:linear-gradient(135deg, var(--accent), #8f79ff); color:#fff; box-shadow:0 10px 24px rgba(109,94,252,0.24); }
    .layout { display:grid; grid-template-columns:minmax(0,2fr) 420px; gap:18px; align-items:start; }
    .timeline-grid { display:flex; flex-direction:column; gap:12px; }
    .card { position:relative; margin-left:calc(var(--depth) * 24px); border-radius:22px; background:rgba(255,255,255,0.86); border:1px solid rgba(255,255,255,0.92); padding:16px 18px; cursor:pointer; }
    .card::before { content:\"\"; position:absolute; left:-14px; top:18px; bottom:-12px; width:2px; background:linear-gradient(180deg, rgba(109,94,252,0.35), rgba(109,94,252,0)); }
    .card.root::before { display:none; }
    .card.selected { transform:translateY(-2px); box-shadow:0 18px 36px rgba(77,61,137,0.14); border-color:rgba(109,94,252,0.24); }
    .card.error { border-left:5px solid rgba(229,72,77,0.82); }
    .card.ok { border-left:5px solid rgba(15,159,110,0.82); }
    .top { display:flex; justify-content:space-between; gap:16px; align-items:flex-start; }
    .name { font-size:18px; font-weight:800; margin:0; }
    .meta { display:flex; flex-wrap:wrap; gap:8px; margin-top:8px; }
    .badge { border-radius:999px; padding:6px 10px; font-size:12px; font-weight:700; letter-spacing:0.03em; }
    .framework { background:rgba(109,94,252,0.1); color:var(--accent); }
    .category { background:rgba(31,41,55,0.08); color:#334155; }
    .status-ok { background:rgba(15,159,110,0.12); color:var(--ok); }
    .status-error { background:rgba(229,72,77,0.12); color:var(--error); }
    .usage { background:rgba(31,41,55,0.06); color:#334155; }
    .snippet { color:var(--muted); font-size:14px; line-height:1.5; margin-top:12px; white-space:pre-wrap; word-break:break-word; }
    .side { position:sticky; top:18px; }
    .kv { display:grid; gap:12px; }
    .row { padding:12px 14px; border-radius:18px; background:rgba(255,255,255,0.72); border:1px solid rgba(255,255,255,0.86); }
    .row span { display:block; color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:0.08em; margin-bottom:6px; }
    pre { margin:0; white-space:pre-wrap; word-break:break-word; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; line-height:1.55; color:#334155; }
    .empty { color:var(--muted); font-size:14px; padding:18px 4px; }
    @media (max-width:1100px) { .layout { grid-template-columns:1fr; } .side { position:static; } .stats,.toolbar { grid-template-columns:1fr 1fr; } }
    @media (max-width:720px) { .shell { padding:18px 14px 28px; } .stats,.toolbar { grid-template-columns:1fr; } .card { margin-left:calc(var(--depth) * 12px); } }
  </style>
</head>
<body>
  <div class=\"shell\">
    <section class=\"hero\">
      <div class=\"eyebrow\">Agent-Surgeon · Time-travel debugging</div>
      <h1>__TITLE__</h1>
      <p class=\"subcopy\">Token burn, prompt drift, and silent retry loops should not hide inside plain logs. Rewind the run, inspect every hop, and find the exact moment your agent went sideways.</p>
      <div class=\"stats\" id=\"stats\"></div>
    </section>
    <section class=\"toolbar\">
      <div class=\"panel\"><strong>Search the timeline</strong><div style=\"height:10px\"></div><input id=\"search\" placeholder=\"Filter by event name, framework, category, diff, result, or error...\" /></div>
      <div class=\"panel\"><strong>Status filter</strong><div class=\"chipset\" id=\"statusFilters\"></div></div>
      <div class=\"panel\"><strong>Framework filter</strong><div class=\"chipset\" id=\"frameworkFilters\"></div></div>
    </section>
    <section class=\"layout\">
      <div class=\"panel\"><div id=\"timeline\" class=\"timeline-grid\"></div></div>
      <aside class=\"panel side\"><h3>Event inspector</h3><p class=\"subcopy\" style=\"font-size:14px; max-width:none;\">Click any card to inspect args, outputs, token usage, cost, diff preview, and loop guard details.</p><div id=\"inspector\" class=\"kv\"></div></aside>
    </section>
  </div>
  <script id=\"trace-data\" type=\"application/json\">__PAYLOAD__</script>
  <script>
    var events = JSON.parse(document.getElementById("trace-data").textContent || "[]");
    var state = { status: "all", framework: "all", query: "", selected: null };
    var statsEl = document.getElementById("stats");
    var timelineEl = document.getElementById("timeline");
    var inspectorEl = document.getElementById("inspector");
    var searchEl = document.getElementById("search");
    var frameworks = ["all"].concat(Array.from(new Set(events.map(function (event) { return event.framework || "generic"; }))));
    var statuses = ["all", "ok", "error"];
    function compact(value) { if (value === null || value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) { return "-"; } var text = typeof value === "string" ? value : JSON.stringify(value, null, 2); return text.length > 420 ? text.slice(0, 417) + "..." : text; }
    function tokenUsage(event) { return event.token_usage || {}; }
    function renderStats() { var slowest = events.reduce(function (best, event) { return Number(event.duration_ms || 0) > Number(best.duration_ms || 0) ? event : best; }, events[0] || { duration_ms: 0, name: "n/a" }); var totalTokens = events.reduce(function (sum, event) { return sum + Number(tokenUsage(event).total_tokens || 0); }, 0); var totalCost = events.reduce(function (sum, event) { return sum + Number(tokenUsage(event).cost_usd || 0); }, 0).toFixed(6); var blockedLoops = events.filter(function (event) { return event.error && event.error.type === "DeadLoopError"; }).length; var failures = events.filter(function (event) { return event.status === "error"; }).length; var cards = [{ label: "Events captured", value: String(events.length) }, { label: "Tokens estimated", value: String(totalTokens) }, { label: "Cost estimated", value: "$" + totalCost }, { label: "Loop blocks", value: String(blockedLoops) }, { label: "Errors surfaced", value: String(failures) }, { label: "Slowest span", value: slowest.name + " · " + String(slowest.duration_ms) + "ms" }]; statsEl.innerHTML = ""; cards.forEach(function (stat) { var div = document.createElement("div"); div.className = "stat"; div.innerHTML = "<span>" + stat.label + "</span><strong>" + stat.value + "</strong>"; statsEl.appendChild(div); }); }
    function renderChips(container, values, key) { container.innerHTML = ""; values.forEach(function (value) { var button = document.createElement("button"); button.className = "chip" + (state[key] === value ? " active" : ""); button.textContent = value; button.addEventListener("click", function () { state[key] = value; render(); }); container.appendChild(button); }); }
    function matches(event) { var haystack = [event.name, event.framework, event.category, JSON.stringify(event.result), JSON.stringify(event.metadata), JSON.stringify(event.comparison), event.error ? JSON.stringify(event.error) : ""].join(" " ).toLowerCase(); return (state.status === "all" || event.status === state.status) && (state.framework === "all" || (event.framework || "generic") === state.framework) && (!state.query || haystack.indexOf(state.query.toLowerCase()) >= 0); }
    function renderInspector(event) { if (!event) { inspectorEl.innerHTML = "<div class=\"empty\">Pick an event on the left. The juicy details will show up here.</div>"; return; } var rows = [["Name", event.name], ["Framework", event.framework], ["Category", event.category], ["Status", event.status], ["Duration", String(event.duration_ms) + "ms"], ["Started at", event.started_at], ["Args", compact(event.args)], ["Kwargs", compact(event.kwargs)], ["Token usage", compact(event.token_usage)], ["Diff preview", compact((event.comparison || {}).diff_preview)], ["Before preview", compact((event.comparison || {}).before_preview)], ["After preview", compact((event.comparison || {}).after_preview)], ["Result", compact(event.result)], ["Metadata", compact(event.metadata)], ["Error", compact(event.error)]]; inspectorEl.innerHTML = rows.map(function (pair) { return "<div class=\"row\"><span>" + pair[0] + "</span><pre>" + pair[1] + "</pre></div>"; }).join(""); }
    function renderTimeline() { timelineEl.innerHTML = ""; var visible = events.filter(matches); if (!visible.length) { timelineEl.innerHTML = "<div class=\"empty\">No events match the current filters. Try a broader search.</div>"; return; } visible.forEach(function (event) { var usage = tokenUsage(event); var usageBadge = usage.total_tokens ? "<span class=\"badge usage\">" + usage.total_tokens + " tok · $" + String(usage.cost_usd || 0) + "</span>" : ""; var badges = "<span class=\"badge framework\">" + (event.framework || "generic") + "</span><span class=\"badge category\">" + (event.category || "span") + "</span><span class=\"badge " + (event.status === "error" ? "status-error" : "status-ok") + "\">" + (event.status || "ok") + "</span>" + usageBadge; var snippet = event.error ? compact(event.error) : compact((event.comparison || {}).diff_preview || event.result); var card = document.createElement("article"); card.className = "card " + event.status + " " + (!event.parent_id ? "root" : "") + " " + (state.selected === event.id ? "selected" : ""); card.style.setProperty("--depth", Number(event.depth || 0)); card.innerHTML = "<div class=\"top\"><div><div class=\"name\">" + event.name + "</div><div class=\"meta\">" + badges + "</div></div><strong>" + String(event.duration_ms) + "ms</strong></div><div class=\"snippet\">" + snippet + "</div>"; card.addEventListener("click", function () { state.selected = event.id; renderTimeline(); renderInspector(event); }); timelineEl.appendChild(card); }); if (!state.selected && visible[0]) { state.selected = visible[0].id; } var selected = visible.find(function (event) { return event.id === state.selected; }) || visible[0]; renderInspector(selected || null); }
    function render() { renderChips(document.getElementById("statusFilters"), statuses, "status"); renderChips(document.getElementById("frameworkFilters"), frameworks, "framework"); renderStats(); renderTimeline(); }
    searchEl.addEventListener("input", function (event) { state.query = event.target.value; renderTimeline(); });
    render();
  </script>
</body>
</html>"""
    return template.replace("__TITLE__", title).replace("__PAYLOAD__", payload)


def export_html_report(trace_path: Union[str, Path] = ".surgeon/trace.json", output_path: Union[str, Path] = ".surgeon/report.html") -> Path:
    events = _load_events(trace_path)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_html(events, "Time-travel debugging for your LLM agents"), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a local Agent-Surgeon HTML replay")
    parser.add_argument("trace_path", nargs="?", default=".surgeon/trace.json")
    parser.add_argument("output_path", nargs="?", default=".surgeon/report.html")
    parser.add_argument("--open", action="store_true", dest="should_open")
    args = parser.parse_args()
    output = export_html_report(args.trace_path, args.output_path)
    print(f"HTML report exported to {output}")
    if args.should_open:
        webbrowser.open(output.resolve().as_uri())


if __name__ == "__main__":
    main()
