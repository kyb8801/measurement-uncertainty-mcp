"""Math kernel for GUM-compliant uncertainty analysis.

All formulas follow JCGM 100:2008 (the Guide to the Expression of Uncertainty
in Measurement, a.k.a. "the GUM"). No shortcuts, no vibes — if a formula
isn't in the GUM or a ratified supplement, it's not here.

This module intentionally has no MCP-specific imports, so it can be unit-
tested and reused outside the server.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Sequence

import numpy as np
from scipy import stats


# --- Data structures --------------------------------------------------------


@dataclass
class UncertaintyComponent:
    """A single uncertainty contribution in a budget."""
    name: str
    value: float           # the standard uncertainty u(x_i)
    sensitivity: float = 1.0   # c_i = ∂f/∂x_i evaluated at the estimate
    degrees_of_freedom: float = math.inf  # ν_i; ∞ for Type B with no info

    @property
    def contribution(self) -> float:
        """c_i * u(x_i) — signed contribution to y."""
        return self.sensitivity * self.value

    @property
    def contribution_squared(self) -> float:
        """(c_i * u(x_i))^2 — variance contribution to u_c(y)^2."""
        return self.contribution ** 2


# --- Type A (statistical) ---------------------------------------------------


def type_a_uncertainty(samples: Sequence[float]) -> dict:
    """Standard uncertainty from a sample of n observations.

    GUM 4.2: u(x) = s / sqrt(n), with ν = n - 1.
    Uses Bessel-corrected sample standard deviation.
    """
    n = len(samples)
    if n < 2:
        raise ValueError("Need at least 2 samples for Type A evaluation")
    arr = np.asarray(samples, dtype=float)
    mean = float(arr.mean())
    std = float(arr.std(ddof=1))
    u = std / math.sqrt(n)
    return {
        "n": n,
        "mean": mean,
        "std": std,
        "standard_uncertainty": u,
        "degrees_of_freedom": n - 1,
    }


# --- Type B (non-statistical) -----------------------------------------------


def type_b_rectangular(half_width: float) -> dict:
    """Uniform distribution on [-a, a] → u = a / sqrt(3). ν = ∞."""
    u = half_width / math.sqrt(3.0)
    return {
        "distribution": "rectangular",
        "half_width": half_width,
        "standard_uncertainty": u,
        "degrees_of_freedom": math.inf,
    }


def type_b_triangular(half_width: float) -> dict:
    """Triangular distribution on [-a, a] → u = a / sqrt(6). ν = ∞."""
    u = half_width / math.sqrt(6.0)
    return {
        "distribution": "triangular",
        "half_width": half_width,
        "standard_uncertainty": u,
        "degrees_of_freedom": math.inf,
    }


def type_b_normal(expanded_value: float, k: float = 2.0) -> dict:
    """Normal (Gaussian) with known expanded value U at coverage factor k.

    u = U / k. The datasheet says ±U @ 95% → pass k=2.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    u = expanded_value / k
    return {
        "distribution": "normal",
        "expanded_value": expanded_value,
        "coverage_factor": k,
        "standard_uncertainty": u,
        "degrees_of_freedom": math.inf,
    }


# --- Combined standard uncertainty ------------------------------------------


def combine_uncertainty(components: Sequence[UncertaintyComponent]) -> dict:
    """Root sum-of-squares of sensitivity-weighted standard uncertainties.

    GUM 5.1.2 (uncorrelated inputs):
        u_c(y)^2 = Σ (c_i * u(x_i))^2
    """
    if not components:
        raise ValueError("Need at least one component")
    variance = sum(c.contribution_squared for c in components)
    uc = math.sqrt(variance)
    per_component = [
        {
            "name": c.name,
            "u": c.value,
            "sensitivity": c.sensitivity,
            "contribution": c.contribution,
            "percent_of_variance": 100.0 * c.contribution_squared / variance if variance else 0.0,
        }
        for c in components
    ]
    return {
        "combined_standard_uncertainty": uc,
        "variance": variance,
        "components": per_component,
    }


# --- Effective degrees of freedom -------------------------------------------


def welch_satterthwaite(components: Sequence[UncertaintyComponent]) -> dict:
    """Effective DOF via Welch-Satterthwaite (GUM G.4.2).

    ν_eff = u_c^4 / Σ( (c_i u_i)^4 / ν_i )
    Components with ν = ∞ contribute zero to the denominator.
    """
    num = sum(c.contribution_squared for c in components) ** 2
    denom = 0.0
    for c in components:
        if math.isfinite(c.degrees_of_freedom) and c.degrees_of_freedom > 0:
            denom += (c.contribution_squared ** 2) / c.degrees_of_freedom
    if denom == 0:
        return {"effective_dof": math.inf, "note": "All components have ν=∞; k from normal distribution"}
    return {"effective_dof": num / denom}


# --- Expanded uncertainty ---------------------------------------------------


_COVERAGE_LEVELS = {
    0.68: "k≈1 (approximate 68%)",
    0.90: "k=1.645 at ν=∞ (90%)",
    0.95: "k=1.96 at ν=∞ (95%)",
    0.99: "k=2.576 at ν=∞ (99%)",
}


def expanded_uncertainty(
    combined_uncertainty: float,
    effective_dof: float = math.inf,
    confidence: float = 0.95,
) -> dict:
    """U = k * u_c with k from Student-t at (confidence, ν_eff).

    Falls back to standard-normal critical values when ν_eff = ∞.
    """
    if confidence <= 0 or confidence >= 1:
        raise ValueError("confidence must be in (0, 1)")
    alpha = 1.0 - confidence
    if math.isfinite(effective_dof):
        k = float(stats.t.ppf(1 - alpha / 2, df=effective_dof))
    else:
        k = float(stats.norm.ppf(1 - alpha / 2))
    U = k * combined_uncertainty
    return {
        "expanded_uncertainty": U,
        "coverage_factor": k,
        "confidence": confidence,
        "effective_dof": effective_dof,
        "note": _COVERAGE_LEVELS.get(round(confidence, 2), ""),
    }


# --- Numerical propagation --------------------------------------------------


def propagate(
    formula: Callable[[dict], float],
    estimates: dict,
    components: Sequence[UncertaintyComponent],
    step_ratio: float = 1e-6,
) -> dict:
    """Compute u_c(y) by numerical partial derivatives of `formula`.

    Uses central differences with a step h_i = max(|x_i|*step_ratio, step_ratio).
    This is the GUM 5.1.2 formula but with c_i estimated numerically — handy
    when the user defines formula as a Python callable at runtime.
    """
    y0 = float(formula(estimates))
    sens: dict[str, float] = {}
    for c in components:
        if c.name not in estimates:
            raise KeyError(f"No estimate given for component '{c.name}'")
        x = float(estimates[c.name])
        h = max(abs(x) * step_ratio, step_ratio)
        up = dict(estimates); up[c.name] = x + h
        dn = dict(estimates); dn[c.name] = x - h
        sens[c.name] = (formula(up) - formula(dn)) / (2 * h)

    applied = [
        UncertaintyComponent(name=c.name, value=c.value,
                             sensitivity=sens[c.name],
                             degrees_of_freedom=c.degrees_of_freedom)
        for c in components
    ]
    combined = combine_uncertainty(applied)
    dof = welch_satterthwaite(applied)
    return {
        "y_estimate": y0,
        "sensitivities": sens,
        "combined_standard_uncertainty": combined["combined_standard_uncertainty"],
        "components": combined["components"],
        "effective_dof": dof.get("effective_dof"),
    }
