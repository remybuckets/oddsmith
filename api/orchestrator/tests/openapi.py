"""Check orchestrator events and cards against contracts/openapi.yaml (what the web app reads)."""

from functools import cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

_CONTRACT_PATH = Path(__file__).resolve().parents[3] / "contracts" / "openapi.yaml"
_BASE = "urn:oddsmith:openapi"


@cache
def _validator(schema_name: str) -> Draft202012Validator:
    contract = yaml.safe_load(_CONTRACT_PATH.read_text())
    registry = Registry().with_resource(_BASE, Resource(contract, DRAFT202012))
    return Draft202012Validator(
        {"$ref": f"{_BASE}#/components/schemas/{schema_name}"},
        registry=registry,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


def assert_matches(instance: Any, schema_name: str) -> None:
    errors = list(_validator(schema_name).iter_errors(instance))
    assert not errors, "\n".join(
        f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in errors
    )


def assert_stream_events(events: list[dict[str, Any]]) -> None:
    """Every event except the final usage event (never forwarded) is a StreamEvent."""
    for event in events:
        if event["type"] != "usage":
            assert_matches(event, "StreamEvent")
