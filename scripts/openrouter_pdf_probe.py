#!/usr/bin/env python3
"""Probe OpenRouter PDF and multimodal behavior across multiple model routes.

This script mirrors Pollux's current OpenRouter chat-completions request shapes
for text, image, and PDF inputs, then records transport behavior and lightweight
diagnostics as JSONL.

Examples:
  uv run python scripts/openrouter_pdf_probe.py
  uv run python scripts/openrouter_pdf_probe.py --repeat 3
  uv run python scripts/openrouter_pdf_probe.py --preset expected --preset multimodal
  uv run python scripts/openrouter_pdf_probe.py --model openai/gpt-5-nano --case local_pdf
  uv run python scripts/openrouter_pdf_probe.py --list-presets
"""

from __future__ import annotations

import argparse
import base64
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import statistics
import sys
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse
from uuid import uuid4

from dotenv import load_dotenv
import httpx

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_REMOTE_PDF_URL = (
    "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
)
DEFAULT_REMOTE_IMAGE_URL = (
    "https://upload.wikimedia.org/wikipedia/commons/thumb/9/97/"
    "The_Earth_seen_from_Apollo_17.jpg/500px-The_Earth_seen_from_Apollo_17.jpg"
)
LOCAL_PDF_TOKEN = "PDFLOCAL314159"  # noqa: S105 - probe sentinel, not a secret
TEXT_CONTROL_TOKEN = "TEXT_CONTROL_OK"  # noqa: S105 - probe sentinel, not a secret
DEFAULT_CASES = (
    "text_control",
    "local_pdf",
    "remote_pdf_url",
    "local_image",
    "remote_image_url",
)
MODEL_PRESETS: dict[str, tuple[str, ...]] = {
    "expected": (
        "openai/gpt-5-nano",
        "openrouter/free",
        "meta-llama/llama-3.2-1b-instruct",
        "deepseek/deepseek-chat-v3.1",
        "qwen/qwen3-next-80b-a3b-instruct:free",
        "moonshotai/kimi-k2.5",
        "z-ai/glm-4.5-air:free",
        "nvidia/nemotron-3-nano-30b-a3b:free",
    ),
    "multimodal": (
        "meta-llama/llama-3.2-11b-vision-instruct",
        "qwen/qwen3-vl-8b-instruct",
        "z-ai/glm-4.6v",
        "nvidia/nemotron-nano-12b-v2-vl:free",
    ),
    "routers": (
        "openrouter/free",
        "openrouter/auto",
    ),
}
CASE_DESCRIPTIONS = {
    "text_control": "Prompt-only control case.",
    "local_pdf": "Inline local-style PDF via data URL, mirroring Pollux upload_file().",
    "remote_pdf_url": "Remote PDF URL through OpenRouter's `type=file` request path.",
    "local_image": "Inline local-style image via data URL.",
    "remote_image_url": "Remote image URL through OpenRouter's `image_url` request path.",
}


