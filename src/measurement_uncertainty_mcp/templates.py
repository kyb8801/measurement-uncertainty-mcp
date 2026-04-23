"""Uncertainty-budget template library (Issue #3).

A template is a fully specified uncertainty budget for a common measurement
task (CMM length, CD-SEM linewidth, DMM voltage, etc.). Each component is
given in its raw form (half-width, expanded value + k, Type A std + n) so a
user can read the budget line-by-line and see *why* each number is there,
then call :func:`apply_uncertainty_template` to get the GUM-compliant
combined + expanded uncertainty.

Tier policy (matches README pricing):

- ``list_uncertainty_templates`` is available on every tier. Listing is a
  catalog preview — users can browse what's in the library before upgrading.
- ``apply_uncertainty_template`` is Team-tier only. Applying a template is
  where the standards-reference value lives (audited, versioned budgets for
  lab certificates).

Tier is read from the environment variable ``MCP_TIER``
(one of ``free`` / ``pro`` / ``team``; default ``free``) so hosted deploys
can set it per-tenant without recompiling.
"""
from __future__ import annotations

import copy
import math
import os
from typing import Any

from .math_kernel import (
    UncertaintyComponent,
    combine_uncertainty,
    expanded_uncertainty,
    welch_satterthwaite,
)


# ---------------------------------------------------------------------------
# Tier gating
# ---------------------------------------------------------------------------

# Higher number = more capable tier. Team includes Pro includes Free.
_TIER_RANK = {"free": 0, "pro": 1, "team": 2}


def _current_tier() -> str:
    tier = os.getenv("MCP_TIER", "free").strip().lower()
    if tier not in _TIER_RANK:
        # Unknown value → be conservative, treat as free.
        return "free"
    return tier


def _require_tier(minimum: str) -> None:
    """Raise if the current process tier is below ``minimum``.

    The error text is deliberately actionable — users should know *exactly*
    which tier unlocks the feature and how to set it.
    """
    current = _current_tier()
    if _TIER_RANK[current] < _TIER_RANK[minimum]:
        raise PermissionError(
            f"This feature requires the '{minimum}' tier (current tier: "
            f"'{current}'). Upgrade at https://mcpize.com/mcp/"
            f"measurement-uncertainty, or set the env var MCP_TIER="
            f"{minimum} if you are self-hosting."
        )


# ---------------------------------------------------------------------------
# Template catalog
# ---------------------------------------------------------------------------

# Component spec schemas (inside a template):
#
#   {"name": "...", "type": "type_a",
#    "u": 0.0004, "dof": 9, "sensitivity": 1.0, "notes": "..."}
#
#   {"name": "...", "type": "type_b_normal",
#    "expanded_value": 0.0012, "k": 2.0, "sensitivity": 1.0, "notes": "..."}
#
#   {"name": "...", "type": "type_b_rectangular",
#    "half_width": 0.0003, "sensitivity": 1.0, "notes": "..."}
#
#   {"name": "...", "type": "type_b_triangular",
#    "half_width": 0.0003, "sensitivity": 1.0, "notes": "..."}
#
# `sensitivity` defaults to 1.0. `notes` is free-text guidance for the user.
# Every template stores all components in the measurand's SI-consistent unit
# listed at the template level — no hidden conversions.

