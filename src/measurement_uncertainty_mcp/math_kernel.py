"""Math kernel for GUM-compliant uncertainty analysis.

All formulas follow JCGM 100:2008 (the Guide to the Expression of Uncertainty
in Measurement, a.k.a. "the GUM"). No shortcuts, no vibes — if a formula
isn't in the GUM or a ratified supplement, it's not here.

This module intentionally has no MCP-specific imports, so it can be unit-
tested and reused outside the server.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import math
from typing import Callable, Sequence

import numpy as np

# Scipy and sympy are imported lazily — they add ~700–900 ms and ~300–500 ms
# respectively to module import on cold-start Cloud Run instances.
# Type A / Type B / combine_uncertainty / welch_satterthwaite don't need either.
# Only expanded_uncertainty uses scipy; only monte_carlo_propagate uses sympy.
# See issue #4.
_stats = None  # populated by _get_stats() on first use
_sympy = None  # populated by _get_sympy() on first use


def _get_stats():
    """Lazy scipy.stats accessor.

    Returns the same module object on repeated calls within a warm instance,
    so the ~700–900 ms import cost is paid at most once per process.
    """
    global _stats
    if _stats is None:
        from scipy import stats as _scipy_stats  # noqa: WPS433 — intentional lazy import
        _stats = _scipy_stats
    return _stats


def _get_sympy():
    """Lazy sympy accessor (Monte Carlo formula parser)."""
    global _sympy
    if _sympy is None:
        import sympy as _mod  # noqa: WPS433 — intentional lazy import
        _sympy = _mod
    return _sympy


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
    stats = _get_stats()  # lazy scipy import — see issue #4
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


# --- Monte Carlo propagation (JCGM 101:2008) -------------------------------


@dataclass
class InputQuantity:
    """An input quantity for Monte Carlo propagation.

    `distribution` is the name of a supported sampling distribution:
      - "normal":      params = {"mean": μ, "std": σ}
      - "uniform":     params = {"low": a, "high": b}  OR  {"center": c, "half_width": h}
      - "triangular":  params = {"low": a, "mode": m, "high": b}
      - "lognormal":   params = {"mu": μ_log, "sigma": σ_log}   (μ, σ of log-variable)
      - "t":           params = {"mean": μ, "scale": s, "df": ν}
    """
    name: str
    distribution: str
    params: dict
    degrees_of_freedom: float = math.inf


_SUPPORTED_DISTRIBUTIONS = ("normal", "uniform", "rectangular", "triangular", "lognormal", "t")


# --- Formula-parsing security gate ------------------------------------------


# sympy.parse_expr internally uses eval() with the full Python builtins, which
# means naive parsing of an untrusted string like "__import__('os').system(...)"
# actually executes shell code. We validate the AST *before* letting sympy see
# it — this is a strict whitelist of operator/call/name nodes only.
_DANGEROUS_NAMES = frozenset({
    "__import__", "__builtins__", "__class__", "__subclasses__", "__bases__",
    "__mro__", "__globals__", "__dict__", "__getattribute__", "__getattr__",
    "eval", "exec", "compile", "open", "input", "breakpoint",
    "globals", "locals", "vars", "getattr", "setattr", "delattr",
    "exit", "quit", "help",
})

_FORBIDDEN_AST_NODES = (
    ast.Attribute,         # blocks "os.system", "obj.__class__"
    ast.Subscript,         # blocks "x[0]", which could index into dunders
    ast.Lambda,
    ast.GeneratorExp,
    ast.ListComp, ast.DictComp, ast.SetComp,
    ast.Starred,           # blocks "*args" unpacking
    ast.Yield, ast.YieldFrom,
    ast.Await,
    ast.JoinedStr,         # blocks f-strings with expression slots
    ast.FormattedValue,
    ast.NamedExpr,         # blocks walrus ":="
    ast.Dict, ast.DictComp, ast.Set,
    ast.List, ast.Tuple,   # formulas are scalars; no containers needed
)


def _validate_formula_ast(formula: str) -> None:
    """Reject anything more powerful than arithmetic-and-function-calls.

    This runs BEFORE sympy.parse_expr so we can block attribute access,
    subscripting, lambdas, and dunder identifiers — constructs that are
    not needed to express a measurement model and that could otherwise
    leak into Python's builtins via sympy's eval-based parser.
    """
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"Invalid formula syntax: {e}") from e

    for node in ast.walk(tree):
        if isinstance(node, _FORBIDDEN_AST_NODES):
            raise ValueError(
                f"Disallowed formula construct: {type(node).__name__}"
            )
        if isinstance(node, ast.Name):
            ident = node.id
            if ident in _DANGEROUS_NAMES:
                raise ValueError(f"Disallowed identifier: {ident!r}")
            if ident.startswith("__") and ident.endswith("__"):
                raise ValueError(f"Dunder identifiers are not allowed: {ident!r}")


def _sample_input(inp: InputQuantity, n: int, rng) -> np.ndarray:
    """Draw n samples from the input's distribution."""
    d = inp.distribution.lower()
    p = inp.params
    if d == "normal":
        return rng.normal(p["mean"], p["std"], n)
    if d in ("uniform", "rectangular"):
        if "low" in p and "high" in p:
            return rng.uniform(p["low"], p["high"], n)
        if "center" in p and "half_width" in p:
            c = p["center"]
            h = p["half_width"]
            return rng.uniform(c - h, c + h, n)
        raise ValueError(
            f"uniform needs (low,high) or (center,half_width); got params={p}"
        )
    if d == "triangular":
        return rng.triangular(p["low"], p["mode"], p["high"], n)
    if d == "lognormal":
        return rng.lognormal(p["mu"], p["sigma"], n)
    if d == "t":
        return p["mean"] + p["scale"] * rng.standard_t(p["df"], n)
    raise ValueError(
        f"Unsupported distribution '{inp.distribution}'. "
        f"Use one of: {_SUPPORTED_DISTRIBUTIONS}"
    )