@dataclass(frozen=True, slots=True)
class PreparedCase:
    """A concrete probe case ready to serialize into a chat-completions payload."""

    slug: str
    modality: str
    source_kind: str
    description: str
    prompt: str
    content_items: tuple[dict[str, Any], ...]
    expected_text: str | None = None
    expectation_kind: str | None = None


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        help="OpenRouter model slug to probe. Repeatable.",
    )
    parser.add_argument(
        "--preset",
        action="append",
        choices=sorted(MODEL_PRESETS),
        default=[],
        help="Named model preset to include. Repeatable. Defaults to 'expected'.",
    )
    parser.add_argument(
        "--case",
        action="append",
        choices=sorted(CASE_DESCRIPTIONS),
        default=[],
        help="Probe case to run. Repeatable. Defaults to a compact multimodal matrix.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Number of attempts per model/case combination.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.0,
        help="Sleep between probe requests.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=90.0,
        help="HTTP timeout for both metadata and chat requests.",
    )
    parser.add_argument(
        "--remote-pdf-url",
        default=DEFAULT_REMOTE_PDF_URL,
        help="Remote PDF URL used by the remote_pdf_url case.",
    )
    parser.add_argument(
        "--remote-image-url",
        default=DEFAULT_REMOTE_IMAGE_URL,
        help="Remote image URL used by the remote_image_url case.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="JSONL output path. Defaults to artifacts/openrouter-probe-<timestamp>.jsonl.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any transport failure occurs.",
    )
    parser.add_argument(
        "--list-presets",
        action="store_true",
        help="List built-in model presets and exit.",
    )
    parser.add_argument(
        "--list-cases",
        action="store_true",
        help="List available probe cases and exit.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    """Run the probe script."""
    args = parse_args(argv)
    if args.list_presets:
        _print_presets()
        return 0
    if args.list_cases:
        _print_cases()
        return 0

    load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("OPENROUTER_API_KEY is required.", file=sys.stderr)
        return 2

    models = _resolve_models(args.model, args.preset)
    cases = _prepare_cases(args.case or list(DEFAULT_CASES), args)
    output_path = args.out or _default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    timeout = httpx.Timeout(args.timeout_seconds)
    run_id = uuid4().hex
    records: list[dict[str, Any]] = []

    with (
        httpx.Client(
            base_url=OPENROUTER_BASE_URL,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        ) as client,
        output_path.open("a", encoding="utf-8") as sink,
    ):
        catalog = fetch_model_catalog(client)
        missing_models = [model for model in models if model not in catalog]
        if missing_models:
            print(
                "warning: models missing from live catalog: "
                + ", ".join(sorted(missing_models)),
                file=sys.stderr,
            )

        for attempt in range(1, args.repeat + 1):
            for model in models:
                metadata = catalog.get(model)
                for probe_case in cases:
                    record = run_probe(
                        client=client,
                        run_id=run_id,
                        attempt=attempt,
                        model=model,
                        metadata=metadata,
                        probe_case=probe_case,
                    )
                    records.append(record)
                    sink.write(json.dumps(record, sort_keys=True) + "\n")
                    sink.flush()
                    if args.delay_seconds > 0:
                        time.sleep(args.delay_seconds)

    print(f"Wrote {len(records)} records to {output_path}")
    print_summary(records)

    if args.strict and any(not record["transport_ok"] for record in records):
        return 1
    return 0


def fetch_model_catalog(client: httpx.Client) -> dict[str, dict[str, Any]]:
    """Fetch the live OpenRouter models catalog."""
    response = client.get("/models")
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(data, list):
        return {}

    catalog: dict[str, dict[str, Any]] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if isinstance(model_id, str) and model_id:
            catalog[model_id] = item
    return catalog


def run_probe(
    *,
    client: httpx.Client,
    run_id: str,
    attempt: int,
    model: str,
    metadata: dict[str, Any] | None,
    probe_case: PreparedCase,
) -> dict[str, Any]:
    """Execute one probe request and return a structured result record."""
    started_at = _utc_now()
    payload = build_payload(model=model, probe_case=probe_case)
    start = time.perf_counter()
    response = client.post("/chat/completions", json=payload)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    completed_at = _utc_now()

    response_json = _parse_json(response)
    transport_ok = 200 <= response.status_code < 300
    answer_text = extract_message_text(response_json)
    semantic_ok = evaluate_semantics(
        answer_text,
        expected_text=probe_case.expected_text,
        expectation_kind=probe_case.expectation_kind,
    )
    pollux_expectation = pollux_expectation_for_case(
        metadata=metadata,
        probe_case=probe_case,
    )

    return {
        "run_id": run_id,
        "started_at_utc": started_at,
        "completed_at_utc": completed_at,
        "attempt": attempt,
        "model": model,
        "case": probe_case.slug,
        "case_description": probe_case.description,
        "modality": probe_case.modality,
        "source_kind": probe_case.source_kind,
        "prompt": probe_case.prompt,
        "request_shape": describe_request_shape(probe_case),
        "transport_ok": transport_ok,
        "semantic_ok": semantic_ok,
        "duration_ms": duration_ms,
        "http_status": response.status_code,
        "response_headers": select_headers(response.headers),
        "response_id": response_json.get("id")
        if isinstance(response_json, dict)
        else None,
        "finish_reason": extract_finish_reason(response_json),
        "answer_text": answer_text,
        "usage": extract_usage(response_json),
        "response_provider": response_json.get("provider")
        if isinstance(response_json, dict)
        else None,
        "response_json": response_json,
        "error_message": extract_error_message(
            response_json,
            response.text,
            transport_ok=transport_ok,
        ),
        "model_metadata": normalize_model_metadata(metadata),
        "pollux_would_attempt": pollux_expectation["would_attempt"],
        "pollux_reason": pollux_expectation["reason"],
        "native_modality_advertised": pollux_expectation["native_modality_advertised"],
    }


def build_payload(*, model: str, probe_case: PreparedCase) -> dict[str, Any]:
    """Build an OpenRouter chat-completions payload."""
    content: list[dict[str, Any]] = [{"type": "text", "text": probe_case.prompt}]
    content.extend(probe_case.content_items)
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": content,
            }
        ],
    }


def _prepare_cases(
    case_slugs: Sequence[str], args: argparse.Namespace
) -> list[PreparedCase]:
    """Materialize requested probe cases."""
    prepared: list[PreparedCase] = []
    for slug in case_slugs:
        if slug == "text_control":
            prepared.append(
                PreparedCase(
                    slug=slug,
                    modality="text",
                    source_kind="prompt",
                    description=CASE_DESCRIPTIONS[slug],
                    prompt=("Reply with exactly TEXT_CONTROL_OK and nothing else."),
                    content_items=(),
                    expected_text=TEXT_CONTROL_TOKEN,
                    expectation_kind="exact",
                )
            )
            continue

        if slug == "local_pdf":
            prepared.append(
                PreparedCase(
                    slug=slug,
                    modality="pdf",
                    source_kind="local_inline",
                    description=CASE_DESCRIPTIONS[slug],
                    prompt=(
                        "Reply with exactly the token printed inside the PDF. "
                        "If you cannot read the PDF text, reply CANNOT_READ_PDF."
                    ),
                    content_items=(
                        {
                            "type": "file",
                            "file": {
                                "filename": "probe-local.pdf",
                                "file_data": _to_data_url(
                                    _build_pdf_with_text(LOCAL_PDF_TOKEN),
                                    "application/pdf",
                                ),
                            },
                        },
                    ),
                    expected_text=LOCAL_PDF_TOKEN,
                    expectation_kind="exact",
                )
            )
            continue

        if slug == "remote_pdf_url":
            prepared.append(
                PreparedCase(
                    slug=slug,
                    modality="pdf",
                    source_kind="remote_url",
                    description=CASE_DESCRIPTIONS[slug],
                    prompt=(
                        "If you can access the PDF, describe it in at most eight "
                        "words. Otherwise reply PDF_UNAVAILABLE."
                    ),
                    content_items=(
                        {
                            "type": "file",
                            "file": {
                                "filename": _pdf_filename(args.remote_pdf_url),
                                "file_data": args.remote_pdf_url,
                            },
                        },
                    ),
                )
            )
            continue

        if slug == "local_image":
            prepared.append(
                PreparedCase(
                    slug=slug,
                    modality="image",
                    source_kind="local_inline",
                    description=CASE_DESCRIPTIONS[slug],
                    prompt=(
                        "If you can access the image, describe it in at most five "
                        "words. Otherwise reply IMAGE_UNAVAILABLE."
                    ),
                    content_items=(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": _to_data_url(_tiny_png_bytes(), "image/png")
                            },
                        },
                    ),
                )
            )
            continue

        if slug == "remote_image_url":
            prepared.append(
                PreparedCase(
                    slug=slug,
                    modality="image",
                    source_kind="remote_url",
                    description=CASE_DESCRIPTIONS[slug],
                    prompt=(
                        "If you can access the image, describe it in at most five "
                        "words. Otherwise reply IMAGE_UNAVAILABLE."
                    ),
                    content_items=(
                        {
                            "type": "image_url",
                            "image_url": {"url": args.remote_image_url},
                        },
                    ),
                )
            )
            continue

        raise AssertionError(f"Unhandled case slug: {slug}")

    return prepared


def _resolve_models(
    explicit_models: Sequence[str], preset_names: Sequence[str]
) -> list[str]:
    """Resolve models from explicit flags plus named presets."""
    chosen_presets = list(preset_names)
    if not explicit_models and not chosen_presets:
        chosen_presets = ["expected"]
    combined: list[str] = []
    for preset in chosen_presets:
        combined.extend(MODEL_PRESETS[preset])
    combined.extend(explicit_models)
    return list(_unique_preserve_order(combined))


def _unique_preserve_order(values: Iterable[str]) -> list[str]:
    """Return values once, preserving first-seen order."""
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _default_output_path() -> Path:
    """Return the default JSONL output path."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path("artifacts") / f"openrouter-probe-{timestamp}.jsonl"


def _utc_now() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _parse_json(response: httpx.Response) -> dict[str, Any]:
    """Best-effort JSON parsing for OpenRouter responses."""
    try:
        payload = response.json()
    except ValueError:
        return {"_raw_text": response.text}
    return payload if isinstance(payload, dict) else {"_non_object": payload}


def extract_message_text(payload: dict[str, Any]) -> str:
    """Extract assistant text from a chat-completions response payload."""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    choice = choices[0]
    if not isinstance(choice, dict):
        return ""
    message = choice.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")

    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    text_parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if item.get("type") == "text" and isinstance(text, str):
            text_parts.append(text)
    return "\n\n".join(text_parts)


def extract_finish_reason(payload: dict[str, Any]) -> str | None:
    """Extract `finish_reason` from a chat-completions response payload."""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    choice = choices[0]
    if not isinstance(choice, dict):
        return None
    finish_reason = choice.get("finish_reason")
    return finish_reason if isinstance(finish_reason, str) else None


def extract_usage(payload: dict[str, Any]) -> dict[str, int]:
    """Extract usage fields from a response payload."""
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return {}

    extracted: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, int):
            extracted[key] = value
    return extracted


