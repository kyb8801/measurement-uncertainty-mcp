"""Cold-start + warm-call benchmark for measurement_uncertainty_mcp.

What this measures
------------------
1. **Cold import**: time to `import measurement_uncertainty_mcp.math_kernel`
   from a fresh subprocess. This is what a Cloud Run cold instance pays the
   first time a tool call arrives.

2. **Cold first-call latency** per tool: time from module import to the end
   of the first call to that tool, in the same subprocess. For tools that
   need scipy (`expanded_uncertainty`), this includes the lazy scipy import.

3. **Warm repeat-call latency** (p50, p99): subsequent calls to the same tool
   in the same warm instance. No scipy import cost, no numpy JIT.

Why per-subprocess
------------------
Python caches module imports within a process (`sys.modules`), so re-importing
inside the same interpreter is free. A Cloud Run cold start is a fresh process
— so we spawn a subprocess per tool to get a realistic number.

Target numbers (issue #4):
- Cold p50 for `type_a_uncertainty`: ≤ 600 ms (was ~1200 ms)
- Cold p50 for tools that need scipy (`expanded_uncertainty`): ≤ 900 ms
- Warm p50 across the board: ≤ 10 ms
"""
from __future__ import annotations

import json
import statistics
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"

COLD_TRIALS = 5  # subprocess spawns per tool
WARM_CALLS = 100  # repeat calls inside one warm process


# Each entry: (label, python snippet that imports + calls the tool once,
#              python snippet that calls the tool repeatedly N times)
TOOLS = [
    (
        "type_a_uncertainty (numpy only, no scipy)",
        (
            "from measurement_uncertainty_mcp.math_kernel import type_a_uncertainty\n"
            "type_a_uncertainty([10.01, 10.03, 9.99, 10.02, 10.00])\n"
        ),
        (
            "from measurement_uncertainty_mcp.math_kernel import type_a_uncertainty\n"
            "samples = [10.01, 10.03, 9.99, 10.02, 10.00]\n"
            "for _ in range({N}):\n"
            "    type_a_uncertainty(samples)\n"
        ),
    ),
    (
        "type_b_rectangular (pure math, no scipy)",
        (
            "from measurement_uncertainty_mcp.math_kernel import type_b_rectangular\n"
            "type_b_rectangular(0.003)\n"
        ),
        (
            "from measurement_uncertainty_mcp.math_kernel import type_b_rectangular\n"
            "for _ in range({N}):\n"
            "    type_b_rectangular(0.003)\n"
        ),
    ),
    (
        "combine_uncertainty (pure math)",
        (
            "from measurement_uncertainty_mcp.math_kernel import (\n"
            "    UncertaintyComponent, combine_uncertainty,\n"
            ")\n"
            "combine_uncertainty([\n"
            "    UncertaintyComponent('a', 0.3),\n"
            "    UncertaintyComponent('b', 0.4),\n"
            "])\n"
        ),
        (
            "from measurement_uncertainty_mcp.math_kernel import (\n"
            "    UncertaintyComponent, combine_uncertainty,\n"
            ")\n"
            "comps = [UncertaintyComponent('a', 0.3), UncertaintyComponent('b', 0.4)]\n"
            "for _ in range({N}):\n"
            "    combine_uncertainty(comps)\n"
        ),
    ),
    (
        "expanded_uncertainty (scipy.stats, lazy)",
        (
            "from measurement_uncertainty_mcp.math_kernel import expanded_uncertainty\n"
            "expanded_uncertainty(0.1, effective_dof=10.0, confidence=0.95)\n"
        ),
        (
            "from measurement_uncertainty_mcp.math_kernel import expanded_uncertainty\n"
            "for _ in range({N}):\n"
            "    expanded_uncertainty(0.1, effective_dof=10.0, confidence=0.95)\n"
        ),
    ),
]


HARNESS_HEAD = (
    "import sys, time\n"
    f"sys.path.insert(0, r'{SRC}')\n"
    "t0 = time.perf_counter()\n"
)

