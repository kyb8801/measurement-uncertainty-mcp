"""Uncertainty-budget template library tests (Issue #3).

What we verify:
  1. list_uncertainty_templates works on every tier and previews only names,
     not numbers.
  2. Industry / measurand filters work and return deterministic ordering.
  3. apply_uncertainty_template is tier-gated (Team only). Free / Pro /
     missing env var → PermissionError.
  4. When the tier is Team, applying a template produces the same combined
     + expanded uncertainty as the direct combine_uncertainty → welch →
     expanded chain on the same components. This is the core correctness
     property — the template is a convenience, not a re-implementation.
  5. Overrides patch individual component fields without touching the rest.
  6. Unknown template_id / unknown override component raise clean errors.
"""
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from measurement_uncertainty_mcp.math_kernel import (  # noqa: E402
    combine_uncertainty,
    expanded_uncertainty,
    welch_satterthwaite,
)
from measurement_uncertainty_mcp import templates as T  # noqa: E402
from measurement_uncertainty_mcp.templates import (  # noqa: E402
    TEMPLATES,
    _spec_to_uncertainty,
    apply_uncertainty_template,
    list_uncertainty_templates,
)


# ---------------------------------------------------------------------------
# Tier env-var helpers
# ---------------------------------------------------------------------------


class _TierEnv:
    """Context manager to set MCP_TIER for the duration of a test."""

    def __init__(self, tier: str | None):
        self._tier = tier
        self._prior = None

    def __enter__(self):
        self._prior = os.environ.get("MCP_TIER")
        if self._tier is None:
            os.environ.pop("MCP_TIER", None)
        else:
            os.environ["MCP_TIER"] = self._tier
        return self

    def __exit__(self, *exc):
        if self._prior is None:
            os.environ.pop("MCP_TIER", None)
        else:
            os.environ["MCP_TIER"] = self._prior


# ---------------------------------------------------------------------------
# Listing (always free)
# ---------------------------------------------------------------------------


def test_list_available_on_free_tier():
    with _TierEnv("free"):
        out = list_uncertainty_templates()
    assert out["tier"] == "free"
    assert out["n_templates"] >= 6
    # Name-only preview, no raw u / half_width / expanded_value leaks.
    first = out["templates"][0]
    assert "component_names" in first
    assert "components" not in first


def test_list_available_without_env_var():
    # Default (no env var) must also list — unknown/missing tiers default to free.
    with _TierEnv(None):
        out = list_uncertainty_templates()
    assert out["tier"] == "free"
    assert out["n_templates"] == len(TEMPLATES)


def test_list_industry_filter():
    with _TierEnv("team"):
        out = list_uncertainty_templates(industry="semiconductor")
    assert out["n_templates"] == 2
    assert {t["id"] for t in out["templates"]} == {
        "cdsem_linewidth_45nm",
        "ocd_film_thickness_50nm",
    }


def test_list_measurand_filter():
    with _TierEnv("team"):
        out = list_uncertainty_templates(measurand="length")
    # Length templates: CMM + CD-SEM.
    ids = {t["id"] for t in out["templates"]}
    assert "cmm_length_10mm" in ids
    assert "cdsem_linewidth_45nm" in ids


def test_list_is_sorted_deterministically():
    with _TierEnv("team"):
        a = list_uncertainty_templates()
        b = list_uncertainty_templates()
    assert [t["id"] for t in a["templates"]] == [t["id"] for t in b["templates"]]


# ---------------------------------------------------------------------------
# apply_* tier gating
# ---------------------------------------------------------------------------


def test_apply_blocked_on_free_tier():
    with _TierEnv("free"):
        try:
            apply_uncertainty_template("cmm_length_10mm")
        except PermissionError as e:
            assert "team" in str(e).lower()
        else:
            raise AssertionError("apply must raise on free tier")


def test_apply_blocked_on_pro_tier():
    with _TierEnv("pro"):
        try:
            apply_uncertainty_template("cmm_length_10mm")
        except PermissionError:
            return
        raise AssertionError("apply must raise on pro tier (team-only feature)")


def test_apply_blocked_without_env_var():
    with _TierEnv(None):
        try:
            apply_uncertainty_template("cmm_length_10mm")
        except PermissionError:
            return
        raise AssertionError("apply must raise when MCP_TIER is unset")


def test_unknown_tier_treated_as_free():
    with _TierEnv("enterprise"):  # not in the rank table
        try:
            apply_uncertainty_template("cmm_length_10mm")
        except PermissionError as e:
            assert "team" in str(e).lower()
        else:
            raise AssertionError("unknown tier must not unlock team features")


# ---------------------------------------------------------------------------
# apply_* correctness (Team tier)
# ---------------------------------------------------------------------------


def test_apply_all_templates_load():
    """Every shipped template must apply cleanly without raising."""
    with _TierEnv("team"):
        for tid in TEMPLATES:
            r = apply_uncertainty_template(tid)
            assert r["combined_standard_uncertainty"] > 0
            assert r["expanded_uncertainty"] > r["combined_standard_uncertainty"]
            assert 0 < r["coverage_factor"]
            assert r["template"]["id"] == tid


