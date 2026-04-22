"""Smoke tests for the math kernel. No MCP runtime needed."""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from measurement_uncertainty_mcp.math_kernel import (  # noqa: E402
    UncertaintyComponent,
    type_a_uncertainty,
    type_b_rectangular,
    type_b_triangular,
    type_b_normal,
    combine_uncertainty,
    welch_satterthwaite,
    expanded_uncertainty,
    propagate,
)


def test_type_a():
    result = type_a_uncertainty([10.01, 10.03, 9.99, 10.02, 10.00])
    assert result["n"] == 5
    assert abs(result["mean"] - 10.01) < 1e-9
    # std = 0.0158113883... → u = std/sqrt(5)
    assert abs(result["standard_uncertainty"] - 0.015811388300841896 / math.sqrt(5)) < 1e-12
    assert result["degrees_of_freedom"] == 4


def test_type_b_rectangular():
    result = type_b_rectangular(0.003)
    assert abs(result["standard_uncertainty"] - 0.003 / math.sqrt(3)) < 1e-15


def test_type_b_triangular():
    result = type_b_triangular(0.003)
    assert abs(result["standard_uncertainty"] - 0.003 / math.sqrt(6)) < 1e-15


def test_type_b_normal():
    result = type_b_normal(0.5, k=2.0)
    assert result["standard_uncertainty"] == 0.25


def test_combine_uncertainty():
    components = [
        UncertaintyComponent(name="u1", value=0.3, sensitivity=1.0),
        UncertaintyComponent(name="u2", value=0.4, sensitivity=1.0),
    ]
    r = combine_uncertainty(components)
    assert abs(r["combined_standard_uncertainty"] - 0.5) < 1e-12  # sqrt(0.09 + 0.16)


def test_welch_satterthwaite_finite():
    # Two type-A components: u1 with ν=4 (n=5), u2 with ν=9 (n=10)
    c = [
        UncertaintyComponent(name="a", value=0.1, degrees_of_freedom=4.0),
        UncertaintyComponent(name="b", value=0.1, degrees_of_freedom=9.0),
    ]
    res = welch_satterthwaite(c)
    # Equal variances, 2 * u^2 total → ν_eff = (2u^2)^2 / (u^4/4 + u^4/9)
    expected = (2 * 0.01) ** 2 / (0.0001 / 4 + 0.0001 / 9)
    assert abs(res["effective_dof"] - expected) < 1e-9


def test_welch_satterthwaite_all_infinite():
    c = [UncertaintyComponent(name="a", value=0.1)]  # ν=∞ default
    res = welch_satterthwaite(c)
    assert res["effective_dof"] == math.inf


def test_expanded_uncertainty_large_dof():
    # For ν→∞, k at 95% → 1.96
    res = expanded_uncertainty(0.1, effective_dof=math.inf, confidence=0.95)
    assert abs(res["coverage_factor"] - 1.959963984540054) < 1e-9
    assert abs(res["expanded_uncertainty"] - 0.1 * 1.959963984540054) < 1e-9


def test_expanded_uncertainty_small_dof():
    # At ν=4 and 95%, Student-t k ≈ 2.776
    res = expanded_uncertainty(0.1, effective_dof=4.0, confidence=0.95)
    assert abs(res["coverage_factor"] - 2.776445105) < 1e-6


def test_propagate_linear():
    # y = a + b; u(a)=0.3, u(b)=0.4 → u_c(y) = 0.5
    comps = [
        UncertaintyComponent("a", 0.3),
        UncertaintyComponent("b", 0.4),
    ]
    out = propagate(lambda x: x["a"] + x["b"], {"a": 1.0, "b": 2.0}, comps)
    assert abs(out["combined_standard_uncertainty"] - 0.5) < 1e-6


def test_propagate_product():
    # y = a*b, sensitivities (b, a); u_c at (a=2, b=3, u=(0.1,0.1))
    # = sqrt((3*0.1)^2 + (2*0.1)^2) = sqrt(0.09 + 0.04) = sqrt(0.13)
    comps = [
        UncertaintyComponent("a", 0.1),
        UncertaintyComponent("b", 0.1),
    ]
    out = propagate(lambda x: x["a"] * x["b"], {"a": 2.0, "b": 3.0}, comps)
    assert abs(out["combined_standard_uncertainty"] - math.sqrt(0.13)) < 1e-5


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
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    sys.exit(0 if failed == 0 else 1)
