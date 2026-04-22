"""MCP server — exposes math_kernel functions as MCP tools over stdio."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .math_kernel import (
    InputQuantity,
    UncertaintyComponent,
    type_a_uncertainty,
    type_b_rectangular,
    type_b_triangular,
    type_b_normal,
    combine_uncertainty,
    welch_satterthwaite,
    expanded_uncertainty,
    monte_carlo_propagate,
)

log = logging.getLogger("measurement-uncertainty-mcp")

APP = Server("measurement-uncertainty")


# --- Tool schemas (JSON Schema, per MCP spec) -------------------------------

_TOOLS: list[Tool] = [
    Tool(
        name="type_a_uncertainty",
        description=(
            "GUM Type A (statistical) standard uncertainty from a sample of "
            "repeated measurements. Returns n, mean, sample std (Bessel-corrected), "
            "standard uncertainty u = s/sqrt(n), and degrees of freedom ν = n-1."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "samples": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "description": "List of observed values (e.g. replicate measurements)",
                }
            },
            "required": ["samples"],
        },
    ),
    Tool(
        name="type_b_rectangular",
        description=(
            "GUM Type B standard uncertainty assuming a uniform distribution "
            "over [-half_width, +half_width]. u = half_width / sqrt(3). "
            "Use for resolution limits, quantization, tolerance bands."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "half_width": {"type": "number", "exclusiveMinimum": 0},
            },
            "required": ["half_width"],
        },
    ),
    Tool(
        name="type_b_triangular",
        description=(
            "GUM Type B standard uncertainty assuming a triangular distribution "
            "over [-half_width, +half_width]. u = half_width / sqrt(6)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "half_width": {"type": "number", "exclusiveMinimum": 0},
            },
            "required": ["half_width"],
        },
    ),
    Tool(
        name="type_b_normal",
        description=(
            "GUM Type B standard uncertainty from a manufacturer-specified "
            "expanded uncertainty value U at coverage factor k "
            "(e.g. ±0.5 µm at k=2 → u = 0.25 µm)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "expanded_value": {"type": "number", "exclusiveMinimum": 0},
                "coverage_factor": {"type": "number", "exclusiveMinimum": 0, "default": 2.0},
            },
            "required": ["expanded_value"],
        },
    ),
    Tool(
        name="combine_uncertainty",
        description=(
            "Combined standard uncertainty u_c(y) from a list of components. "
            "Each component supplies its standard uncertainty u_i, sensitivity c_i, "
            "and (optional) degrees of freedom. Uncorrelated inputs only."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "components": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "u": {"type": "number", "minimum": 0},
                            "sensitivity": {"type": "number", "default": 1.0},
                            "dof": {"type": "number", "exclusiveMinimum": 0},
                        },
                        "required": ["name", "u"],
                    },
                }
            },
            "required": ["components"],
        },
    ),
    Tool(
        name="welch_satterthwaite",
        description=(
            "Effective degrees of freedom ν_eff via the Welch-Satterthwaite "
            "formula (GUM G.4.2). Needed for picking the right Student-t "
            "coverage factor when combining Type A (finite ν) with Type B (ν=∞)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "components": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "u": {"type": "number", "minimum": 0},
                            "sensitivity": {"type": "number", "default": 1.0},
                            "dof": {"type": "number", "exclusiveMinimum": 0},
                        },
                        "required": ["name", "u"],
                    },
                }
            },
            "required": ["components"],
        },
    ),
    Tool(
        name="expanded_uncertainty",
        description=(
            "Expanded uncertainty U = k * u_c. k is picked from Student-t at "
            "(confidence, ν_eff). Confidence defaults to 0.95."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "u_combined": {"type": "number", "exclusiveMinimum": 0},
                "effective_dof": {"type": "number", "exclusiveMinimum": 0,
                                  "description": "Use a large number (e.g. 1e9) for ν=∞"},
                "confidence": {"type": "number", "minimum": 0.5, "maximum": 0.999,
                               "default": 0.95},
            },
            "required": ["u_combined"],
        },
    ),
    Tool(
        name="monte_carlo_propagate",
        description=(
            "Monte Carlo uncertainty propagation (JCGM 101:2008 / GUM Supplement 1). "
            "Use when the measurement model is non-linear, inputs are non-Gaussian, "
            "or the Welch-Satterthwaite effective dof is too small for a k=2 "
            "normal-approximation coverage factor. Returns mean, standard uncertainty, "
            "shortest coverage interval, skewness, and excess kurtosis of the output."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "formula": {
                    "type": "string",
                    "description": (
                        "Sympy-parseable expression of the measurement model. "
                        "Variable names must match inputs[*].name. "
                        "Examples: 'V / I', 'a + b', 'exp(x)', '(a * b) / (c - d)'."
                    ),
                },
                "inputs": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "distribution": {
                                "type": "string",
                                "enum": [
                                    "normal", "uniform", "rectangular",
                                    "triangular", "lognormal", "t",
                                ],
                            },
                            "params": {
                                "type": "object",
                                "description": (
                                    "Distribution-specific params. "
                                    "normal: {mean, std}. "
                                    "uniform: {low, high} or {center, half_width}. "
                                    "triangular: {low, mode, high}. "
                                    "lognormal: {mu, sigma} (of log-variable). "
                                    "t: {mean, scale, df}."
                                ),
                            },
                            "dof": {"type": "number", "exclusiveMinimum": 0},
                        },
                        "required": ["name", "distribution", "params"],
                    },
                },
                "n_trials": {
                    "type": "integer",
                    "minimum": 1000,
                    "default": 200000,
                    "description": "JCGM 101 recommends 1e6; 2e5 is a fast, accurate default.",
                },
                "coverage": {
                    "type": "number",
                    "minimum": 0.5,
                    "maximum": 0.999,
                    "default": 0.95,
                },
                "seed": {
                    "type": "integer",
                    "description": "Optional RNG seed for reproducibility.",
                },
            },
            "required": ["formula", "inputs"],
        },
    ),
]


def _to_components(raw: list[dict]) -> list[UncertaintyComponent]:
    out = []
    for c in raw:
        dof = c.get("dof")
        out.append(UncertaintyComponent(
            name=c["name"],
            value=float(c["u"]),
            sensitivity=float(c.get("sensitivity", 1.0)),
            degrees_of_freedom=float(dof) if dof is not None else float("inf"),
        ))
    return out


def _to_inputs(raw: list[dict]) -> list[InputQuantity]:
    out = []
    for i in raw:
        dof = i.get("dof")
        out.append(InputQuantity(
            name=i["name"],
            distribution=i["distribution"],
            params=dict(i["params"]),
            degrees_of_freedom=float(dof) if dof is not None else float("inf"),
        ))
    return out


def _as_text(payload: Any) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, indent=2, default=str))]


@APP.list_tools()
async def list_tools() -> list[Tool]:
    return _TOOLS


@APP.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "type_a_uncertainty":
            return _as_text(type_a_uncertainty(arguments["samples"]))
        if name == "type_b_rectangular":
            return _as_text(type_b_rectangular(float(arguments["half_width"])))
        if name == "type_b_triangular":
            return _as_text(type_b_triangular(float(arguments["half_width"])))
        if name == "type_b_normal":
            return _as_text(type_b_normal(
                float(arguments["expanded_value"]),
                k=float(arguments.get("coverage_factor", 2.0)),
            ))
        if name == "combine_uncertainty":
            return _as_text(combine_uncertainty(_to_components(arguments["components"])))
        if name == "welch_satterthwaite":
            return _as_text(welch_satterthwaite(_to_components(arguments["components"])))
        if name == "expanded_uncertainty":
            dof = arguments.get("effective_dof", float("inf"))
            return _as_text(expanded_uncertainty(
                float(arguments["u_combined"]),
                effective_dof=float(dof) if dof != float("inf") else float("inf"),
                confidence=float(arguments.get("confidence", 0.95)),
            ))
        if name == "monte_carlo_propagate":
            return _as_text(monte_carlo_propagate(
                formula=str(arguments["formula"]),
                inputs=_to_inputs(arguments["inputs"]),
                n_trials=int(arguments.get("n_trials", 200_000)),
                coverage=float(arguments.get("coverage", 0.95)),
                seed=int(arguments["seed"]) if arguments.get("seed") is not None else None,
            ))
        raise ValueError(f"Unknown tool: {name}")
    except Exception as exc:
        log.exception("tool %s failed", name)
        return _as_text({"error": str(exc), "tool": name})


async def run() -> None:
    async with stdio_server() as (reader, writer):
        await APP.run(reader, writer, APP.create_initialization_options())