def extract_error_message(
    payload: dict[str, Any], raw_text: str, *, transport_ok: bool
) -> str | None:
    """Extract a concise error message from a response payload."""
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            return message
    if transport_ok:
        return None
    if payload.get("_raw_text"):
        text = payload["_raw_text"]
        return text[:500] if isinstance(text, str) and text else None
    return raw_text[:500] if raw_text else None


def evaluate_semantics(
    answer_text: str,
    *,
    expected_text: str | None,
    expectation_kind: str | None,
) -> bool | None:
    """Evaluate semantic success for cases with a meaningful oracle."""
    if expected_text is None or expectation_kind is None:
        return None
    normalized_answer = answer_text.strip()
    if expectation_kind == "exact":
        return normalized_answer == expected_text
    raise AssertionError(f"Unhandled expectation kind: {expectation_kind}")


def describe_request_shape(probe_case: PreparedCase) -> list[dict[str, str]]:
    """Describe the content items without embedding raw base64 data."""
    items = [{"type": "text", "source": "prompt"}]
    for item in probe_case.content_items:
        item_type = item.get("type")
        if item_type == "image_url":
            url = item.get("image_url", {}).get("url", "")
            items.append(
                {
                    "type": "image_url",
                    "source": "data_url"
                    if str(url).startswith("data:")
                    else "remote_url",
                }
            )
            continue
        if item_type == "file":
            file_part = item.get("file", {})
            file_data = file_part.get("file_data", "")
            items.append(
                {
                    "type": "file",
                    "source": (
                        "data_url"
                        if str(file_data).startswith("data:")
                        else "remote_url"
                    ),
                    "filename": str(file_part.get("filename", "")),
                }
            )
            continue
        items.append({"type": str(item_type), "source": "unknown"})
    return items