TEMPLATES: dict[str, dict[str, Any]] = {
    # ----- Calibration-lab (2) ---------------------------------------------
    "cmm_length_10mm": {
        "id": "cmm_length_10mm",
        "name": "CMM length calibration at 10 mm nominal",
        "industry": "calibration_lab",
        "measurand": "length",
        "unit": "mm",
        "nominal_value": 10.0,
        "description": (
            "Coordinate-measuring-machine point-to-point length against a "
            "calibrated gauge block. ISO 10360-2 probing-error model."
        ),
        "references": ["ISO 10360-2:2009", "EURAMET cg-10 v2.1", "JCGM 100:2008"],
        "default_confidence": 0.95,
        "components": [
            {
                "name": "probing_error",
                "type": "type_b_normal",
                "expanded_value": 0.0012,
                "k": 2.0,
                "notes": "MPE_E from ISO 10360-2 acceptance test (±1.2 µm @ k=2).",
            },
            {
                "name": "gauge_block_cal",
                "type": "type_b_normal",
                "expanded_value": 0.0005,
                "k": 2.0,
                "notes": "Gauge block calibration certificate (±0.5 µm @ k=2).",
            },
            {
                "name": "temperature_variation",
                "type": "type_b_triangular",
                "half_width": 0.00030,
                "notes": (
                    "Thermal expansion mismatch across 19–21 °C lab excursion "
                    "(triangular: gauge and CMM scale reach equilibrium)."
                ),
            },
            {
                "name": "repeatability",
                "type": "type_a",
                "u": 0.000126,  # s/√n with s=0.0004 mm, n=10
                "dof": 9,
                "notes": "Pooled std of 10 replicate probings, Bessel-corrected.",
            },
        ],
    },
    "dmm_dc_voltage_10v": {
        "id": "dmm_dc_voltage_10v",
        "name": "DMM DC voltage calibration at 10 V",
        "industry": "calibration_lab",
        "measurand": "voltage",
        "unit": "V",
        "nominal_value": 10.0,
        "description": (
            "6½-digit DMM on DC 10 V range, compared against a Fluke 732B-"
            "class Zener reference. Budget mirrors typical NIM-level labs."
        ),
        "references": ["NIST TN 1297", "EURAMET cg-15", "JCGM 100:2008"],
        "default_confidence": 0.95,
        "components": [
            {
                "name": "reference_standard_cal",
                "type": "type_b_normal",
                "expanded_value": 20e-6,
                "k": 2.0,
                "notes": "Zener reference calibration (±20 µV @ k=2).",
            },
            {
                "name": "dmm_resolution",
                "type": "type_b_rectangular",
                "half_width": 1e-6,
                "notes": "6½-digit display quantization on 10 V range (1 µV LSD).",
            },
            {
                "name": "short_term_stability",
                "type": "type_b_rectangular",
                "half_width": 5e-6,
                "notes": "24-h drift envelope of Zener at 23 °C (±5 µV).",
            },
            {
                "name": "temperature_coefficient",
                "type": "type_b_rectangular",
                "half_width": 8e-6,
                "notes": "Lab-temp excursion ±1 °C × tempco 4 ppm/°C.",
            },
            {
                "name": "repeatability",
                "type": "type_a",
                "u": 6.7e-7,  # s/√n with s=3 µV, n=20
                "dof": 19,
                "notes": "Std of 20 replicate readings, 30-s settle each.",
            },
        ],
    },

    # ----- Semiconductor (2) -----------------------------------------------
    "cdsem_linewidth_45nm": {
        "id": "cdsem_linewidth_45nm",
        "name": "CD-SEM linewidth at 45 nm nominal",
        "industry": "semiconductor",
        "measurand": "length",
        "unit": "nm",
        "nominal_value": 45.0,
        "description": (
            "Top-down CD-SEM measurement of a patterned gate linewidth at "
            "45 nm nominal. Budget used for CD SPC and wafer disposition."
        ),
        "references": [
            "SEMI MF1982",
            "ISMI CD uncertainty best-practices",
            "JCGM 100:2008",
        ],
        "default_confidence": 0.95,
        "components": [
            {
                "name": "magnification_calibration",
                "type": "type_b_normal",
                "expanded_value": 0.5,
                "k": 2.0,
                "notes": "NIST RM-8820 pitch standard (±0.5 nm @ k=2).",
            },
            {
                "name": "line_edge_roughness",
                "type": "type_b_normal",
                "expanded_value": 0.4,
                "k": 2.0,
                "notes": "3σ LER from SEM image post-processing (±0.4 nm @ k=2).",
            },
            {
                "name": "edge_detection_threshold",
                "type": "type_b_rectangular",
                "half_width": 0.2,
                "notes": "Algorithm sensitivity to threshold choice.",
            },
            {
                "name": "chamber_vibration",
                "type": "type_b_rectangular",
                "half_width": 0.15,
                "notes": "Floor-vibration transfer to stage at 45 nm magnification.",
            },
            {
                "name": "repeatability",
                "type": "type_a",
                "u": 0.0671,  # s/√n with s=0.3 nm, n=20
                "dof": 19,
                "notes": "Std of 20 consecutive measurements of the same feature.",
            },
        ],
    },
    "ocd_film_thickness_50nm": {
        "id": "ocd_film_thickness_50nm",
        "name": "OCD / spectroscopic-ellipsometry film thickness at 50 nm",
        "industry": "semiconductor",
        "measurand": "thickness",
        "unit": "nm",
        "nominal_value": 50.0,
        "description": (
            "Scatterometry / ellipsometry thin-film thickness readout on a "
            "single-layer SiO₂-on-Si reference. Model-fit dominated."
        ),
        "references": ["SEMI ME1344", "NIST SP 260-191", "JCGM 100:2008"],
        "default_confidence": 0.95,
        "components": [
            {
                "name": "model_fit_residual",
                "type": "type_b_triangular",
                "half_width": 0.8,
                "notes": "RMSE of fit residual across spectral band (triangular).",
            },
            {
                "name": "refractive_index",
                "type": "type_b_rectangular",
                "half_width": 0.5,
                "notes": "Published n(λ) uncertainty propagated to thickness.",
            },
            {
                "name": "stage_tilt",
                "type": "type_b_rectangular",
                "half_width": 0.3,
                "notes": "AOI drift from nominal 70° over one wafer.",
            },
            {
                "name": "repeatability",
                "type": "type_a",
                "u": 0.0632,  # s/√n with s=0.2 nm, n=10
                "dof": 9,
                "notes": "Std of 10 site re-measurements on the same coupon.",
            },
        ],
    },

    # ----- University / teaching lab (2) -----------------------------------
    "thermocouple_k_100c": {
        "id": "thermocouple_k_100c",
        "name": "Type-K thermocouple reading at 100 °C",
        "industry": "university",
        "measurand": "temperature",
        "unit": "C",
        "nominal_value": 100.0,
        "description": (
            "Classroom calibration of a Type-K thermocouple using an ice-"
            "bath reference junction and a 6½-digit DMM."
        ),
        "references": [
            "NIST Monograph 175 (Type K tables)",
            "JCGM 100:2008",
        ],
        "default_confidence": 0.95,
        "components": [
            {
                "name": "reference_standard_cal",
                "type": "type_b_normal",
                "expanded_value": 0.5,
                "k": 2.0,
                "notes": "PRT reference against which TC was calibrated (±0.5 °C @ k=2).",
            },
            {
                "name": "wire_inhomogeneity",
                "type": "type_b_rectangular",
                "half_width": 0.3,
                "notes": "Type-K batch-to-batch EMF drift across wire length.",
            },
            {
                "name": "reference_junction",
                "type": "type_b_rectangular",
                "half_width": 0.1,
                "notes": "Ice-bath temperature drift at 0.000 °C.",
            },
            {
                "name": "dmm_voltage",
                "type": "type_b_normal",
                "expanded_value": 0.02,
                "k": 2.0,
                "notes": "DMM uncertainty at 4 mV, propagated via Seebeck (~41 µV/°C).",
            },
            {
                "name": "repeatability",
                "type": "type_a",
                "u": 0.0447,  # s/√n with s=0.1 °C, n=5
                "dof": 4,
                "notes": "Std of 5 repeated dips in a stirred 100 °C bath.",
            },
        ],
    },
    "analytical_balance_500g": {
        "id": "analytical_balance_500g",
        "name": "Analytical balance — mass at 500 g",
        "industry": "university",
        "measurand": "mass",
        "unit": "g",
        "nominal_value": 500.0,
        "description": (
            "0.1-mg readability analytical balance, E2 mass standard. "
            "Budget suitable for teaching-lab gravimetric analysis."
        ),
        "references": ["OIML R 111-1", "JCGM 100:2008"],
        "default_confidence": 0.95,
        "components": [
            {
                "name": "mass_standard_cal",
                "type": "type_b_normal",
                "expanded_value": 0.00005,
                "k": 2.0,
                "notes": "OIML E2 500 g calibration certificate (±50 µg @ k=2).",
            },
            {
                "name": "drift",
                "type": "type_b_rectangular",
                "half_width": 0.00003,
                "notes": "Recalibration-interval drift window (±30 µg).",
            },
            {
                "name": "resolution",
                "type": "type_b_rectangular",
                "half_width": 5e-5,
                "notes": (
                    "0.1 mg LSD display quantization → rectangular half-width "
                    "= 0.5 × LSD = 0.05 mg = 5e-5 g."
                ),
            },
            {
                "name": "air_buoyancy",
                "type": "type_b_rectangular",
                "half_width": 0.00008,
                "notes": "Air-density variation across 1008–1020 hPa, ρ≈8 g/cm³.",
            },
            {
                "name": "repeatability",
                "type": "type_a",
                "u": 6.32e-6,  # s/√n with s=20 µg, n=10
                "dof": 9,
                "notes": "Std of 10 replicate weighings at 500 g.",
            },
        ],
    },
}