def test_apply_matches_direct_chain_for_cmm():
    """apply must equal the manual combine → welch → expanded pipeline."""
    tid = "cmm_length_10mm"
    with _TierEnv("team"):
        via_template = apply_uncertainty_template(tid)

    # Re-derive the components by hand.
    comps = [_spec_to_uncertainty(c) for c in TEMPLATES[tid]["components"]]
    combined = combine_uncertainty(comps)
    dof = welch_satterthwaite(comps)["effective_dof"]
    exp = expanded_uncertainty(
        combined["combined_standard_uncertainty"],
        effective_dof=dof,
        confidence=0.95,
    )

    assert math.isclose(
        via_template["combined_standard_uncertainty"],
        combined["combined_standard_uncertainty"],
        rel_tol=1e-12,
    )
    assert math.isclose(
        via_template["expanded_uncertainty"],
        exp["expanded_uncertainty"],
        rel_tol=1e-12,
    )
    assert via_template["coverage_factor"] == exp["coverage_factor"]


def test_apply_confidence_propagates():
    """Coverage factor must actually change when confidence changes."""
    with _TierEnv("team"):
        r95 = apply_uncertainty_template("cmm_length_10mm", confidence=0.95)
        r99 = apply_uncertainty_template("cmm_length_10mm", confidence=0.99)
    assert r99["coverage_factor"] > r95["coverage_factor"]
    assert r99["expanded_uncertainty"] > r95["expanded_uncertainty"]


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def test_override_changes_repeatability():
    with _TierEnv("team"):
        base = apply_uncertainty_template("cmm_length_10mm")
        patched = apply_uncertainty_template(
            "cmm_length_10mm",
            overrides={"repeatability": {"u": 0.0005, "dof": 4}},
        )

    # u_c must change because a component's u changed.
    assert not math.isclose(
        base["combined_standard_uncertainty"],
        patched["combined_standard_uncertainty"],
    )
    # The non-overridden components are still there.
    names_base = {c["name"] for c in base["components"]}
    names_patch = {c["name"] for c in patched["components"]}
    assert names_base == names_patch


def test_override_does_not_mutate_catalog():
    """Overrides must deepcopy — the global TEMPLATES dict must stay intact."""
    before = TEMPLATES["cmm_length_10mm"]["components"][-1]["u"]
    with _TierEnv("team"):
        apply_uncertainty_template(
            "cmm_length_10mm",
            overrides={"repeatability": {"u": 0.00999}},
        )
    after = TEMPLATES["cmm_length_10mm"]["components"][-1]["u"]
    assert before == after


def test_override_unknown_component_rejected():
    with _TierEnv("team"):
        try:
            apply_uncertainty_template(
                "cmm_length_10mm",
                overrides={"not_a_real_component": {"u": 0.1}},
            )
        except ValueError as e:
            assert "not_a_real_component" in str(e)
        else:
            raise AssertionError("must reject unknown override target")


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_unknown_template_id():
    with _TierEnv("team"):
        try:
            apply_uncertainty_template("not_a_real_template")
        except ValueError as e:
            assert "not_a_real_template" in str(e)
        else:
            raise AssertionError("must reject unknown template_id")


def test_spec_rejects_unknown_type():
    try:
        _spec_to_uncertainty({"name": "bad", "type": "made_up_type"})
    except ValueError as e:
        assert "made_up_type" in str(e)
    else:
        raise AssertionError("must reject unknown component type")


def test_spec_rejects_negative_k_in_type_b_normal():
    try:
        _spec_to_uncertainty({
            "name": "bad", "type": "type_b_normal",
            "expanded_value": 1.0, "k": 0.0,
        })
    except ValueError as e:
        assert "k" in str(e).lower()
    else:
        raise AssertionError("must reject k<=0 in type_b_normal")


# ---------------------------------------------------------------------------
# Sanity checks on seed numbers
# ---------------------------------------------------------------------------


def test_cmm_expanded_uncertainty_within_expected_range():
    """Sanity guardrail on the CMM template: U(k=2) should be ≈ 1.0–2.0 µm.
    If someone mistyped a zero, this catches it before users hit it.
    """
    with _TierEnv("team"):
        r = apply_uncertainty_template("cmm_length_10mm")
    U_um = r["expanded_uncertainty"] * 1000.0  # mm → µm
    assert 1.0 < U_um < 2.0, f"CMM U={U_um} µm fell outside sane envelope"


def test_cdsem_expanded_uncertainty_within_expected_range():
    """CD-SEM at 45 nm: U(k≈2) should be a few tenths of nm to ~1 nm."""
    with _TierEnv("team"):
        r = apply_uncertainty_template("cdsem_linewidth_45nm")
    assert 0.3 < r["expanded_uncertainty"] < 1.5, (
        f"CD-SEM U={r['expanded_uncertainty']} nm fell outside sane envelope"
    )


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