def normalize_model_metadata(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the subset of model metadata relevant to Pollux behavior."""
    if metadata is None:
        return None
    architecture = metadata.get("architecture")
    if not isinstance(architecture, dict):
        architecture = {}
    input_modalities = architecture.get("input_modalities")
    output_modalities = architecture.get("output_modalities")
    supported_parameters = metadata.get("supported_parameters")

    return {
        "id": metadata.get("id"),
        "input_modalities": _normalize_str_list(input_modalities),
        "output_modalities": _normalize_str_list(output_modalities),
        "supported_parameters": _normalize_str_list(supported_parameters),
    }


def pollux_expectation_for_case(
    *,
    metadata: dict[str, Any] | None,
    probe_case: PreparedCase,
) -> dict[str, Any]:
    """Explain whether Pollux would attempt the request for this model/case pair."""
    normalized = normalize_model_metadata(metadata) or {}
    input_modalities = set(normalized.get("input_modalities", []))
    output_modalities = set(normalized.get("output_modalities", []))

    if "text" not in input_modalities or "text" not in output_modalities:
        return {
            "would_attempt": False,
            "reason": "Pollux requires text input/output for all OpenRouter requests.",
            "native_modality_advertised": False,
        }

    if probe_case.modality == "text":
        return {
            "would_attempt": True,
            "reason": "Text-only request.",
            "native_modality_advertised": True,
        }

    if probe_case.modality == "image":
        native = "image" in input_modalities
        return {
            "would_attempt": native,
            "reason": (
                "Pollux gates OpenRouter image inputs on model metadata."
                if native
                else "Pollux would reject image input because model metadata does not advertise image support."
            ),
            "native_modality_advertised": native,
        }

    if probe_case.modality == "pdf":
        native = "file" in input_modalities
        return {
            "would_attempt": True,
            "reason": (
                "Pollux allows PDFs via OpenRouter's provider-side PDF parser, even when native file input is not advertised."
            ),
            "native_modality_advertised": native,
        }

    return {
        "would_attempt": None,
        "reason": "Unknown modality.",
        "native_modality_advertised": None,
    }


def select_headers(headers: httpx.Headers) -> dict[str, str]:
    """Keep the most useful response headers for debugging."""
    keep: dict[str, str] = {}
    for key, value in headers.items():
        lowered = key.lower()
        if lowered.startswith(("x-", "openrouter-", "cf-")) or lowered in {
            "content-type",
            "server",
        }:
            keep[key] = value
    return keep


def print_summary(records: Sequence[dict[str, Any]]) -> None:
    """Print a compact human-readable summary."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(record["model"], record["case"])].append(record)

    print()
    print("Summary")
    for model, case in sorted(grouped):
        group = grouped[(model, case)]
        successes = sum(1 for item in group if item["transport_ok"])
        semantic_values = [
            item["semantic_ok"] for item in group if item["semantic_ok"] is not None
        ]
        semantic_summary = (
            f"{sum(bool(v) for v in semantic_values)}/{len(semantic_values)}"
            if semantic_values
            else "n/a"
        )
        latencies = [float(item["duration_ms"]) for item in group]
        last_error = next(
            (
                item["error_message"]
                for item in reversed(group)
                if item["transport_ok"] is False and item["error_message"]
            ),
            None,
        )
        print(
            f"- {model} | {case}: transport {successes}/{len(group)}, "
            f"semantic {semantic_summary}, median {statistics.median(latencies):.1f} ms"
        )
        if last_error:
            print(f"  last error: {last_error}")


def _print_presets() -> None:
    """Print built-in model presets."""
    for name, models in MODEL_PRESETS.items():
        print(f"{name}:")
        for model in models:
            print(f"  {model}")


def _print_cases() -> None:
    """Print available probe cases."""
    for slug, description in CASE_DESCRIPTIONS.items():
        print(f"{slug}: {description}")


def _normalize_str_list(value: Any) -> list[str]:
    """Normalize a list-like field into a lowercase string list."""
    if not isinstance(value, list):
        return []
    normalized = [
        item.strip().lower() for item in value if isinstance(item, str) and item.strip()
    ]
    return sorted(set(normalized))


def _pdf_filename(uri: str) -> str:
    """Return the filename OpenRouter expects for a PDF content item."""
    parsed = urlparse(uri)
    path_name = PurePosixPath(parsed.path).name
    return path_name or "document.pdf"


def _to_data_url(data: bytes, mime_type: str) -> str:
    """Encode bytes as a base64 data URL."""
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _tiny_png_bytes() -> bytes:
    """Return a tiny valid PNG."""
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
        "/w8AAgMBgJ8LxV4AAAAASUVORK5CYII="
    )


def _pdf_escape(text: str) -> str:
    """Escape a string for use in a PDF content stream."""
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_pdf_with_text(text: str) -> bytes:
    """Build a tiny single-page PDF with visible text."""
    stream = (f"BT\n/F1 12 Tf\n72 120 Td\n({_pdf_escape(text)}) Tj\nET\n").encode(
        "ascii"
    )
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            b"3 0 obj\n"
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 200] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>\n"
            b"endobj\n"
        ),
        (
            b"4 0 obj\n<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"endstream\nendobj\n"
        ),
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]

    body = b"%PDF-1.4\n"
    offsets: list[int] = []
    for obj in objects:
        offsets.append(len(body))
        body += obj

    xref_pos = len(body)
    xref = b"xref\n0 6\n0000000000 65535 f \n" + b"".join(
        f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets
    )
    trailer = (
        b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n"
        + str(xref_pos).encode("ascii")
        + b"\n%%EOF\n"
    )
    return body + xref + trailer


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