# ---------------------------------------------------------------------------
# Spec → UncertaintyComponent conversion
# ---------------------------------------------------------------------------


def _spec_to_uncertainty(spec: dict[str, Any]) -> UncertaintyComponent:
    """Turn a template component spec into a math_kernel UncertaintyComponent.

    Raises ValueError on unknown or malformed specs so the template author
    gets a fast signal, not a silent-wrong combined uncertainty.
    """
    t = spec.get("type")
    name = spec["name"]
    sensitivity = float(spec.get("sensitivity", 1.0))

    if t == "type_a":
        u = float(spec["u"])
        dof = float(spec.get("dof", math.inf))
        return UncertaintyComponent(name=name, value=u, sensitivity=sensitivity,
                                    degrees_of_freedom=dof)
    if t == "type_b_normal":
        U = float(spec["expanded_value"])
        k = float(spec.get("k", 2.0))
        if k <= 0:
            raise ValueError(f"{name}: k must be > 0")
        u = U / k
        dof = float(spec.get("dof", math.inf))
        return UncertaintyComponent(name=name, value=u, sensitivity=sensitivity,
                                    degrees_of_freedom=dof)
    if t == "type_b_rectangular":
        u = float(spec["half_width"]) / math.sqrt(3.0)
        dof = float(spec.get("dof", math.inf))
        return UncertaintyComponent(name=name, value=u, sensitivity=sensitivity,
                                    degrees_of_freedom=dof)
    if t == "type_b_triangular":
        u = float(spec["half_width"]) / math.sqrt(6.0)
        dof = float(spec.get("dof", math.inf))
        return UncertaintyComponent(name=name, value=u, sensitivity=sensitivity,
                                    degrees_of_freedom=dof)
    raise ValueError(f"{name}: unknown component type {t!r}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_uncertainty_templates(
    industry: str | None = None,
    measurand: str | None = None,
) -> dict[str, Any]:
    """Catalog of available uncertainty-budget templates.

    Free tier: returns id, name, industry, measurand, unit, nominal_value,
    description, references, component *names only*. The raw component
    numbers are Team-gated — otherwise the Team-only apply_* tool would add
    no value over scraping list_*.
    """
    hits = []
    for tpl in TEMPLATES.values():
        if industry and tpl["industry"] != industry:
            continue
        if measurand and tpl["measurand"] != measurand:
            continue
        hits.append({
            "id": tpl["id"],
            "name": tpl["name"],
            "industry": tpl["industry"],
            "measurand": tpl["measurand"],
            "unit": tpl["unit"],
            "nominal_value": tpl.get("nominal_value"),
            "description": tpl["description"],
            "references": tpl["references"],
            "component_names": [c["name"] for c in tpl["components"]],
            "n_components": len(tpl["components"]),
        })

    # Sort deterministically so catalog order doesn't drift between calls.
    hits.sort(key=lambda r: (r["industry"], r["measurand"], r["id"]))

    return {
        "tier": _current_tier(),
        "tier_note": (
            "Listing is free. apply_uncertainty_template is Team-tier."
            if _current_tier() != "team" else
            "Team tier — all apply_uncertainty_template calls unlocked."
        ),
        "filters": {"industry": industry, "measurand": measurand},
        "n_templates": len(hits),
        "templates": hits,
    }


