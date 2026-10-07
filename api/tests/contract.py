"""Validate responses and SSE events against contracts/openapi.yaml, the file web's types come from."""

from functools import cache
from pathlib import Path
from typing import Any

import httpx
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from tests.sse import parse_sse

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "contracts" / "openapi.yaml"
CONTRACT: dict[str, Any] = yaml.safe_load(CONTRACT_PATH.read_text())
_BASE = "urn:oddsmith:openapi"
_REGISTRY = Registry().with_resource(_BASE, Resource(CONTRACT, DRAFT202012))
JSON = "application/json"
SSE = "text/event-stream"


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


@cache
def _validator(pointer: str) -> Draft202012Validator:
    # Refs inside resolve against the contract document, not this wrapper.
    return Draft202012Validator(
        {"$ref": f"{_BASE}#{pointer}"},
        registry=_REGISTRY,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


def _response_pointer(path: str, method: str, status: int) -> str:
    responses = CONTRACT["paths"][path][method]["responses"]
    response = responses.get(str(status))
    if response is None:
        # Undocumented status (e.g. 404, 422): still has to be an error envelope.
        return "/components/responses/Error"
    if "$ref" in response:
        return response["$ref"].removeprefix("#")
    return "/" + "/".join(_escape(t) for t in ("paths", path, method, "responses", str(status)))


def _schema_pointer(path: str, method: str, status: int, media: str) -> str:
    pointer = _response_pointer(path, method, status)
    return f"{pointer}/content/{_escape(media)}/schema"


def assert_conforms(instance: Any, pointer: str) -> None:
    errors = sorted(_validator(pointer).iter_errors(instance), key=lambda e: list(e.path))
    assert not errors, "\n".join(
        f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in errors
    )


def assert_response(response: httpx.Response, path: str, method: str) -> None:
    """path is the contract's template, e.g. '/conversations/{id}/messages'."""
    media = response.headers["content-type"].split(";")[0]
    if media == SSE:
        assert response.status_code == 200
        for _name, event in parse_sse(response.text):
            assert_conforms(event, _schema_pointer(path, method, 200, SSE))
        return
    assert media == JSON, media
    assert_conforms(response.json(), _schema_pointer(path, method, response.status_code, JSON))
    if response.status_code >= 400:
        assert_conforms(response.json()["error"], "/components/schemas/ApiError")


def contract_operations() -> set[tuple[str, str]]:
    return {
        (path, method)
        for path, item in CONTRACT["paths"].items()
        for method in item
        if method in {"get", "post", "put", "patch", "delete"}
    }
