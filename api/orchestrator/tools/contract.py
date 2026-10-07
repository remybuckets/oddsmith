"""Loads oddsmith_tools.json (owned by the lead lane) and validates tool input and output."""

import json
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import best_match

from orchestrator.tools.envelope import ToolError

# api/orchestrator/tools/contract.py -> repo root
TOOLS_FILE = Path(__file__).resolve().parents[3] / "oddsmith_tools.json"


@cache
def _contract() -> dict[str, Any]:
    with TOOLS_FILE.open(encoding="utf-8") as f:
        return json.load(f)


@cache
def tool_specs() -> dict[str, dict[str, Any]]:
    return {tool["name"]: tool for tool in _contract()["tools"]}


@cache
def _input_validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(tool_specs()[name]["input_schema"], format_checker=FormatChecker())


@cache
def _output_validator(name: str) -> Draft202012Validator:
    schema = {**tool_specs()[name]["output_schema"], "$defs": _contract()["$defs"]}
    return Draft202012Validator(schema, format_checker=FormatChecker())


@cache
def _envelope_validator() -> Draft202012Validator:
    return Draft202012Validator(_contract()["envelope"], format_checker=FormatChecker())


def validate_input(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict with schema defaults filled in, or raise ToolError(invalid_input)."""
    error = best_match(_input_validator(name).iter_errors(args))
    if error is not None:
        where = ".".join(str(p) for p in error.absolute_path)
        message = f"{where}: {error.message}" if where else error.message
        raise ToolError("invalid_input", f"Invalid input for {name}. {message}")
    properties = tool_specs()[name]["input_schema"].get("properties", {})
    defaults = {k: p["default"] for k, p in properties.items() if "default" in p}
    return {**defaults, **args}


def output_problem(name: str, result: dict[str, Any]) -> str | None:
    """Describe how `result` breaks the envelope or the tool's output_schema, or None."""
    error = best_match(_envelope_validator().iter_errors(result))
    if error is None and result.get("ok"):
        error = best_match(_output_validator(name).iter_errors(result["data"]))
    if error is None:
        return None
    where = "/".join(str(p) for p in error.absolute_path)
    return f"{where}: {error.message}"
