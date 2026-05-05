from __future__ import annotations

import json
from datetime import datetime, timezone

from app_core.models import AnalysisResult, PiiMaskResult, PromptCorpusResult, RequestLogEntry


def build_report_json(
    *,
    trace_id: str,
    model: str,
    task_text: str,
    prompt_result: PromptCorpusResult,
    primary_result: AnalysisResult | None,
    final_result: AnalysisResult | None,
    question_answers: list[dict],
    request_logs: list[RequestLogEntry],
    pii_mask_result: PiiMaskResult | None,
) -> str:
    payload = {
        "trace_id": trace_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "tokens_full_corpus_est": prompt_result.tokens_full_corpus_est,
        "tokens_prompt_corpus_est": prompt_result.tokens_prompt_corpus_est,
        "tokens_prompt_total_est": _last_prompt_total(request_logs),
        "prompt_corpus_compression_summary": {
            "policy_step": prompt_result.compression_policy_step,
            "details": prompt_result.compression_summary,
        },
        "task_text": task_text,
        "primary_analysis": primary_result.to_dict() if primary_result else None,
        "question_answers": question_answers,
        "final_analysis": final_result.to_dict() if final_result else None,
        "request_logs": [entry.to_dict() for entry in request_logs],
    }
    if pii_mask_result is not None:
        payload["pii_masking"] = {
            "masked_text": pii_mask_result.masked_text,
            "replacements": pii_mask_result.replacements,
        }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _last_prompt_total(request_logs: list[RequestLogEntry]) -> int:
    if not request_logs:
        return 0
    return request_logs[-1].tokens_prompt_total_est