def apply_uncertainty_template(
    template_id: str,
    overrides: dict[str, dict[str, Any]] | None = None,
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Compute the full GUM budget for a named template.

    `overrides` is an optional ``{component_name: {field: value, ...}}`` map
    that merges into the stored spec before evaluation — useful when a user's
    setup matches the shape of a template but has different numbers (e.g. a
    CD-SEM with a tighter repeatability, or a CMM at a different nominal).

    Returns:
        {
          "template": {id, name, industry, measurand, unit, nominal_value,
                       references, notes_per_component},
          "components": [{name, u, sensitivity, contribution, percent_of_variance}, ...],
          "combined_standard_uncertainty": u_c,
          "effective_dof": ν_eff,
          "expanded_uncertainty": U,
          "coverage_factor": k,
          "confidence": confidence,
        }

    Team-tier only (PermissionError from _require_tier if not set).
    """
    _require_tier("team")

    if template_id not in TEMPLATES:
        raise ValueError(
            f"Unknown template id {template_id!r}. "
            f"Call list_uncertainty_templates for the catalog."
        )

    tpl = copy.deepcopy(TEMPLATES[template_id])
    if overrides:
        by_name = {c["name"]: c for c in tpl["components"]}
        for cname, patch in overrides.items():
            if cname not in by_name:
                raise ValueError(
                    f"Override targets unknown component {cname!r} in "
                    f"template {template_id!r}. "
                    f"Known: {list(by_name)}"
                )
            by_name[cname].update(patch)

    components = [_spec_to_uncertainty(c) for c in tpl["components"]]

    combined = combine_uncertainty(components)
    dof_info = welch_satterthwaite(components)
    nu_eff = dof_info["effective_dof"]
    expanded = expanded_uncertainty(
        combined["combined_standard_uncertainty"],
        effective_dof=nu_eff,
        confidence=confidence,
    )

    return {
        "template": {
            "id": tpl["id"],
            "name": tpl["name"],
            "industry": tpl["industry"],
            "measurand": tpl["measurand"],
            "unit": tpl["unit"],
            "nominal_value": tpl.get("nominal_value"),
            "references": tpl["references"],
            "notes_per_component": {c["name"]: c.get("notes", "")
                                    for c in tpl["components"]},
        },
        "components": combined["components"],
        "combined_standard_uncertainty": combined["combined_standard_uncertainty"],
        "effective_dof": nu_eff,
        "expanded_uncertainty": expanded["expanded_uncertainty"],
        "coverage_factor": expanded["coverage_factor"],
        "confidence": confidence,
    }
