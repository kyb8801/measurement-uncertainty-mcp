"""JCGM 101:2008 Monte Carlo propagation tests.

These validate two things:
  1. In the regime where GUM's linear approximation holds (linear model,
     Gaussian inputs), MC matches GUM u_c to within ~0.3%.
  2. In a non-linear regime (y = exp(X)), MC diverges substantially from
     the linear GUM estimate — this is exactly the case JCGM 101 was
     designed to handle, and justifies this tool's existence.
"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from measurement_uncertainty_mcp.math_kernel import (  # noqa: E402
    InputQuantity,
    monte_carlo_propagate,
)


# ---------------------------------------------------------------------------
# Agreement with GUM on linear + Gaussian cases
# ---------------------------------------------------------------------------


def test_mc_linear_gaussian_matches_gum():
    """y = a + b, a~N(10, 0.3), b~N(5, 0.4). GUM: u_c = sqrt(0.09 + 0.16) = 0.5."""
    inputs = [
        InputQuantity("a", "normal", {"mean": 10.0, "std": 0.3}),
        InputQuantity("b", "normal", {"mean": 5.0, "std": 0.4}),
    ]
    r = monte_carlo_propagate("a + b", inputs, n_trials=200_000, seed=42)

    # Mean ≈ 15 within a few MC standard errors
    mc_mean_se = 0.5 / math.sqrt(200_000)
    assert abs(r["mean"] - 15.0) < 5 * mc_mean_se

    # Std uncertainty matches GUM u_c = 0.5 to better than 1 %
    relative_error = abs(r["standard_uncertainty"] - 0.5) / 0.5
    assert relative_error < 0.01, f"Got {r['standard_uncertainty']}, expected 0.5 (±1%)"


def test_mc_sum_of_three_standard_normals():
    """y = a + b + c, all N(0, 1). u_c = sqrt(3) ≈ 1.732."""
    inputs = [
        InputQuantity("a", "normal", {"mean": 0.0, "std": 1.0}),
        InputQuantity("b", "normal", {"mean": 0.0, "std": 1.0}),
        InputQuantity("c", "normal", {"mean": 0.0, "std": 1.0}),
    ]
    r = monte_carlo_propagate("a + b + c", inputs, n_trials=200_000, seed=7)
    expected = math.sqrt(3.0)
    assert abs(r["standard_uncertainty"] - expected) / expected < 0.01


def test_mc_uniform_matches_analytic():
    """y = X, X ~ U(-1, 1). u = 1/sqrt(3) ≈ 0.577."""
    inputs = [InputQuantity("X", "uniform", {"low": -1.0, "high": 1.0})]
    r = monte_carlo_propagate("X", inputs, n_trials=200_000, seed=11)
    expected = 1.0 / math.sqrt(3.0)
    assert abs(r["standard_uncertainty"] - expected) / expected < 0.02


def test_mc_triangular_matches_analytic():
    """y = X, X ~ Triangular(-1, 0, 1). u = 1/sqrt(6) ≈ 0.408."""
    inputs = [InputQuantity("X", "triangular", {"low": -1.0, "mode": 0.0, "high": 1.0})]
    r = monte_carlo_propagate("X", inputs, n_trials=200_000, seed=13)
    expected = 1.0 / math.sqrt(6.0)
    assert abs(r["standard_uncertainty"] - expected) / expected < 0.02


# ---------------------------------------------------------------------------
# Non-linear divergence from GUM (justifies the tool's existence)
# ---------------------------------------------------------------------------


def test_mc_exp_nonlinear_diverges_from_gum():
    """y = exp(X), X ~ N(0, 1).

    GUM linearization: c = ∂y/∂x|_{x=0} = exp(0) = 1  ⇒  u_linear = 1.

    True distribution of exp(X) is lognormal:
        E[Y]   = exp(1/2) ≈ 1.648721
        Var[Y] = (exp(1) - 1) * exp(1) ≈ 4.670774
        u_true = sqrt(Var[Y]) ≈ 2.161197

    So MC should give ~2.16 and diverge from GUM's 1.0 by >100 %.
    This is exactly the scenario JCGM 101 was written to handle.
    """
    inputs = [InputQuantity("X", "normal", {"mean": 0.0, "std": 1.0})]
    r = monte_carlo_propagate("exp(X)", inputs, n_trials=200_000, seed=3)

    u_true = math.sqrt((math.exp(1) - 1) * math.exp(1))  # ≈ 2.161
    rel_err = abs(r["standard_uncertainty"] - u_true) / u_true
    assert rel_err < 0.05, f"MC std {r['standard_uncertainty']} vs truth {u_true}"

    # And the GUM-linear estimate u=1 is >5 % away from the MC result
    gum_linear = 1.0
    divergence = abs(r["standard_uncertainty"] - gum_linear) / gum_linear
    assert divergence > 0.05, (
        f"Expected MC to diverge from GUM linear by > 5 %, got {divergence:.1%}"
    )

    # Mean also diverges from point estimate y0 = exp(0) = 1
    assert abs(r["mean"] - math.exp(0.5)) / math.exp(0.5) < 0.03


def test_mc_skewed_output_has_positive_skew():
    """Lognormal output should have positive skew."""
    inputs = [InputQuantity("X", "normal", {"mean": 0.0, "std": 0.5})]
    r = monte_carlo_propagate("exp(X)", inputs, n_trials=100_000, seed=5)
    assert r["skewness"] > 0.5, f"expected positive skew for exp(N), got {r['skewness']}"


# ---------------------------------------------------------------------------
# Input validation & safety
# ---------------------------------------------------------------------------


def test_mc_rejects_undefined_symbol():
    inputs = [InputQuantity("a", "normal", {"mean": 0.0, "std": 1.0})]
    try:
        monte_carlo_propagate("a + b", inputs, n_trials=1_000, seed=1)
    except ValueError as e:
        assert "undefined" in str(e).lower()
    else:
        raise AssertionError("should have raised for undefined symbol 'b'")


def test_mc_rejects_non_finite_outputs():
    """log(X) with X ~ N(0, 0.5) produces NaN for negative samples → should raise."""
    inputs = [InputQuantity("X", "normal", {"mean": 0.0, "std": 0.5})]
    try:
        monte_carlo_propagate("log(X)", inputs, n_trials=50_000, seed=2)
    except ValueError as e:
        assert "non-finite" in str(e).lower()
    else:
        raise AssertionError("should have raised for non-finite outputs")


def test_mc_blocks_import_trick():
    """AST gate must refuse __import__ tricks before they reach sympy's
    eval-based parser. A successful parse here would mean os.system ran.
    """
    inputs = [InputQuantity("a", "normal", {"mean": 0.0, "std": 1.0})]
    try:
        monte_carlo_propagate(
            "__import__('os').system('echo PWNED')",
            inputs,
            n_trials=1_000,
            seed=1,
        )
    except ValueError as e:
        # Must be caught by the AST gate, not by a downstream error.
        msg = str(e).lower()
        assert any(tok in msg for tok in ("disallowed", "dunder", "attribute")), (
            f"Expected AST-gate message, got {e!r}"
        )
    else:
        raise AssertionError("AST gate did not block __import__ trick")


def test_mc_blocks_attribute_access():
    inputs = [InputQuantity("x", "normal", {"mean": 1.0, "std": 0.1})]
    try:
        monte_carlo_propagate("x.__class__", inputs, n_trials=1_000, seed=1)
    except ValueError as e:
        assert "attribute" in str(e).lower() or "dunder" in str(e).lower()
    else:
        raise AssertionError("AST gate did not block attribute access")


def test_mc_blocks_lambda():
    inputs = [InputQuantity("x", "normal", {"mean": 0.0, "std": 1.0})]
    try:
        monte_carlo_propagate("(lambda q: q)(x)", inputs, n_trials=1_000, seed=1)
    except ValueError as e:
        assert "lambda" in str(e).lower() or "disallowed" in str(e).lower()
    else:
        raise AssertionError("AST gate did not block lambda")


def test_mc_rejects_duplicate_input_names():
    inputs = [
        InputQuantity("a", "normal", {"mean": 0.0, "std": 1.0}),
        InputQuantity("a", "normal", {"mean": 1.0, "std": 1.0}),
    ]
    try:
        monte_carlo_propagate("a", inputs, n_trials=1_000, seed=1)
    except ValueError as e:
        assert "unique" in str(e).lower()
    else:
        raise AssertionError("should have raised for duplicate input names")


def test_mc_coverage_interval_contains_target_fraction():
    """The reported coverage interval should contain ~coverage of the samples."""
    inputs = [InputQuantity("X", "normal", {"mean": 0.0, "std": 1.0})]
    r = monte_carlo_propagate("X", inputs, n_trials=200_000, coverage=0.95, seed=17)
    y_low, y_high = r["coverage_interval"]
    # For N(0,1), 95 % shortest interval ≈ [-1.96, 1.96]
    assert abs(y_low - (-1.96)) < 0.05
    assert abs(y_high - 1.96) < 0.05


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001 — surface all failures in CLI runner
            failed += 1
            print(f"  ✗ {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    sys.exit(0 if failed == 0 else 1)