def monte_carlo_propagate(
    formula: str,
    inputs: Sequence[InputQuantity],
    n_trials: int = 200_000,
    coverage: float = 0.95,
    seed: int | None = None,
) -> dict:
    """Monte Carlo uncertainty propagation per JCGM 101:2008 (GUM Supplement 1).

    Use this when any of the following hold:
      - The measurement model is strongly non-linear.
      - Input quantities have asymmetric or heavy-tailed distributions.
      - One dominant component is non-Gaussian.
      - The Welch-Satterthwaite effective dof is small and the k=2 multiplier
        is no longer a valid 95 % coverage factor.

    Parameters
    ----------
    formula : str
        Expression in sympy syntax. Variable names must match `inputs[*].name`.
        Examples: "V / I", "a + b", "exp(x)", "(a * b) / (c - d)".
    inputs : list of InputQuantity
        One entry per input quantity. See `InputQuantity` for distribution specs.
    n_trials : int
        Number of Monte Carlo trials. JCGM 101 recommends 1e6 for 3-digit
        coverage-interval accuracy; the default 200_000 is fast (~0.3 s) and
        typically matches u_c to within 0.3 %.
    coverage : float
        Target coverage probability for the reported interval (e.g. 0.95).
    seed : int or None
        RNG seed for reproducibility. None uses an OS-seeded RNG.

    Returns
    -------
    dict
        mean, standard_uncertainty, coverage, coverage_interval (shortest),
        skewness, excess_kurtosis, n_trials, formula.

    Notes
    -----
    - The coverage interval is the SHORTEST interval containing `coverage` of
      the output samples (JCGM 101 §7.7). For symmetric output distributions
      this matches the probabilistically-symmetric interval; for skewed ones
      (e.g. ratios, lognormal outputs) it is strictly tighter than y_mean ± U.
    - Formula parsing uses `sympy.parse_expr` with an empty `global_dict`,
      which forbids arbitrary Python evaluation — only named inputs and the
      default sympy math namespace (sin, cos, exp, log, sqrt, …) are allowed.
    - Correlated inputs are not yet supported in this release; inputs are
      sampled independently. (A future revision will accept a covariance
      structure and apply Cholesky factorization.)
    """
    if not 0.0 < coverage < 1.0:
        raise ValueError("coverage must be in (0, 1)")
    if n_trials < 1000:
        raise ValueError("n_trials should be >= 1000 for stable statistics")

    # AST-level safety gate — run *before* sympy so malicious strings never
    # reach sympy.parse_expr's internal eval() call.
    _validate_formula_ast(formula)

    sympy = _get_sympy()
    stats = _get_stats()

    input_names = [inp.name for inp in inputs]
    if len(set(input_names)) != len(input_names):
        raise ValueError("Input names must be unique")

    symbols = sympy.symbols(input_names)
    if not isinstance(symbols, (list, tuple)):
        symbols = (symbols,)
    local_dict = dict(zip(input_names, symbols))

    # parse_expr uses sympy's default global_dict — sympy math functions
    # (exp, log, sin, sqrt, …) are available; Python builtins like
    # __import__, eval, open are NOT in sympy's namespace, so they'd become
    # unresolved symbols and get caught by the free_symbols check below.
    try:
        expr = sympy.parse_expr(formula, local_dict=local_dict)
        # Coerce Python literals (int, float) into sympy Basic so the rest
        # of the code can rely on .free_symbols. Also defends against
        # malformed inputs that cause parse_expr to return non-Basic types.
        expr = sympy.sympify(expr)
    except Exception as e:
        raise ValueError(f"Could not parse formula {formula!r}: {e}") from e

    if not hasattr(expr, "free_symbols"):
        raise ValueError(
            f"Formula {formula!r} did not parse as a valid sympy expression"
        )

    free = {str(s) for s in expr.free_symbols}
    undefined = free - set(input_names)
    if undefined:
        raise ValueError(
            f"Formula references undefined inputs: {sorted(undefined)}. "
            f"Known inputs: {input_names}"
        )

    f = sympy.lambdify(symbols, expr, modules="numpy")

    rng = np.random.default_rng(seed)
    sample_arrays = [_sample_input(inp, n_trials, rng) for inp in inputs]

    y = np.asarray(f(*sample_arrays), dtype=float)
    # Scalar expressions (no input dependence) broadcast to a scalar.
    if y.ndim == 0:
        y = np.full(n_trials, float(y))

    if not np.all(np.isfinite(y)):
        n_bad = int((~np.isfinite(y)).sum())
        raise ValueError(
            f"{n_bad}/{n_trials} non-finite output samples — "
            f"check for division by zero, log of non-positive, etc."
        )

    y_mean = float(np.mean(y))
    y_std = float(np.std(y, ddof=1))
    y_skew = float(stats.skew(y))
    y_kurt = float(stats.kurtosis(y))

    # Shortest coverage interval (JCGM 101 §7.7)
    y_sorted = np.sort(y)
    n_cover = int(round(coverage * n_trials))
    if n_cover >= n_trials:
        n_cover = n_trials - 1
    widths = y_sorted[n_cover:] - y_sorted[: n_trials - n_cover]
    i_min = int(np.argmin(widths))
    y_low = float(y_sorted[i_min])
    y_high = float(y_sorted[i_min + n_cover])

    return {
        "n_trials": n_trials,
        "formula": formula,
        "mean": y_mean,
        "standard_uncertainty": y_std,
        "coverage": coverage,
        "coverage_interval": [y_low, y_high],
        "skewness": y_skew,
        "excess_kurtosis": y_kurt,
    }
