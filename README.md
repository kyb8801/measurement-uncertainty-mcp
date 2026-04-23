# measurement-uncertainty-mcp

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP Compatible](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io)
[![MCPize](https://mcpize.com/badge/@kyb8801/measurement-uncertainty)](https://mcpize.com/mcp/measurement-uncertainty)
[![GitHub stars](https://img.shields.io/github/stars/kyb8801/measurement-uncertainty-mcp?style=social)](https://github.com/kyb8801/measurement-uncertainty-mcp/stargazers)

**The first Model Context Protocol server for GUM-compliant measurement uncertainty analysis.**

Built for AI engineers, metrologists, and semiconductor equipment teams who need to compute Type A/B uncertainties, combined standard uncertainty, effective degrees of freedom, and expanded uncertainty directly from their LLM assistant — without leaving chat or switching to a spreadsheet.

Now live on MCPize: **https://measurement-uncertainty.mcpize.run**

## What this server does

Exposes 10 MCP tools that implement the **Guide to the Expression of Uncertainty in Measurement (GUM, JCGM 100:2008)** and its **Monte Carlo supplement (JCGM 101:2008)**:

| Tool | What it returns |
|---|---|
| `type_a_uncertainty` | Statistical uncertainty from a sample (n, mean, std, standard uncertainty, dof) |
| `type_b_rectangular` | Non-statistical uncertainty from a known half-width, uniform distribution (u = half_width / √3) |
| `type_b_triangular` | Same for triangular distribution (u = half_width / √6) |
| `type_b_normal` | Non-statistical uncertainty from a k-expanded value (u = U / k) |
| `combine_uncertainty` | Combined standard uncertainty from a list of components and sensitivities |
| `welch_satterthwaite` | Effective degrees of freedom from components |
| `expanded_uncertainty` | Expanded uncertainty with coverage factor k for a target confidence level |
| `monte_carlo_propagate` | **JCGM 101 Monte Carlo propagation** — output mean, standard uncertainty, shortest coverage interval, skewness, excess kurtosis. Use when the model is non-linear, inputs are non-Gaussian, or ν_eff is too small for k=2 to be valid |
| `list_uncertainty_templates` | Catalog of pre-built uncertainty budgets (CMM length, CD-SEM CD, DMM voltage, thermocouple, balance, OCD film thickness). Filters by industry / measurand. Free on every tier |
| `apply_uncertainty_template` | **Team tier.** Run a named template end-to-end — combine components, compute ν_eff, report U at target confidence. Accepts an `overrides` map so a template adapts to your setup without copy-paste |

The Python library also ships a `propagate(formula, estimates, components)` helper for numerical uncertainty propagation through an arbitrary callable — not exposed as an MCP tool because callables don't serialize over JSON, but directly importable from `measurement_uncertainty_mcp.math_kernel`.

## Who this is for

- **Semiconductor equipment engineers** doing CD-SEM, OCD, TEM, AFM, optical metrology. Wafer dispositions with proper uncertainty budgets, not hand-waved error bars.
- **Calibration labs** (KOLAS, A2LA, UKAS) that need uncertainty budgets in every certificate and spend hours in Excel on the same formulas.
- **AI engineers building quality-control agents** that must reason about measurement uncertainty before making a pass/fail call.
- **Research groups** publishing in journals that require GUM-compliant uncertainty reporting (AIP, IOP, Elsevier metrology titles).

## Why this is on MCPize, not just GitHub

Because uncertainty analysis is **recurring, high-value, and inherently metered** — a calibration lab runs these calculations 50–500 times per month. That's a subscription, not a one-time script purchase. And because the GUM is standards-referenceable but notoriously error-prone when implemented by non-metrologists, the value here is **correctness-as-a-service**, not code.

## Quickstart — hosted (no install)

Connect your MCP client directly to the live Cloud Run endpoint via MCPize. No Python, no dependencies, no config.

### Claude Desktop / Cursor / Windsurf / Cline (one-line)

```bash
npx -y mcpize connect @kyb8801/measurement-uncertainty --client claude
```

Replace `--client claude` with `cursor`, `windsurf`, or `cline` as needed.

### Claude Code CLI

```bash
claude mcp add --transport http "Measurement Uncertainty" https://measurement-uncertainty.mcpize.run
```

### Manual config (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "Measurement Uncertainty": {
      "url": "https://measurement-uncertainty.mcpize.run"
    }
  }
}
```

## Quickstart — local install (60 seconds)

For airgapped labs, offline use, or if you'd rather run locally:

```bash
# 1. Clone and install
git clone https://github.com/kyb8801/measurement-uncertainty-mcp.git
cd measurement-uncertainty-mcp
pip install -e .

# 2. Run the stdio server (will connect to any MCP client)
measurement-uncertainty-mcp
```

Then add this to `~/Library/Application Support/Claude/claude_desktop_config.json`
(macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "measurement-uncertainty": {
      "command": "python",
      "args": ["-m", "measurement_uncertainty_mcp"]
    }
  }
}
```

Restart Claude Desktop, then ask:

> "Compute the Type A uncertainty for these 10 CD-SEM measurements: 45.12, 45.08, 45.15, 45.11, 45.09, 45.13, 45.10, 45.14, 45.07, 45.12 nm. Report u, ν, and the expanded uncertainty at k=2."

## Uncertainty-budget templates (Team tier)

Six starter templates ship in v0.2, covering the most commonly recurring budgets in calibration, teaching, and fab metrology:

| Template id | Industry | Measurand | Nominal |
|---|---|---|---|
| `cmm_length_10mm` | calibration_lab | length | 10 mm |
| `dmm_dc_voltage_10v` | calibration_lab | voltage | 10 V |
| `cdsem_linewidth_45nm` | semiconductor | length | 45 nm |
| `ocd_film_thickness_50nm` | semiconductor | thickness | 50 nm |
| `thermocouple_k_100c` | university | temperature | 100 °C |
| `analytical_balance_500g` | university | mass | 500 g |

`list_uncertainty_templates` is free on every tier (previews component names, descriptions, and references). `apply_uncertainty_template` is **Team tier** — it reads the raw component numbers, combines them via the GUM chain, and returns `U` at the target confidence. Users can pass an `overrides` map keyed by component name to adapt a template to their own measurement setup.

Self-hosting? Set `MCP_TIER=team` in the server environment to unlock `apply_*`.

## Pricing (planned)

- **Free tier**: 50 calls / month, `type_a_uncertainty` + `type_b_*` only
- **Pro tier ($29/mo)**: unlimited, full toolset, `propagate` enabled, JSON and LaTeX export
- **Team tier ($99/mo)**: Pro + audit log, shared uncertainty-budget templates, support response ≤ 48h

MCPize revenue share: 85/15. Projected break-even: 5 Pro subscriptions.

## Status

- [x] Server skeleton
- [x] Tool definitions (10 tools, JSON Schema)
- [x] Math kernel (imports from `gumroad_products/python_data_analysis/05_uncertainty_analysis.py`)
- [x] MCPize deployment (live at `measurement-uncertainty.mcpize.run`, 2026-04-22)
- [x] Public beta — 10 tools discovered and callable
- [x] Cold-start optimization: scipy lazy import, cold p50 ~9× faster (#4)
- [x] Monte Carlo uncertainty propagation (GUM Supplement 1 / JCGM 101:2008, 2026-04-22) (#2)
- [x] Uncertainty-budget template library v1 — 6 seed templates, Team-tier gated (#3, 2026-04-23)
- [ ] First paid subscriber (target: 2026-05-10)
- [ ] Template library expansion: target 20 templates (pressure, torque, flow, dimensional, electrical)

## Differentiation

Searched mcp.so, Smithery, and MCPize on 2026-04-17 for: `uncertainty`, `metrology`, `calibration`, `GUM`, `measurement`. **Zero results.** This is first-mover territory in a niche that has ~10,000 paying professionals globally.

## Testing

```bash
pytest tests/        # kernel + monte carlo + templates — all 44 tests should pass
```

## License

MIT — see [LICENSE](LICENSE). Free for commercial use, attribution appreciated.
