"""A run's results as Markdown: what passed, what failed and why, and what it cost."""

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from orchestrator.eval.cost import cold_start, summarise
from orchestrator.model_client import TurnUsage

Record = Mapping[str, Any]


def _failed_checks(record: Record) -> list[Mapping[str, Any]]:
    return [f for f in record["findings"] if not f["ok"]]


def _answered(records: Sequence[Record]) -> list[Record]:
    return [r for r in records if "usage" in r]


def cost_summary(records: Sequence[Record]) -> dict[str, dict[str, Any]]:
    return summarise((r["model"], TurnUsage(**r["usage"])) for r in _answered(records))


def cold_cost_summary(records: Sequence[Record]) -> dict[str, dict[str, Any]]:
    """The same answers priced as if each had found the prompt cache cold."""
    return summarise(
        (r["model"], cold_start([TurnUsage(**turn) for turn in r["turns"]]))
        for r in _answered(records)
    )


def _summary(run: Mapping[str, Any]) -> list[str]:
    records = run["records"]
    failed = [r for r in records if not r["passed"]]
    by_check = Counter(f["check"] for r in failed for f in _failed_checks(r))
    lines = [
        (
            f"- Run: {run['started_at']} to {run['finished_at']}"
            f" (judge {'on' if run['judged'] else 'off'})"
        ),
        f"- Questions: {len(records)}; passed {len(records) - len(failed)}, failed {len(failed)}",
        f"- Total cost: ${sum(r.get('cost_usd', 0) for r in records):.2f}",
    ]
    if by_check:
        checks = ", ".join(f"{check} ({count})" for check, count in by_check.most_common())
        lines = [*lines, f"- Failed checks: {checks}"]
    return lines


def _results_table(records: Sequence[Record]) -> list[str]:
    rows = ["| Id | Category | Result | Model | Tools | Cost | Failed checks |", "|" + " --- |" * 7]
    for r in records:
        checks = ", ".join(f["check"] for f in _failed_checks(r))
        model = r.get("model", "").removeprefix("claude-")
        rows = [
            *rows,
            (
                f"| {r['id']} | {r['category']} | {'pass' if r['passed'] else '**FAIL**'} | {model}"
                f" | {len(r.get('tool_calls', []))} | ${r.get('cost_usd', 0):.3f} | {checks} |"
            ),
        ]
    return rows


def _failure(record: Record) -> list[str]:
    lines = [f"### {record['id']}: {record['question']}", ""]
    lines += [f"- **{f['check']}**: {f['detail']}" for f in _failed_checks(record)]
    answer = (record.get("text") or "").strip()
    if answer:
        lines += ["", "Answer:", "", *(f"> {line}" for line in answer.splitlines())]
    return [*lines, ""]


def _derived(records: Sequence[Record]) -> list[str]:
    lines = []
    for r in records:
        detail = next((f["detail"] for f in r["findings"] if f["check"] == "derived_figures"), "")
        if detail:
            lines = [*lines, f"- {r['id']}: {detail}"]
    return lines


def _cost_table(records: Sequence[Record]) -> list[str]:
    header = (
        "| Model | Answers | Mean cost | p95 cost | Max cost | Mean cost, cold cache"
        " | p95 cost, cold cache | Uncached in | Cache read | Cache write | Out"
        " | Mean counted tokens | p95 counted tokens |"
    )
    rows = [header, "|" + " --- |" * 13]
    cold = cold_cost_summary(records)
    for model, s in sorted(cost_summary(records).items()):
        rows = [
            *rows,
            (
                f"| {model} | {s['answers']} | ${s['mean_cost_usd']:.4f} | ${s['p95_cost_usd']:.4f}"
                f" | ${s['max_cost_usd']:.4f} | ${cold[model]['mean_cost_usd']:.4f}"
                f" | ${cold[model]['p95_cost_usd']:.4f} | {s['mean_input_tokens']:,}"
                f" | {s['mean_cache_read_tokens']:,} | {s['mean_cache_write_tokens']:,}"
                f" | {s['mean_output_tokens']:,} | {s['mean_counted_tokens']:,}"
                f" | {s['p95_counted_tokens']:,} |"
            ),
        ]
    return rows


def render(run: Mapping[str, Any]) -> str:
    records = run["records"]
    failures = [line for r in records if not r["passed"] for line in _failure(r)]
    derived = _derived(records)
    sections = [
        "# Oddsmith eval run",
        "",
        *_summary(run),
        "",
        "## Results",
        "",
        *_results_table(records),
        "",
        "## Cost per answer",
        "",
        (
            "Token columns are means per answer. Counted tokens are what `DAILY_TOKEN_BUDGET`"
            " counts: all input (cached included) plus output. Cold-cache cost prices each"
            " answer as if the system prompt and tools were not cached when it started."
        ),
        "",
        *_cost_table(records),
        "",
        "## Failures",
        "",
        *(failures or ["None."]),
        "",
        "## Derived figures to review",
        "",
        (
            "Figures not in a tool result as such, but which simple arithmetic on tool values"
            " could explain."
        ),
        "",
        *(derived or ["None."]),
        "",
    ]
    return "\n".join(sections)
