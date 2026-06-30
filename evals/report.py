"""Render a self-contained HTML report from a multi-variant run summary.

No dependencies, no external assets -- a single openable report.html.
"""

from __future__ import annotations

import html
from pathlib import Path

_CSS = """
:root { --bg:#0f1117; --card:#1a1d27; --line:#2a2f3d; --fg:#e6e8ee;
        --muted:#9aa3b2; --pass:#3fb950; --fail:#f85149; --accent:#58a6ff;
        --warn:#d29922; }
* { box-sizing:border-box; }
body { margin:0; padding:32px; background:var(--bg); color:var(--fg);
       font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
h1 { font-size:20px; margin:0 0 4px; }
h2 { font-size:13px; margin:28px 0 12px; color:var(--muted);
     text-transform:uppercase; letter-spacing:.06em; }
.sub { color:var(--muted); margin:0 0 24px; font-size:13px; }
.cards { display:flex; gap:12px; flex-wrap:wrap; }
.vcard { background:var(--card); border:1px solid var(--line); border-radius:10px;
         padding:16px 20px; min-width:200px; }
.vcard h3 { margin:0 0 12px; font-size:14px; }
.metric { display:flex; justify-content:space-between; gap:24px; padding:3px 0;
          font-variant-numeric:tabular-nums; }
.metric .k { color:var(--muted); }
.badge { display:inline-block; padding:3px 10px; border-radius:20px; font-weight:600;
         font-size:12px; }
.badge.pass { background:rgba(63,185,80,.15); color:var(--pass); }
.badge.fail { background:rgba(248,81,73,.15); color:var(--fail); }
.delta-better { color:var(--pass); } .delta-worse { color:var(--fail); }
table { width:100%; border-collapse:collapse; background:var(--card);
        border:1px solid var(--line); border-radius:10px; overflow:hidden; margin-bottom:8px; }
th,td { padding:9px 14px; text-align:left; border-bottom:1px solid var(--line); font-size:13px; }
th { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.04em; }
tr:last-child td { border-bottom:none; }
td.num { font-variant-numeric:tabular-nums; }
.tools { color:var(--accent); font-family:ui-monospace,Menlo,monospace; font-size:12px; }
.detail { color:var(--muted); font-size:12px; }
.recs { background:var(--card); border:1px solid var(--line); border-radius:10px;
        padding:8px 8px 8px 28px; }
.recs li { margin:6px 0; }
.prompt { background:var(--card); border:1px solid var(--line); border-radius:10px;
          padding:16px; color:var(--muted); white-space:pre-wrap; font-size:13px; }
.gate { padding:12px 16px; border-radius:10px; margin-bottom:8px; }
.gate.pass { background:rgba(63,185,80,.08); border:1px solid rgba(63,185,80,.3); }
.gate.fail { background:rgba(248,81,73,.08); border:1px solid rgba(248,81,73,.3); }
"""


def _badge(passed: bool) -> str:
    cls = "pass" if passed else "fail"
    return f'<span class="badge {cls}">{"PASS" if passed else "FAIL"}</span>'


def _variant_card(name: str, agg: dict) -> str:
    rows = [
        ("success", f"{agg['success_rate']:.0%}"),
        ("median cost", f"${agg['median_cost_usd']:.4f}"),
        ("median tools", f"{agg['median_tool_calls']:g}"),
        ("median turns", f"{agg['median_turns']:g}"),
        ("samples", str(agg["n"])),
    ]
    body = "".join(
        f'<div class="metric"><span class="k">{html.escape(k)}</span><span>{v}</span></div>'
        for k, v in rows
    )
    return f'<div class="vcard"><h3>{html.escape(name)}</h3>{body}</div>'


