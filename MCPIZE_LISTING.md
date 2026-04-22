# MCPize listing draft — measurement-uncertainty

*Paste these fields directly into the MCPize publisher UI. Field names match MCPize's current form (verified against mcpize.com/publish as of 2026-04-17).*

---

## Field: Server name
```
measurement-uncertainty
```

## Field: Display title (shown in marketplace)
```
Measurement Uncertainty (GUM-compliant)
```

## Field: Tagline (max 80 chars)
```
GUM-compliant uncertainty analysis for AI agents, metrologists, and cal labs.
```

## Field: Long description (markdown-supported)
```markdown
The first Model Context Protocol server for **GUM-compliant measurement uncertainty analysis** — the standard every calibration lab, semiconductor metrology team, and research group already has to use but spends hours on in Excel.

### What you get
- **7 tools** implementing the Guide to the Expression of Uncertainty in Measurement (JCGM 100:2008):
  - `type_a_uncertainty` — statistical uncertainty from repeated samples
  - `type_b_rectangular`, `type_b_triangular`, `type_b_normal` — non-statistical distributions
  - `combine_uncertainty` — variance-based combination with sensitivity coefficients
  - `welch_satterthwaite` — effective degrees of freedom for mixed-type budgets
  - `expanded_uncertainty` — k-factor from Student-t at your chosen confidence level

### Why this beats a spreadsheet
- No formula cells that silently break after a paste
- Uses scipy.stats.t for exact critical values (not lookup tables)
- Deterministic, testable, versioned (v0.1.0 — 11/11 unit tests green)
- Works inside Claude, Cursor, and any MCP-aware client — no context switch to a calculator tab

### Who it's for
- **Calibration labs** (KOLAS, A2LA, UKAS) producing uncertainty budgets in every certificate
- **Semiconductor metrology** (CD-SEM, OCD, TEM, AFM) — pass/fail wafer dispositions with defensible numbers
- **AI QA engineers** building quality-control agents that reason about measurement uncertainty before flagging parts
- **Research groups** publishing in journals that require GUM-compliant uncertainty reporting

### Install
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

### Quick demo (what your AI sees)
> User: I ran a thickness measurement 5 times: 10.01, 10.03, 9.99, 10.02, 10.00 nm.
> The scope's datasheet says ±0.005 nm at k=2 resolution. Give me the full budget at 95%.
>
> AI: [calls type_a_uncertainty] u_A = 0.0071 nm (ν=4)
> [calls type_b_normal] u_B = 0.0025 nm (ν=∞)
> [calls combine_uncertainty] u_c = 0.00753 nm
> [calls welch_satterthwaite] ν_eff = 7.05
> [calls expanded_uncertainty at 0.95, ν_eff=7.05] k = 2.37, U = 0.0178 nm
> Result: 10.01 ± 0.018 nm at 95% confidence (k=2.37, ν_eff=7).

That would take 20 minutes in Excel. With this server, 8 seconds.

### Standards
Follows JCGM 100:2008 exactly. No shortcuts. Source in `math_kernel.py` cites the GUM section for each formula.

### Open source
MIT licensed. Source on GitHub. This listing exists because the convenience of "it runs where I already work" is worth more than re-implementing the same math for the 40th time.
```

## Field: Tags (comma-separated, max 10)
```
metrology, uncertainty, GUM, calibration, semiconductor, measurement, QA, scipy, mcp, python
```

## Field: Categories (pick from MCPize dropdown)
- Primary: **Science & Engineering**
- Secondary: **Developer Tools**

## Field: Pricing tiers
| Tier | Price | Included |
|---|---|---|
| **Free** | $0/mo | 50 tool calls/month; `type_a_*` and `type_b_*` only; community support |
| **Pro** | **$29/mo** | Unlimited calls; full toolset incl. `combine_*` / `welch_*` / `expanded_*`; JSON + LaTeX output; email support (≤5 business days) |
| **Team** | **$99/mo** | Pro + shared uncertainty-budget templates; audit log export; priority support (≤48h) |

## Field: Hero screenshot plan
Take 3 screenshots (1920×1080, light background, no personal data):
1. **Terminal**: `measurement-uncertainty-mcp` running, Claude Desktop's MCP panel showing tools green-dot-connected.
2. **Conversation**: The quick-demo above in a Claude Desktop conversation window.
3. **Code**: `tests/test_math_kernel.py` output showing `11/11 tests passed`.

## Field: Connection details
- **Transport**: stdio (MCP default)
- **Command**: `python -m measurement_uncertainty_mcp`
- **Package**: `measurement-uncertainty-mcp` on PyPI (after first publish) OR `pip install git+https://github.com/kyb8801/measurement-uncertainty-mcp`
- **Requirements**: Python ≥ 3.10, numpy, scipy, mcp

## Field: Changelog for v0.1.0
```
- Initial release.
- 7 MCP tools covering GUM Type A, Type B (rectangular / triangular / normal),
  combined standard uncertainty, Welch-Satterthwaite effective degrees of freedom,
  and expanded uncertainty with Student-t coverage factors.
- 11 unit tests all passing, covering normalization constants, known-answer cases
  at the boundary (t-dist vs normal), and numerical propagation sanity.
- MIT license, source on GitHub.
```

## Field: Support contact
```
kyb8801@gmail.com
```

## Field: Homepage URL
```
https://github.com/kyb8801/measurement-uncertainty-mcp
```
(Create the GitHub repo before submitting the listing; MCPize validates the URL.)

---

## MCPize submission checklist

- [ ] Create GitHub repo `kyb8801/measurement-uncertainty-mcp`, push the `mcp_servers/measurement-uncertainty-mcp/` folder.
- [ ] Publish v0.1.0 tag + release.
- [ ] (Optional) `twine upload dist/*` to PyPI if we want `pip install` without GitHub.
- [ ] Sign up at mcpize.com; verify email.
- [ ] Connect Stripe for payouts (Korean bank accounts are supported via Stripe Korea).
- [ ] Submit server listing with the fields above.
- [ ] Upload 3 screenshots.
- [ ] Set pricing tiers per table.
- [ ] Submit for review (MCPize typically reviews in 24–72h).
- [ ] Announce on X once approved. Draft tweet:
  > "World-first MCP server for GUM-compliant measurement uncertainty analysis just went live. 7 tools. For calibration labs, semiconductor metrology, research groups who are tired of re-Exceling the same math. $29/mo. [link]"

## What MCPize CANNOT automate away
1. **Identity verification** — MCPize requires ID check before any paid tier is enabled. KYC handshake.
2. **Stripe payout onboarding** — Stripe's own KYC + bank account connection.
3. **Screenshot capture** — must be taken manually on YB's machine (or by Claude-in-Chrome after login).
4. **Review reply** — if MCPize comes back with questions, only YB can respond.

Estimated total manual time: **45–90 minutes**, spread over 1–3 days including review waits.