HARNESS_TAIL_COLD = (
    "\nt1 = time.perf_counter()\n"
    "print(f'{(t1 - t0) * 1000.0:.3f}')\n"
)

HARNESS_TAIL_WARM = (
    "\nt1 = time.perf_counter()\n"
    "per_call_ms = (t1 - t_warm_start) * 1000.0 / {N}\n"
    "print(f'{per_call_ms:.6f}')\n"
)


def _run_cold(snippet: str) -> float:
    """Spawn a fresh python process, measure wall time from import to end."""
    code = HARNESS_HEAD + snippet + HARNESS_TAIL_COLD
    out = subprocess.check_output([sys.executable, "-c", code], text=True, timeout=30)
    return float(out.strip())


def _run_warm(snippet_n: str, n: int) -> float:
    """Import once, then call N times; return average per-call time in ms.

    Timer is reset *after* module import so we measure only the loop,
    not the one-time scipy/numpy import overhead.
    """
    body = snippet_n.format(N=n)
    loop_marker = f"for _ in range({n}):\n"
    assert loop_marker in body, f"warm snippet missing expected loop marker: {body!r}"
    setup, _, loop = body.partition(loop_marker)
    code = (
        HARNESS_HEAD
        + setup
        + "t_warm_start = time.perf_counter()\n"
        + loop_marker
        + loop
        + HARNESS_TAIL_WARM.replace("{N}", str(n))
    )
    out = subprocess.check_output([sys.executable, "-c", code], text=True, timeout=30)
    return float(out.strip())


def _summarize(samples: list[float]) -> dict:
    return {
        "n": len(samples),
        "p50_ms": round(statistics.median(samples), 3),
        "p99_ms": round(
            sorted(samples)[max(0, int(len(samples) * 0.99) - 1)], 3
        ),
        "min_ms": round(min(samples), 3),
        "max_ms": round(max(samples), 3),
    }


def main() -> int:
    print(f"Cold-start benchmark — {COLD_TRIALS} cold spawns × {len(TOOLS)} tools")
    print(f"Warm loop: {WARM_CALLS} repeat calls per tool")
    print("-" * 72)

    results = []
    for label, cold_snippet, warm_snippet_template in TOOLS:
        cold_samples = [_run_cold(cold_snippet) for _ in range(COLD_TRIALS)]
        warm_per_call = _run_warm(warm_snippet_template, WARM_CALLS)

        cold_summary = _summarize(cold_samples)
        print(f"\n{label}")
        print(
            f"  COLD  p50={cold_summary['p50_ms']:>7.2f} ms  "
            f"p99={cold_summary['p99_ms']:>7.2f} ms  "
            f"(n={cold_summary['n']}, min={cold_summary['min_ms']}, max={cold_summary['max_ms']})"
        )
        print(f"  WARM  per-call avg = {warm_per_call:.4f} ms  (n={WARM_CALLS})")

        results.append(
            {
                "tool": label,
                "cold": cold_summary,
                "warm_avg_ms": warm_per_call,
                "warm_n": WARM_CALLS,
            }
        )

    print("\n" + "-" * 72)
    print(json.dumps({"results": results}, indent=2))

    # Acceptance assertions (issue #4 targets)
    type_a_cold_p50 = results[0]["cold"]["p50_ms"]
    exp_unc_cold_p50 = results[3]["cold"]["p50_ms"]
    failed = []
    if type_a_cold_p50 > 600:
        failed.append(f"type_a cold p50 {type_a_cold_p50:.1f} ms > 600 ms target")
    if exp_unc_cold_p50 > 900:
        failed.append(f"expanded_uncertainty cold p50 {exp_unc_cold_p50:.1f} ms > 900 ms target")

    if failed:
        print("\nFAIL:", "; ".join(failed))
        return 1
    print("\nPASS: cold-start targets met.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