def render(summary: dict, out_path: Path) -> None:
    variants = summary["variants"]
    agg = summary["aggregate"]

    cards = "".join(_variant_card(v, agg[v]) for v in variants if v in agg)

    gate = summary.get("gate")
    gate_html = ""
    if gate is not None:
        cls = "pass" if gate["passed"] else "fail"
        reasons = (
            "<ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in gate["reasons"]) + "</ul>"
            if gate["reasons"]
            else "<p>No regression beyond thresholds.</p>"
        )
        gate_html = (
            f'<h2>Telemetry Gate (revised vs baseline)</h2>'
            f'<div class="gate {cls}">{_badge(gate["passed"])}{reasons}</div>'
        )

    recs = summary.get("recommendations", {}).get("items", [])
    recs_html = "<ul class='recs'>" + "".join(f"<li>{html.escape(x)}</li>" for x in recs) + "</ul>"

    # Per-variant run tables.
    tables = ""
    for v in variants:
        rows = ""
        for r in summary["runs"].get(v, []):
            tools = ", ".join(r["tool_calls"]) or "—"
            rows += (
                f"<tr><td class='num'>{r['run']}</td><td>{_badge(r['passed'])}</td>"
                f"<td class='num'>{r['num_turns']}</td><td class='tools'>{html.escape(tools)}</td>"
                f"<td class='num'>${r['total_cost_usd']:.4f}</td>"
                f"<td class='detail'>{html.escape(r['detail'])}</td></tr>"
            )
        tables += (
            f"<h2>Runs — {html.escape(v)}</h2><table>"
            "<tr><th>#</th><th>Result</th><th>Turns</th><th>Tool calls</th>"
            "<th>Cost</th><th>Detail</th></tr>" + rows + "</table>"
        )

    all_passed = all(r["passed"] for v in variants for r in summary["runs"].get(v, []))

    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>deadline-evals — {html.escape(summary['task_id'])}</title>
<style>{_CSS}</style></head><body>
<h1>deadline-evals — {html.escape(summary['task_id'])} {_badge(all_passed)}</h1>
<p class="sub">{html.escape(summary['timestamp'])} · variants: {html.escape(', '.join(variants))} · K={summary['k']}
 · <strong>variable under test: CLI docstrings</strong></p>

<h2>Variant comparison</h2>
<div class="cards">{cards}</div>
{gate_html}

<h2>Docstring recommendations</h2>
{recs_html}

{tables}

<h2>Prompt</h2>
<div class="prompt">{html.escape(summary['prompt'])}</div>
</body></html>"""
    out_path.write_text(doc)


def render_suite(summaries: list[dict], group: str, out_path: Path) -> None:
    """Consolidated report across all test cases (and models) in a suite run.

    One row per (task, model); columns per variant showing success + median tools.
    Highlights the best model per task family and any docstring proposals emitted.
    """
    # Collect the union of variants across all summaries for stable columns.
    variants: list[str] = []
    for s in summaries:
        for v in s.get("variants", []):
            if v not in variants:
                variants.append(v)

    head = "".join(f"<th>{html.escape(v)}<br>succ / tools</th>" for v in variants)
    rows = ""
    n_pass_total = n_total = 0
    for s in summaries:
        agg = s.get("aggregate", {})
        model = s.get("model", "default")
        cells = ""
        for v in variants:
            if v in agg:
                a = agg[v]
                ok = a["success_rate"] >= 1.0
                n_pass_total += 1 if ok else 0
                n_total += 1
                cells += (
                    f"<td class='num'><span class='{'ok' if ok else 'bad'}'>"
                    f"{a['success_rate']:.0%}</span> / {a['median_tool_calls']:g}t</td>"
                )
            else:
                cells += "<td class='num'>—</td>"
        draft = s.get("draft_error")
        note = f" <span class='detail'>(draft failed)</span>" if draft else ""
        rows += (
            f"<tr><td>{html.escape(s['task_id'])}</td>"
            f"<td class='tools'>{html.escape(model)}</td>{cells}"
            f"<td class='detail'>{note}</td></tr>"
        )

    overall = f"{n_pass_total}/{n_total} variant-runs at 100% success" if n_total else "no data"
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>deadline-evals suite — {html.escape(group)}</title>
<style>{_CSS}
.bad {{ color:var(--fail); }} .ok {{ color:var(--pass); }}
</style></head><body>
<h1>deadline-evals suite — {html.escape(group)}</h1>
<p class="sub">{len(summaries)} test cases · variants: {html.escape(', '.join(variants))} · {overall}</p>
<table>
<tr><th>Test case</th><th>Model</th>{head}<th></th></tr>
{rows}
</table>
<p class="sub">Per-case detail (transcripts, telemetry, any docstring proposals) is in each
test case's own folder alongside this report.</p>
</body></html>"""
    out_path.write_text(doc)
