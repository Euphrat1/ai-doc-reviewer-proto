from __future__ import annotations

import math

from app_core.models import FileParseResult, PromptCorpusFileView, PromptCorpusResult
from app_core.parsers import estimate_tokens, truncate_by_tokens


def build_full_corpus_text(files: list[FileParseResult]) -> str:
    return "\n\n".join(file_result.to_full_corpus_block() for file_result in files)


def build_prompt_corpus(
    files: list[FileParseResult],
    *,
    chars_per_token: float,
    prompt_budget_tokens: int,
    max_structure_tokens_per_file: int,
    max_evidence_tokens_per_file: int,
    max_pdf_pages_in_evidence: int,
    max_files_with_evidence: int,
) -> PromptCorpusResult:
    views: list[PromptCorpusFileView] = []
    full_tokens = sum(file_result.tokens_total_full_est for file_result in files)
    compression_summary: list[str] = []
    compression_policy_step = "none"

    for file_result in files:
        structure = truncate_by_tokens(
            file_result.structure_text,
            max_structure_tokens_per_file,
            chars_per_token,
        )
        evidence_source = _limit_pdf_evidence(
            file_result,
            max_pdf_pages_in_evidence=max_pdf_pages_in_evidence,
        )
        evidence = truncate_by_tokens(
            evidence_source,
            max_evidence_tokens_per_file,
            chars_per_token,
        )
        evidence_before = estimate_tokens(evidence_source, chars_per_token)
        evidence_after = estimate_tokens(evidence, chars_per_token)
        note = ""
        if evidence_after < evidence_before:
            note = "Evidence trimmed to per-file limit."
            compression_summary.append(
                f"{file_result.relative_path}: EVIDENCE trimmed {evidence_before} -> {evidence_after} tokens est."
            )
            compression_policy_step = "step_2_trim_evidence"

        views.append(
            PromptCorpusFileView(
                relative_path=file_result.relative_path,
                included_structure=structure,
                included_evidence=evidence,
                tokens_structure_est=estimate_tokens(structure, chars_per_token),
                tokens_evidence_before_est=evidence_before,
                tokens_evidence_after_est=evidence_after,
                evidence_removed=False,
                compression_note=note,
                metadata=file_result.metadata,
            )
        )

    total_tokens = _prompt_views_tokens(views, files, chars_per_token)

    if total_tokens > prompt_budget_tokens:
        compression_policy_step = "step_2_priority_trim"
        for view in sorted(
            views,
            key=lambda item: (_evidence_priority(item.relative_path), item.relative_path),
        ):
            if total_tokens <= prompt_budget_tokens:
                break
            reduced = _halve_text(view.included_evidence)
            if reduced == view.included_evidence:
                continue
            before = view.tokens_evidence_after_est
            view.included_evidence = reduced
            view.tokens_evidence_after_est = estimate_tokens(reduced, chars_per_token)
            view.compression_note = "Evidence reduced by prompt budget policy."
            compression_summary.append(
                f"{view.relative_path}: EVIDENCE trimmed {before} -> {view.tokens_evidence_after_est} tokens est by prompt budget."
            )
            total_tokens = _prompt_views_tokens(views, files, chars_per_token)

    if total_tokens > prompt_budget_tokens and max_files_with_evidence >= 0:
        compression_policy_step = "step_3_limit_files_with_evidence"
        for index, view in enumerate(views):
            if index < max_files_with_evidence:
                continue
            if not view.included_evidence:
                continue
            before = view.tokens_evidence_after_est
            view.included_evidence = ""
            view.tokens_evidence_after_est = 0
            view.evidence_removed = True
            view.compression_note = "Evidence removed by max files with evidence policy."
            compression_summary.append(
                f"{view.relative_path}: EVIDENCE removed {before} -> 0 tokens est."
            )
            total_tokens = _prompt_views_tokens(views, files, chars_per_token)
            if total_tokens <= prompt_budget_tokens:
                break

    prompt_blocks: list[str] = []
    files_by_name = {file_result.relative_path: file_result for file_result in files}
    for view in views:
        file_result = files_by_name[view.relative_path]
        prompt_blocks.append(
            view.to_block(file_result.file_type, file_result.size_bytes, file_result.parse_status)
        )

    return PromptCorpusResult(
        prompt_corpus_text="\n\n".join(prompt_blocks),
        file_views=views,
        tokens_full_corpus_est=full_tokens,
        tokens_prompt_corpus_est=total_tokens,
        compression_summary=compression_summary,
        compression_policy_step=compression_policy_step,
    )


def build_qa_block(
    questions: list[str],
    answers: list[str],
    attachment_texts: list[list[tuple[str, str]]],
) -> str:
    lines = ["Q_AND_A:"]
    for index, question in enumerate(questions, start=1):
        answer = answers[index - 1] if index - 1 < len(answers) else ""
        lines.append(f"[{index}] QUESTION: {question}")
        lines.append(f"    ANSWER: {answer.strip() or '(no answer provided)'}")
        attachments = attachment_texts[index - 1] if index - 1 < len(attachment_texts) else []
        if attachments:
            lines.append("    ATTACHMENTS:")
            for filename, content in attachments:
                lines.append(f"      - name: {filename}")
                lines.append(f"        content: {content}")
    return "\n".join(lines)


def estimate_total_prompt_tokens(
    *,
    system_prompt: str,
    user_prompt: str,
    chars_per_token: float,
) -> int:
    return estimate_tokens(f"{system_prompt}\n{user_prompt}", chars_per_token)


def _limit_pdf_evidence(file_result: FileParseResult, *, max_pdf_pages_in_evidence: int) -> str:
    if file_result.file_type != "pdf" or max_pdf_pages_in_evidence <= 0:
        return file_result.evidence_text

    sections = [section for section in file_result.evidence_text.split("\n\n") if section.strip()]
    if len(sections) <= max_pdf_pages_in_evidence:
        file_result.metadata["included_pages"] = list(range(1, len(sections) + 1))
        return file_result.evidence_text

    front_count = max(1, math.ceil(max_pdf_pages_in_evidence / 2))
    tail_count = max_pdf_pages_in_evidence - front_count
    selected_sections = sections[:front_count]
    if tail_count > 0:
        selected_sections.extend(sections[-tail_count:])
    included_pages = []
    for section in selected_sections:
        marker = "PDF_TEXT p."
        if section.startswith(marker):
            page_number = section[len(marker):].split(":", 1)[0]
            if page_number.isdigit():
                included_pages.append(int(page_number))
    file_result.metadata["included_pages"] = included_pages
    return "\n\n".join(selected_sections)


def _prompt_views_tokens(
    views: list[PromptCorpusFileView],
    files: list[FileParseResult],
    chars_per_token: float,
) -> int:
    files_by_name = {file_result.relative_path: file_result for file_result in files}
    total = 0
    for view in views:
        file_result = files_by_name[view.relative_path]
        block = view.to_block(file_result.file_type, file_result.size_bytes, file_result.parse_status)
        total += estimate_tokens(block, chars_per_token)
    return total


def _halve_text(text: str) -> str:
    if not text:
        return text
    midpoint = max(1, len(text) // 2)
    return text[:midpoint].rstrip() + "\n...[truncated more]..."


def _evidence_priority(relative_path: str) -> int:
    lower = relative_path.lower()
    if lower.endswith(".csv") or lower.endswith(".xlsx"):
        return 0
    if lower.endswith(".pdf"):
        return 1
    return 2
