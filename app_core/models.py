from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class FileParseResult:
    relative_path: str
    file_type: str
    size_bytes: int
    parse_status: str
    structure_text: str
    evidence_text: str
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    tokens_structure_full_est: int = 0
    tokens_evidence_full_est: int = 0
    tokens_total_full_est: int = 0

    def header(self) -> str:
        return (
            f"FILE: {self.relative_path} | TYPE: {self.file_type} | "
            f"SIZE: {self.size_bytes} | PARSE: {self.parse_status}"
        )

    def to_full_corpus_block(self) -> str:
        return (
            f"{self.header()}\n"
            f"STRUCTURE:\n{self.structure_text.strip() or '(empty)'}\n\n"
            f"EVIDENCE:\n{self.evidence_text.strip() or '(empty)'}"
        ).strip()


@dataclass
class PromptCorpusFileView:
    relative_path: str
    included_structure: str
    included_evidence: str
    tokens_structure_est: int
    tokens_evidence_before_est: int
    tokens_evidence_after_est: int
    evidence_removed: bool
    compression_note: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_block(self, file_type: str, size_bytes: int, parse_status: str) -> str:
        return (
            f"FILE: {self.relative_path} | TYPE: {file_type} | "
            f"SIZE: {size_bytes} | PARSE: {parse_status}\n"
            f"STRUCTURE:\n{self.included_structure.strip() or '(empty)'}\n\n"
            f"EVIDENCE:\n{self.included_evidence.strip() or '(empty)'}"
        ).strip()


@dataclass
class PromptCorpusResult:
    prompt_corpus_text: str
    file_views: list[PromptCorpusFileView]
    tokens_full_corpus_est: int
    tokens_prompt_corpus_est: int
    compression_summary: list[str]
    compression_policy_step: str


@dataclass
class RequestLogEntry:
    timestamp: str
    request_type: str
    model: str
    attempt: int
    retry_reason: str
    success: bool
    http_status: int | None
    error_text: str
    trace_id: str
    tokens_prompt_total_est: int
    compression_applied: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnalysisResult:
    answer: str
    confidence: int
    questions: list[str] = field(default_factory=list)
    expected_confidence_after_answers: int | None = None
    question_impact: list[dict[str, Any]] = field(default_factory=list)
    raw_json: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PiiMaskResult:
    masked_text: str
    replacements: list[dict[str, Any]]
    raw_json: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
