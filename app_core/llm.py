from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError

from app_core.models import AnalysisResult, PiiMaskResult, RequestLogEntry


RETRYABLE_EXCEPTIONS = (RateLimitError, APITimeoutError, APIError, APIConnectionError)


def generate_trace_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"req_{timestamp}_{uuid4().hex[:4]}"


def create_openrouter_client(api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")


def create_lm_studio_client(base_url: str, api_key: str) -> OpenAI:
    return OpenAI(base_url=base_url.rstrip("/") + "/v1", api_key=api_key)


def run_primary_analysis(
    *,
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
    trace_id: str,
    timeout_seconds: int,
    max_output_tokens: int,
    request_logs: list[RequestLogEntry],
    tokens_prompt_total_est: int,
    compression_applied: bool,
) -> AnalysisResult:
    payload = _run_json_request(
        client=client,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        request_type="analyze",
        trace_id=trace_id,
        timeout_seconds=timeout_seconds,
        max_output_tokens=max_output_tokens,
        request_logs=request_logs,
        tokens_prompt_total_est=tokens_prompt_total_est,
        compression_applied=compression_applied,
    )
    return AnalysisResult(
        answer=str(payload.get("answer", "")),
        confidence=int(payload.get("confidence", 0)),
        questions=[str(item) for item in payload.get("questions", [])],
        expected_confidence_after_answers=_optional_int(payload.get("expected_confidence_after_answers")),
        question_impact=list(payload.get("question_impact", [])),
        raw_json=payload,
    )


def run_final_analysis(
    *,
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
    trace_id: str,
    timeout_seconds: int,
    max_output_tokens: int,
    request_logs: list[RequestLogEntry],
    tokens_prompt_total_est: int,
    compression_applied: bool,
) -> AnalysisResult:
    payload = _run_json_request(
        client=client,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        request_type="final_analyze",
        trace_id=trace_id,
        timeout_seconds=timeout_seconds,
        max_output_tokens=max_output_tokens,
        request_logs=request_logs,
        tokens_prompt_total_est=tokens_prompt_total_est,
        compression_applied=compression_applied,
    )
    return AnalysisResult(
        answer=str(payload.get("answer", "")),
        confidence=int(payload.get("confidence", 0)),
        raw_json=payload,
    )


def run_pii_masking(
    *,
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
    trace_id: str,
    timeout_seconds: int,
    max_output_tokens: int,
    request_logs: list[RequestLogEntry],
    tokens_prompt_total_est: int,
) -> PiiMaskResult:
    payload = _run_json_request(
        client=client,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        request_type="mask_pii",
        trace_id=trace_id,
        timeout_seconds=timeout_seconds,
        max_output_tokens=max_output_tokens,
        request_logs=request_logs,
        tokens_prompt_total_est=tokens_prompt_total_est,
        compression_applied=False,
    )
    return PiiMaskResult(
        masked_text=str(payload.get("masked_text", "")),
        replacements=list(payload.get("replacements", [])),
        raw_json=payload,
    )


def _run_json_request(
    *,
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
    request_type: str,
    trace_id: str,
    timeout_seconds: int,
    max_output_tokens: int,
    request_logs: list[RequestLogEntry],
    tokens_prompt_total_est: int,
    compression_applied: bool,
) -> dict[str, Any]:
    last_error = ""
    last_status: int | None = None
    for attempt in range(1, 4):
        try:
            content = _chat_completion(
                client=client,
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                timeout_seconds=timeout_seconds,
                max_output_tokens=max_output_tokens,
            )
            payload = json.loads(content)
            _append_log(
                request_logs,
                request_type=request_type,
                model=model,
                attempt=attempt,
                retry_reason="" if attempt == 1 else last_error,
                success=True,
                http_status=None,
                error_text="",
                trace_id=trace_id,
                tokens_prompt_total_est=tokens_prompt_total_est,
                compression_applied=compression_applied,
            )
            return payload
        except json.JSONDecodeError as exc:
            last_error = f"Invalid JSON: {exc}"
            fixed_payload = _try_reformat_json(
                client=client,
                model=model,
                invalid_response=content if "content" in locals() else "",
                timeout_seconds=timeout_seconds,
                max_output_tokens=max_output_tokens,
                request_logs=request_logs,
                trace_id=trace_id,
                tokens_prompt_total_est=tokens_prompt_total_est,
                compression_applied=compression_applied,
            )
            if fixed_payload is not None:
                return fixed_payload
            _append_log(
                request_logs,
                request_type=request_type,
                model=model,
                attempt=attempt,
                retry_reason=last_error,
                success=False,
                http_status=None,
                error_text=last_error,
                trace_id=trace_id,
                tokens_prompt_total_est=tokens_prompt_total_est,
                compression_applied=compression_applied,
            )
            raise ValueError(last_error) from exc
        except RETRYABLE_EXCEPTIONS as exc:
            last_status = getattr(exc, "status_code", None)
            last_error = str(exc)
            _append_log(
                request_logs,
                request_type=request_type,
                model=model,
                attempt=attempt,
                retry_reason=last_error if attempt > 1 else "",
                success=False,
                http_status=last_status,
                error_text=last_error,
                trace_id=trace_id,
                tokens_prompt_total_est=tokens_prompt_total_est,
                compression_applied=compression_applied,
            )
            if attempt >= 3:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError(last_error or "Unknown request failure")


def _try_reformat_json(
    *,
    client: OpenAI,
    model: str,
    invalid_response: str,
    timeout_seconds: int,
    max_output_tokens: int,
    request_logs: list[RequestLogEntry],
    trace_id: str,
    tokens_prompt_total_est: int,
    compression_applied: bool,
) -> dict[str, Any] | None:
    system_prompt = (
        "You convert invalid model output into one valid JSON object. "
        "Return JSON only with no explanations."
    )
    user_prompt = "Fix this content into valid JSON only:\n\n" + invalid_response
    try:
        content = _chat_completion(
            client=client,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens,
        )
        payload = json.loads(content)
        _append_log(
            request_logs,
            request_type="reformat_to_json",
            model=model,
            attempt=1,
            retry_reason="invalid_json",
            success=True,
            http_status=None,
            error_text="",
            trace_id=trace_id,
            tokens_prompt_total_est=tokens_prompt_total_est,
            compression_applied=compression_applied,
        )
        return payload
    except Exception as exc:
        _append_log(
            request_logs,
            request_type="reformat_to_json",
            model=model,
            attempt=1,
            retry_reason="invalid_json",
            success=False,
            http_status=getattr(exc, "status_code", None),
            error_text=str(exc),
            trace_id=trace_id,
            tokens_prompt_total_est=tokens_prompt_total_est,
            compression_applied=compression_applied,
        )
        return None


def _chat_completion(
    *,
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout_seconds: int,
    max_output_tokens: int,
) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        timeout=timeout_seconds,
        max_tokens=max_output_tokens,
    )
    message = response.choices[0].message.content
    if not message:
        raise ValueError("Empty response from model")
    return message


def _append_log(
    request_logs: list[RequestLogEntry],
    *,
    request_type: str,
    model: str,
    attempt: int,
    retry_reason: str,
    success: bool,
    http_status: int | None,
    error_text: str,
    trace_id: str,
    tokens_prompt_total_est: int,
    compression_applied: bool,
) -> None:
    request_logs.append(
        RequestLogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            request_type=request_type,
            model=model,
            attempt=attempt,
            retry_reason=retry_reason,
            success=success,
            http_status=http_status,
            error_text=error_text,
            trace_id=trace_id,
            tokens_prompt_total_est=tokens_prompt_total_est,
            compression_applied=compression_applied,
        )
    )


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
