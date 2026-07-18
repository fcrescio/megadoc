"""Knowledge classifier API router."""

import base64
import csv
import hashlib
import io
import json
import os
import re
import time
import unicodedata
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal

import fitz
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.orm import Session, selectinload

from common.application.knowledge import (
    ensure_scan_unit_for_ocr_result,
    has_active_ingestion_jobs,
    mark_knowledge_job_pending_dispatch,
    upsert_document_unit_topic_assignment,
)
from common.application.graph import graph_stats, rebuild_knowledge_graph
from common.application.contexts import rebuild_knowledge_contexts
from common.application.accounting import (
    apply_manual_accounting_correction,
    compare_context_accounting_periods,
    find_context_account_subjects,
    get_accounting_cell_detail,
    get_accounting_table,
)
from common.application.specialists import ensure_specialist_jobs_for_scan_unit
from common.application.page_artifacts import get_page_artifact_text
from common.application.topic_policy import collection_topic_kind
from common.application.entities import (
    EntityVariantInput,
    assign_entity_variant,
    get_or_create_canonical_entity,
)
from common.application.projections import rebuild_semantic_projections
from common.application.runtime_settings import resolve_runtime_settings
from common.db.models import (
    CanonicalEntity,
    CanonicalEntityVariant,
    KnowledgeContext,
    KnowledgeContextAnchor,
    KnowledgeContextMembership,
    Document,
    DocumentVersion,
    DocumentType,
    OCRResult,
    ScanUnit,
    DocumentUnit,
    DocumentUnitEntity,
    DocumentUnitTopicAssignment,
    Topic,
    TopicAlias,
    TopicProposal,
    KnowledgeAgentRun,
    KnowledgeJob,
    GraphConsolidationReview,
    SpecialistJob,
    SpecialistResult,
    DocumentUnitLink,
    DocumentUnitMention,
    CalendarEvent,
    Payable,
    KnowledgeAssertion,
    KnowledgeNode,
    KnowledgeNodeAlias,
)
from common.config import get_settings
from common.db.session import SessionLocal, get_db_session
from common.storage.backends import get_storage_backend
from knowledge_classifier.schemas import (
    ConsolidationResponse,
    ScanUnitCreate,
    ScanUnitResponse,
    DocumentUnitResponse,
    TopicResponse,
    TopicSummaryResponse,
    TopicDetailResponse,
    TopicRelatedDocumentResponse,
    KnowledgeSearchResponse,
    KnowledgeSearchTopicHit,
    KnowledgeSearchDocumentHit,
    KnowledgeEntitySummaryResponse,
    KnowledgeEntityDetailResponse,
    KnowledgeEntityDocumentHitResponse,
    CanonicalEntitySummaryResponse,
    CanonicalEntityVariantResponse,
    CanonicalEntityDetailResponse,
    CanonicalEntityMergeRequest,
    KnowledgeContextDetailResponse,
    KnowledgeContextAnchorResponse,
    KnowledgeContextMembershipResponse,
    KnowledgeContextStatsResponse,
    KnowledgeContextSummaryResponse,
    ContextAccountingComparisonResponse,
    ContextAccountingSubjectResponse,
    AccountingAskRequest,
    AccountingAskResponse,
    AccountingFactCorrectionRequest,
    AccountingFactCorrectionResponse,
    KnowledgeAssertionResponse,
    KnowledgeGraphStatsResponse,
    KnowledgeNodeDetailResponse,
    KnowledgeNodeSummaryResponse,
    TopicCreate,
    TopicProposalResponse,
    DocumentTypeResponse,
    GraphConsolidationSuggestionsResponse,
    GraphMergeSuggestionResponse,
    GraphConsolidationReviewRequest,
    GraphConsolidationReviewResponse,
    GraphSuggestionTopicSummaryResponse,
    TopicMergeRequest,
    TopicMergeResponse,
    CleanupReportResponse,
    InactiveTopicCleanupResponse,
    KnowledgeJobResponse,
    ReviewUpdate,
    ReviewStatus,
    TopicAssignmentUpsert,
    TopicProposalResolution,
    ScanUnitStatus,
)
from knowledge_classifier.services.consolidation import KnowledgeBaseConsolidationService
from knowledge_classifier.config import get_settings as get_knowledge_settings
from knowledge_classifier.llm.base import ChatMessage
from knowledge_classifier.llm.openai_compat import OpenAICompatibleProvider
from knowledge_worker.dispatch import dispatch_scan_unit_processing
from specialist_worker.dispatch import dispatch_specialist_job
from api.services.retrieval import RetrievalService
from api.services.agent_orchestration import AgentToolBudget, SEARCH_ACTIONS, canonical_query

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class _AccountingAskPlan(BaseModel):
    subject: str | None = Field(default=None)
    period_a_from: date | None = Field(default=None)
    period_a_to: date | None = Field(default=None)
    period_b_from: date | None = Field(default=None)
    period_b_to: date | None = Field(default=None)
    intent: str = Field(default="compare_periods")


class _KnowledgeAgentAction(BaseModel):
    action: Literal[
        "retrieve_evidence",
        "search_archive",
        "semantic_search",
        "list_topics",
        "get_document_unit",
        "get_document",
        "search_document_text",
        "get_page_text",
        "analyze_page_image",
        "request_page_vision",
        "search_calendar_events",
        "query_accounting_tables",
        "final_answer",
    ]
    reasoning: str = Field(default="")
    query: str | None = Field(default=None)
    supplier: str | None = Field(default=None)
    document_id: str | None = Field(default=None)
    document_unit_id: str | None = Field(default=None)
    topic_id: str | None = Field(default=None)
    page_number: int | None = Field(default=None)
    date_from: date | None = Field(default=None)
    date_to: date | None = Field(default=None)
    amount_min: float | None = Field(default=None)
    amount_max: float | None = Field(default=None)
    status: str | None = Field(default=None)
    review_status: str | None = Field(default=None)
    subject: str | None = Field(default=None)
    period_a_from: date | None = Field(default=None)
    period_a_to: date | None = Field(default=None)
    period_b_from: date | None = Field(default=None)
    period_b_to: date | None = Field(default=None)
    limit: int | None = Field(default=None)
    answer: str | None = Field(default=None)
    confidence: float | None = Field(default=None, ge=0, le=1)
    citations: list[dict[str, Any]] = Field(default_factory=list)


class KnowledgeAgentConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=8000)


class KnowledgeAgentChatRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=4000)
    max_steps: int = Field(default=12, ge=1, le=20)
    allow_vision: bool = Field(default=False)
    history: list[KnowledgeAgentConversationMessage] = Field(default_factory=list, max_length=20)
    selected_document_ids: list[str] = Field(default_factory=list, max_length=8)


class KnowledgeAgentTraceStep(BaseModel):
    step: int
    action: str
    reasoning: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | list[Any] | str | None = None
    error: str | None = None


class KnowledgeAgentCitation(BaseModel):
    document_id: str | None = None
    document_unit_id: str | None = None
    original_filename: str | None = None
    title: str | None = None
    page_from: int | None = None
    page_to: int | None = None
    quote: str | None = None


class KnowledgeAgentVisionRequest(BaseModel):
    document_id: str
    page_number: int
    reason: str | None = None


class _KnowledgeAgentVisionAnalysis(BaseModel):
    page_summary: str
    relevant_text: str | None = None
    answer_hint: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class KnowledgeAgentChatResponse(BaseModel):
    status: str
    answer: str
    confidence: float | None = None
    tool_trace: list[KnowledgeAgentTraceStep] = Field(default_factory=list)
    citations: list[KnowledgeAgentCitation] = Field(default_factory=list)
    vision_requests: list[KnowledgeAgentVisionRequest] = Field(default_factory=list)
    model: str | None = None
    run_id: str | None = None


class KnowledgeAgentRunSummary(BaseModel):
    id: str
    question: str
    answer: str
    status: str
    model: str | None = None
    confidence: float | None = None
    allow_vision: bool
    max_steps: int
    tool_step_count: int
    citation_count: int
    vision_request_count: int
    duration_ms: int | None = None
    created_at: datetime


class KnowledgeAgentRunDetail(KnowledgeAgentRunSummary):
    tool_trace: list[KnowledgeAgentTraceStep] = Field(default_factory=list)
    citations: list[KnowledgeAgentCitation] = Field(default_factory=list)
    vision_requests: list[KnowledgeAgentVisionRequest] = Field(default_factory=list)


class KnowledgeSearchIndexStats(BaseModel):
    total_chunks: int
    by_source_type: dict[str, int] = Field(default_factory=dict)
    embedding_models: list[str] = Field(default_factory=list)
    active_model: str
    indexed_at: datetime | None = None
    source_updated_at: datetime | None = None
    is_stale: bool


class KnowledgeSearchIndexRebuildResponse(KnowledgeSearchIndexStats):
    status: str
    chunks_indexed: int
    chunks_skipped: int


def _serialize_entity(entity: DocumentUnitEntity) -> dict[str, Any]:
    return {
        "id": str(entity.id),
        "entity_type": entity.entity_type,
        "entity_value": entity.entity_value,
        "normalized_value": entity.normalized_value,
        "confidence": entity.confidence,
        "page_from": entity.page_from,
        "page_to": entity.page_to,
    }


def _serialize_topic_assignment(assignment: DocumentUnitTopicAssignment) -> dict[str, Any]:
    topic = assignment.topic
    return {
        "id": str(assignment.id),
        "topic_id": str(assignment.topic_id),
        "topic_slug": topic.slug if topic else None,
        "topic_title": topic.title if topic else None,
        "topic_kind": topic.topic_kind if topic else None,
        "topic_class": topic.topic_class if topic else None,
        "assignment_role": assignment.assignment_role,
        "confidence": assignment.confidence,
        "rationale": assignment.rationale,
    }


def _serialize_topic_proposal(proposal: TopicProposal | None) -> dict[str, Any] | None:
    if proposal is None:
        return None
    source_document_unit = proposal.source_document_unit
    source_scan_unit = source_document_unit.scan_unit if source_document_unit else None
    source_document = source_scan_unit.document if source_scan_unit else None
    return {
        "id": str(proposal.id),
        "proposed_slug": proposal.proposed_slug,
        "proposed_title": proposal.proposed_title,
        "topic_class": proposal.topic_class,
        "proposed_topic_kind": proposal.proposed_topic_kind,
        "description": proposal.description,
        "proposal_status": proposal.proposal_status,
        "matched_existing_topic_id": str(proposal.matched_existing_topic_id) if proposal.matched_existing_topic_id else None,
        "matched_existing_topic_title": proposal.matched_topic.title if proposal.matched_topic else None,
        "source_document_unit_id": str(source_document_unit.id) if source_document_unit else None,
        "source_document_id": str(source_document.id) if source_document else None,
        "source_document_filename": source_document.original_filename if source_document else None,
        "source_start_page": source_document_unit.start_page if source_document_unit else None,
        "source_end_page": source_document_unit.end_page if source_document_unit else None,
        "confidence": proposal.confidence,
        "rationale": proposal.rationale,
        "review_payload_json": proposal.review_payload_json,
        "created_at": proposal.created_at,
        "reviewed_at": proposal.reviewed_at,
    }


def _serialize_document_unit(doc_unit: DocumentUnit) -> dict[str, Any]:
    specialist_jobs = sorted(doc_unit.specialist_jobs, key=lambda job: job.created_at, reverse=True)
    specialist_results = sorted(doc_unit.specialist_results, key=lambda result: result.created_at, reverse=True)
    outgoing_links = sorted(doc_unit.outgoing_links, key=lambda link: (link.link_type, link.created_at))
    return {
        "id": str(doc_unit.id),
        "scan_unit_id": str(doc_unit.scan_unit_id),
        "ordinal": doc_unit.ordinal,
        "start_page": doc_unit.start_page,
        "end_page": doc_unit.end_page,
        "title": doc_unit.title,
        "document_type_code": doc_unit.document_type.code if doc_unit.document_type else None,
        "document_type_name": doc_unit.document_type.name if doc_unit.document_type else None,
        "document_type_confidence": doc_unit.document_type_confidence,
        "segmentation_confidence": doc_unit.segmentation_confidence,
        "extracted_summary": doc_unit.extracted_summary,
        "review_status": doc_unit.review_status,
        "entities": [_serialize_entity(entity) for entity in doc_unit.entities],
        "topic_assignments": [
            _serialize_topic_assignment(assignment)
            for assignment in doc_unit.topic_assignments
        ],
        "proposal": _serialize_topic_proposal(doc_unit.proposal),
        "specialist_jobs": [
            {
                "id": str(job.id),
                "specialist_type": job.specialist_type,
                "status": job.status,
                "input_version": job.input_version,
                "routing_confidence": job.routing_confidence,
                "routing_rationale": job.routing_rationale,
                "attempt_count": job.attempt_count,
                "error_message": job.error_message,
                "created_at": job.created_at,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
            }
            for job in specialist_jobs
        ],
        "specialist_results": [
            {
                "id": str(result.id),
                "specialist_type": result.specialist_type,
                "schema_version": result.schema_version,
                "confidence": result.confidence,
                "review_status": result.review_status,
                "result_json": result.result_json,
                "created_at": result.created_at,
                "updated_at": result.updated_at,
            }
            for result in specialist_results
        ],
        "outgoing_links": [
            {
                "id": str(link.id),
                "link_type": link.link_type,
                "target_document_unit_id": str(link.target_document_unit_id),
                "target_title": link.target_document_unit.title if link.target_document_unit else None,
                "target_document_type_code": (
                    link.target_document_unit.document_type.code
                    if link.target_document_unit and link.target_document_unit.document_type
                    else None
                ),
                "target_document_id": (
                    str(link.target_document_unit.scan_unit.source_document_id)
                    if link.target_document_unit and link.target_document_unit.scan_unit
                    else None
                ),
                "confidence": link.confidence,
                "rationale": link.rationale,
                "created_at": link.created_at,
            }
            for link in outgoing_links
        ],
        "created_at": doc_unit.created_at,
        "updated_at": doc_unit.updated_at,
    }


def _review_issues_for_scan_unit(scan_unit: ScanUnit) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if scan_unit.segmentation_confidence is not None and scan_unit.segmentation_confidence < 0.75:
        issues.append(
            {
                "type": "low_scan_segmentation_confidence",
                "severity": "warning",
                "message": f"Confidenza segmentazione scansione bassa: {scan_unit.segmentation_confidence:.0%}.",
            }
        )
    if scan_unit.classification_confidence is not None and scan_unit.classification_confidence < 0.75:
        issues.append(
            {
                "type": "low_scan_classification_confidence",
                "severity": "warning",
                "message": f"Confidenza classificazione scansione bassa: {scan_unit.classification_confidence:.0%}.",
            }
        )

    for doc_unit in sorted(scan_unit.document_units, key=lambda unit: unit.ordinal):
        unit_label = f"Unita {doc_unit.ordinal}, pagine {doc_unit.start_page}-{doc_unit.end_page}"
        if doc_unit.review_status == ReviewStatus.NEEDS_REVIEW.value:
            issues.append(
                {
                    "type": "document_unit_needs_review",
                    "severity": "action",
                    "document_unit_id": str(doc_unit.id),
                    "message": f"{unit_label}: controlla tipo documento, pagine e topic.",
                }
            )
        if doc_unit.proposal is not None and doc_unit.proposal.proposal_status == "proposed":
            issues.append(
                {
                    "type": "pending_topic_proposal",
                    "severity": "blocking",
                    "document_unit_id": str(doc_unit.id),
                    "proposal_id": str(doc_unit.proposal.id),
                    "message": f"{unit_label}: risolvi prima la proposal topic.",
                }
            )
        if doc_unit.document_type_confidence is not None and doc_unit.document_type_confidence < 0.75:
            issues.append(
                {
                    "type": "low_document_type_confidence",
                    "severity": "warning",
                    "document_unit_id": str(doc_unit.id),
                    "message": f"{unit_label}: confidenza tipo documento {doc_unit.document_type_confidence:.0%}.",
                }
            )
        if doc_unit.segmentation_confidence is not None and doc_unit.segmentation_confidence < 0.75:
            issues.append(
                {
                    "type": "low_document_segmentation_confidence",
                    "severity": "warning",
                    "document_unit_id": str(doc_unit.id),
                    "message": f"{unit_label}: confidenza segmentazione {doc_unit.segmentation_confidence:.0%}.",
                }
            )
        for result in doc_unit.specialist_results:
            if result.review_status == ReviewStatus.NEEDS_REVIEW.value:
                issues.append(
                    {
                        "type": "specialist_result_needs_review",
                        "severity": "action",
                        "document_unit_id": str(doc_unit.id),
                        "specialist_result_id": str(result.id),
                        "message": f"{unit_label}: risultato specialista {result.specialist_type} da revisionare.",
                    }
                )
    return issues


def _scan_unit_review_summary(scan_unit: ScanUnit) -> dict[str, Any]:
    issues = _review_issues_for_scan_unit(scan_unit)
    blocking_count = sum(1 for issue in issues if issue.get("severity") == "blocking")
    action_count = sum(1 for issue in issues if issue.get("severity") == "action")
    warning_count = sum(1 for issue in issues if issue.get("severity") == "warning")
    open_count = blocking_count + action_count
    return {
        "status": "needs_review" if open_count else "clear",
        "issue_count": len(issues),
        "blocking_count": blocking_count,
        "action_count": action_count,
        "warning_count": warning_count,
        "open_count": open_count,
        "issues": issues,
    }


def _refresh_scan_unit_review_status(scan_unit: ScanUnit) -> None:
    summary = _scan_unit_review_summary(scan_unit)
    if summary["open_count"] == 0:
        scan_unit.status = ScanUnitStatus.ASSIGNED.value
    elif scan_unit.status != ScanUnitStatus.FAILED.value:
        scan_unit.status = ScanUnitStatus.NEEDS_REVIEW.value


def _latest_specialist_result(document_unit: DocumentUnit, specialist_type: str) -> SpecialistResult | None:
    results = [result for result in document_unit.specialist_results if result.specialist_type == specialist_type]
    if not results:
        return None
    return max(results, key=lambda item: item.created_at)


def _serialize_specialist_utility_summary(result: SpecialistResult, document_unit: DocumentUnit) -> dict[str, Any]:
    payload = result.result_json or {}
    scan_unit = document_unit.scan_unit
    document = scan_unit.document if scan_unit else None
    links = [link for link in document_unit.outgoing_links if link.link_type.startswith("utility_bill_")]
    return {
        "result_id": str(result.id),
        "document_unit_id": str(document_unit.id),
        "document_id": str(document.id) if document else None,
        "original_filename": document.original_filename if document else None,
        "document_type_code": document_unit.document_type.code if document_unit.document_type else None,
        "title": document_unit.title,
        "summary": document_unit.extracted_summary,
        "issuer": payload.get("issuer"),
        "service_type": payload.get("service_type"),
        "account_holder": payload.get("account_holder"),
        "issue_date": payload.get("issue_date"),
        "due_date": payload.get("due_date"),
        "billing_period_from": payload.get("billing_period_from"),
        "billing_period_to": payload.get("billing_period_to"),
        "total_amount": payload.get("total_amount"),
        "currency": payload.get("currency"),
        "payment_status": payload.get("payment_status"),
        "document_number": payload.get("document_number"),
        "contract_code": payload.get("contract_code"),
        "supply_reference": payload.get("supply_reference"),
        "confidence": result.confidence,
        "review_status": result.review_status,
        "related_links": [
            {
                "id": str(link.id),
                "link_type": link.link_type,
                "target_document_unit_id": str(link.target_document_unit_id),
                "target_document_id": (
                    str(link.target_document_unit.scan_unit.source_document_id)
                    if link.target_document_unit and link.target_document_unit.scan_unit
                    else None
                ),
                "target_title": link.target_document_unit.title if link.target_document_unit else None,
                "target_document_type_code": (
                    link.target_document_unit.document_type.code
                    if link.target_document_unit and link.target_document_unit.document_type
                    else None
                ),
                "confidence": link.confidence,
                "rationale": link.rationale,
            }
            for link in links
        ],
        "created_at": result.created_at,
    }


def _serialize_specialist_accounting_summary(result: SpecialistResult, document_unit: DocumentUnit) -> dict[str, Any]:
    payload = result.result_json or {}
    scan_unit = document_unit.scan_unit
    document = scan_unit.document if scan_unit else None
    tables = payload.get("tables") if isinstance(payload.get("tables"), list) else []
    sections = payload.get("sections") if isinstance(payload.get("sections"), list) else []
    checks = payload.get("validation_checks") if isinstance(payload.get("validation_checks"), list) else []
    return {
        "result_id": str(result.id),
        "document_unit_id": str(document_unit.id),
        "document_id": str(document.id) if document else None,
        "original_filename": document.original_filename if document else None,
        "document_type_code": document_unit.document_type.code if document_unit.document_type else None,
        "title": document_unit.title,
        "summary": document_unit.extracted_summary,
        "statement_type": payload.get("statement_type"),
        "accounting_period_from": payload.get("accounting_period_from"),
        "accounting_period_to": payload.get("accounting_period_to"),
        "currency": payload.get("currency"),
        "sections": sections,
        "section_count": len(sections),
        "table_count": len(tables),
        "validation_checks": checks,
        "has_failed_checks": any(check.get("status") == "fail" for check in checks if isinstance(check, dict)),
        "confidence": result.confidence,
        "review_status": result.review_status,
        "created_at": result.created_at,
    }


def _specialist_result_to_csv(result: SpecialistResult) -> str:
    payload = result.result_json or {}
    if result.specialist_type == "accounting_statement":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        tables = payload.get("tables") if isinstance(payload.get("tables"), list) else []
        for table in tables:
            if not isinstance(table, dict):
                continue
            writer.writerow([f"table_id={table.get('table_id','')}", f"table_type={table.get('table_type','')}"])
            headers = table.get("headers") if isinstance(table.get("headers"), list) else []
            if headers:
                writer.writerow([str(header) for header in headers])
            rows = table.get("rows") if isinstance(table.get("rows"), list) else []
            for row in rows:
                cells = row.get("cells") if isinstance(row, dict) and isinstance(row.get("cells"), dict) else {}
                writer.writerow([str(cells.get(str(header), "")) for header in headers])
            writer.writerow([])
        checks = payload.get("validation_checks") if isinstance(payload.get("validation_checks"), list) else []
        if checks:
            writer.writerow(["validation_checks"])
            writer.writerow(["check_type", "status", "details"])
            for check in checks:
                if not isinstance(check, dict):
                    continue
                writer.writerow([check.get("check_type", ""), check.get("status", ""), check.get("details", "")])
        return buffer.getvalue()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["field", "value"])
    for key, value in payload.items():
        if isinstance(value, (list, dict)):
            writer.writerow([key, str(value)])
        else:
            writer.writerow([key, value])
    return buffer.getvalue()


def _serialize_topic_summary(topic: Topic) -> TopicSummaryResponse:
    related_document_ids = {
        str(assignment.document_unit.scan_unit.source_document_id)
        for assignment in topic.assignments
        if assignment.document_unit and assignment.document_unit.scan_unit
    }
    return TopicSummaryResponse(
        id=str(topic.id),
        slug=topic.slug,
        title=topic.title,
        topic_class=topic.topic_class,
        topic_kind=topic.topic_kind,
        description=topic.description,
        canonical=topic.canonical,
        is_active=topic.is_active,
        assignment_count=len(topic.assignments),
        proposal_count=sum(1 for proposal in topic.proposals if proposal.proposal_status == "proposed"),
        related_document_count=len(related_document_ids),
        alias_count=len(topic.aliases),
        created_at=topic.created_at,
        updated_at=topic.updated_at,
    )


def _serialize_topic_detail(topic: Topic) -> TopicDetailResponse:
    related_documents: list[TopicRelatedDocumentResponse] = []
    seen_units: set[str] = set()
    for assignment in sorted(
        topic.assignments,
        key=lambda item: (
            item.document_unit.scan_unit.document.created_at if item.document_unit and item.document_unit.scan_unit and item.document_unit.scan_unit.document else item.created_at,
            item.document_unit.ordinal if item.document_unit else 0,
        ),
        reverse=True,
    ):
        document_unit = assignment.document_unit
        if document_unit is None or document_unit.scan_unit is None or document_unit.scan_unit.document is None:
            continue
        unit_id = str(document_unit.id)
        if unit_id in seen_units:
            continue
        seen_units.add(unit_id)
        document = document_unit.scan_unit.document
        related_documents.append(
            TopicRelatedDocumentResponse(
                document_id=str(document.id),
                external_id=document.external_id,
                original_filename=document.original_filename,
                created_at=document.created_at,
                document_unit_id=unit_id,
                document_type_code=document_unit.document_type.code if document_unit.document_type else None,
                review_status=document_unit.review_status,
                topic_assignment_confidence=assignment.confidence,
                assignment_role=assignment.assignment_role,
                start_page=document_unit.start_page,
                end_page=document_unit.end_page,
                summary=document_unit.extracted_summary,
            )
        )

    return TopicDetailResponse(
        topic=_serialize_topic_summary(topic),
        aliases=sorted({alias.alias for alias in topic.aliases}),
        related_documents=related_documents,
    )


def _normalize_search_value(value: str | None) -> str:
    return (value or "").strip().lower()


def _topic_matched_fields(topic: Topic, query: str) -> list[str]:
    matched_fields: list[str] = []
    normalized_query = _normalize_search_value(query)
    if not normalized_query:
        return matched_fields
    if normalized_query in _normalize_search_value(topic.title):
        matched_fields.append("title")
    if normalized_query in _normalize_search_value(topic.slug):
        matched_fields.append("slug")
    if normalized_query in _normalize_search_value(topic.description):
        matched_fields.append("description")
    if any(normalized_query in _normalize_search_value(alias.alias) for alias in topic.aliases):
        matched_fields.append("alias")
    return matched_fields


def _document_unit_matched_fields(doc_unit: DocumentUnit, query: str) -> list[str]:
    matched_fields: list[str] = []
    normalized_query = _normalize_search_value(query)
    if not normalized_query:
        return matched_fields
    scan_unit = doc_unit.scan_unit
    document = scan_unit.document if scan_unit else None
    if document is not None:
        if normalized_query in _normalize_search_value(document.original_filename):
            matched_fields.append("filename")
        if normalized_query in _normalize_search_value(document.external_id):
            matched_fields.append("external_id")
    if normalized_query in _normalize_search_value(doc_unit.title):
        matched_fields.append("title")
    if normalized_query in _normalize_search_value(doc_unit.extracted_summary):
        matched_fields.append("summary")
    if (
        doc_unit.scan_unit is not None
        and doc_unit.scan_unit.ocr_result is not None
        and (
            normalized_query in _normalize_search_value(doc_unit.scan_unit.ocr_result.full_text)
            or normalized_query in _normalize_search_value(doc_unit.scan_unit.ocr_result.markdown_text)
        )
    ):
        matched_fields.append("ocr_text")
    if any(
        normalized_query in _normalize_search_value(assignment.topic.title if assignment.topic else None)
        or normalized_query in _normalize_search_value(assignment.topic.slug if assignment.topic else None)
        for assignment in doc_unit.topic_assignments
    ):
        matched_fields.append("topic")
    return matched_fields


def _entity_key_expr():
    return func.coalesce(
        func.nullif(DocumentUnitEntity.normalized_value, ""),
        func.lower(DocumentUnitEntity.entity_value),
    )


def _serialize_canonical_entity_summary(entity: CanonicalEntity, document_count: int = 0) -> CanonicalEntitySummaryResponse:
    return CanonicalEntitySummaryResponse(
        id=str(entity.id),
        entity_type=entity.entity_type,
        canonical_value=entity.canonical_value,
        display_value=entity.display_value,
        review_status=entity.review_status,
        variant_count=len(entity.variants),
        document_count=document_count,
    )


def _serialize_knowledge_context_summary(context: KnowledgeContext) -> KnowledgeContextSummaryResponse:
    memberships = context.memberships
    document_ids = {
        str(membership.document_unit.scan_unit.source_document_id)
        for membership in memberships
        if membership.document_unit.scan_unit is not None
    }
    return KnowledgeContextSummaryResponse(
        id=str(context.id),
        context_kind=context.context_kind,
        label=context.label,
        review_status=context.review_status,
        canonical_entity_id=str(context.canonical_entity_id),
        canonical_entity_type=context.canonical_entity.entity_type,
        canonical_value=context.canonical_entity.canonical_value,
        anchor_count=len(context.anchors),
        document_count=len(document_ids),
        document_unit_count=len(memberships),
        direct_membership_count=sum(
            membership.membership_role == "direct" for membership in memberships
        ),
    )


def _knowledge_context_options():
    return (
        selectinload(KnowledgeContext.canonical_entity),
        selectinload(KnowledgeContext.anchors).selectinload(KnowledgeContextAnchor.canonical_entity),
        selectinload(KnowledgeContext.memberships)
        .selectinload(KnowledgeContextMembership.document_unit)
        .selectinload(DocumentUnit.scan_unit)
        .selectinload(ScanUnit.document),
        selectinload(KnowledgeContext.memberships)
        .selectinload(KnowledgeContextMembership.document_unit)
        .selectinload(DocumentUnit.topic_assignments)
        .selectinload(DocumentUnitTopicAssignment.topic),
    )


def _node_document_units(node: KnowledgeNode) -> list[DocumentUnit]:
    units_by_id: dict[str, DocumentUnit] = {}
    for mention in node.mentions:
        units_by_id[str(mention.document_unit_id)] = mention.document_unit
    for assertion in node.object_assertions:
        units_by_id[str(assertion.document_unit_id)] = assertion.document_unit
    return [unit for unit in units_by_id.values() if unit is not None]


def _serialize_knowledge_node_summary(node: KnowledgeNode) -> KnowledgeNodeSummaryResponse:
    document_ids = {
        str(unit.scan_unit.source_document_id)
        for unit in _node_document_units(node)
        if unit.scan_unit is not None
    }
    return KnowledgeNodeSummaryResponse(
        id=str(node.id),
        canonical_entity_id=str(node.canonical_entity_id) if node.canonical_entity_id else None,
        node_kind=node.node_kind,
        canonical_key=node.canonical_key,
        label=node.label,
        description=node.description,
        review_status=node.review_status,
        alias_count=len(node.aliases),
        document_count=len(document_ids),
        assertion_count=len(node.object_assertions) + len(node.subject_assertions),
    )


def _serialize_knowledge_assertion(assertion: KnowledgeAssertion) -> KnowledgeAssertionResponse:
    return KnowledgeAssertionResponse(
        id=str(assertion.id),
        document_unit_id=str(assertion.document_unit_id),
        predicate_code=assertion.predicate_code,
        predicate_label=assertion.predicate.label if assertion.predicate else assertion.predicate_code,
        value_kind=assertion.predicate.value_kind if assertion.predicate else "unknown",
        object_node_id=str(assertion.object_node_id) if assertion.object_node_id else None,
        object_node_label=assertion.object_node.label if assertion.object_node else None,
        value_json=assertion.value_json,
        value_text=assertion.value_text,
        confidence=assertion.confidence,
        review_status=assertion.review_status,
        source_type=assertion.source_type,
    )


def _serialize_scan_unit(
    scan_unit: ScanUnit,
    include_units: bool = False,
    db: Session | None = None,
) -> dict[str, Any]:
    review_summary = _scan_unit_review_summary(scan_unit)
    effective_status = scan_unit.status
    if scan_unit.status == ScanUnitStatus.NEEDS_REVIEW.value and review_summary["open_count"] == 0:
        effective_status = ScanUnitStatus.ASSIGNED.value
    payload = {
        "id": str(scan_unit.id),
        "source_document_id": str(scan_unit.source_document_id),
        "source_document_version_id": str(scan_unit.source_document_version_id)
        if scan_unit.source_document_version_id
        else None,
        "source_ocr_result_id": str(scan_unit.source_ocr_result_id),
        "page_count": scan_unit.page_count,
        "status": effective_status,
        "segmentation_confidence": scan_unit.segmentation_confidence,
        "classification_confidence": scan_unit.classification_confidence,
        "assignment_confidence": scan_unit.assignment_confidence,
        "preflight": _load_preflight(scan_unit, db),
        "review": review_summary,
        "created_at": scan_unit.created_at,
        "updated_at": scan_unit.updated_at,
    }
    if include_units:
        payload["document_units"] = [
            _serialize_document_unit(doc_unit)
            for doc_unit in sorted(scan_unit.document_units, key=lambda unit: unit.ordinal)
        ]
    return payload


def _load_preflight(scan_unit: ScanUnit, db: Session | None = None) -> dict | None:
    """Load preflight/orientation data from the OCR result for a scan unit."""
    if db is None:
        return None
    ocr_result = db.get(OCRResult, scan_unit.source_ocr_result_id)
    if ocr_result is None or ocr_result.confidence_summary is None:
        return None
    summary = ocr_result.confidence_summary

    preflight = summary.get("preflight") if isinstance(summary.get("preflight"), dict) else {}
    orientation = summary.get("orientation_preprocess") if isinstance(summary.get("orientation_preprocess"), dict) else {}

    return {
        "rotation_applied": orientation.get("rotation_applied"),
        "rotation_confidence": None,
        "page_order_reversed": orientation.get("page_order_reversed", False),
        "orientation_backend": orientation.get("backend"),
        "orientation_applied": orientation.get("applied", False),
        "dominant_declared_rotation": preflight.get("dominant_declared_rotation"),
        "flags": preflight.get("flags", []),
        "warnings": preflight.get("warnings", []),
    }


def _get_or_create_topic_from_payload(
    payload: TopicCreate,
    db: Session,
) -> Topic:
    topic_kind = collection_topic_kind(payload.topic_kind, payload.topic_class)
    existing = db.execute(select(Topic).where(Topic.slug == payload.slug)).scalar_one_or_none()
    if existing is not None:
        existing.title = payload.title
        existing.topic_class = payload.topic_class
        existing.topic_kind = topic_kind
        existing.description = payload.description
        existing.canonical = True
        existing.is_active = True
        existing.updated_at = _utcnow()
        topic = existing
    else:
        topic = Topic(
            slug=payload.slug,
            title=payload.title,
            topic_class=payload.topic_class,
            topic_kind=topic_kind,
            description=payload.description,
            canonical=True,
            is_active=True,
        )
        db.add(topic)
        db.flush()
    alias_values = {topic.slug.lower(), topic.title.lower()}
    alias_values.update(alias.alias.lower() for alias in topic.aliases)
    for candidate_alias in payload.aliases:
        if candidate_alias.lower() not in alias_values:
            db.add(TopicAlias(topic_id=topic.id, alias=candidate_alias))
            alias_values.add(candidate_alias.lower())
    return topic


def _assign_topic_to_document_unit(
    doc_unit: DocumentUnit,
    topic: Topic,
    assignment_role: str,
    db: Session,
    confidence: float | None = None,
    rationale: str | None = None,
) -> DocumentUnitTopicAssignment:
    return upsert_document_unit_topic_assignment(
        session=db,
        doc_unit=doc_unit,
        topic=topic,
        assignment_role=assignment_role,
        confidence=confidence,
        rationale=rationale,
    )


@router.get("/documents/{document_id}")
def get_document_knowledge(document_id: str, db: Session = Depends(get_db_session)):
    """Return scan units and rich document-unit results for a source document."""
    try:
        parsed_document_id = uuid.UUID(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid document ID") from exc

    result = db.execute(
        select(ScanUnit)
        .options(
            selectinload(ScanUnit.document_units).selectinload(DocumentUnit.document_type),
            selectinload(ScanUnit.document_units).selectinload(DocumentUnit.entities),
            selectinload(ScanUnit.document_units)
            .selectinload(DocumentUnit.topic_assignments)
            .selectinload(DocumentUnitTopicAssignment.topic),
            selectinload(ScanUnit.document_units)
            .selectinload(DocumentUnit.proposal)
            .selectinload(TopicProposal.matched_topic),
            selectinload(ScanUnit.document_units).selectinload(DocumentUnit.specialist_jobs),
            selectinload(ScanUnit.document_units).selectinload(DocumentUnit.specialist_results),
            selectinload(ScanUnit.document_units)
            .selectinload(DocumentUnit.outgoing_links)
            .selectinload(DocumentUnitLink.target_document_unit)
            .selectinload(DocumentUnit.document_type),
            selectinload(ScanUnit.document_units)
            .selectinload(DocumentUnit.outgoing_links)
            .selectinload(DocumentUnitLink.target_document_unit)
            .selectinload(DocumentUnit.scan_unit),
        )
        .where(ScanUnit.source_document_id == parsed_document_id)
        .order_by(ScanUnit.created_at.desc())
    )
    scan_units = result.scalars().unique().all()
    return {
        "document_id": document_id,
        "scan_units": [
            _serialize_scan_unit(scan_unit, include_units=True, db=db)
            for scan_unit in scan_units
        ],
    }


# Scan Units
@router.post("/scan-units/from-ocr/{ocr_result_id}", response_model=ScanUnitResponse)
async def create_scan_unit_from_ocr(
    ocr_result_id: str,
    data: ScanUnitCreate,
    db: Session = Depends(get_db_session),
):
    """Create a scan unit from an OCR result and start processing."""
    # Verify OCR result exists
    result = db.execute(
        select(OCRResult).where(OCRResult.id == uuid.UUID(ocr_result_id))
    )
    ocr_result = result.scalar_one_or_none()
    if not ocr_result:
        raise HTTPException(status_code=404, detail="OCR result not found")

    scan_unit, _, _, should_dispatch = ensure_scan_unit_for_ocr_result(db, ocr_result)
    if should_dispatch and not has_active_ingestion_jobs(db):
        mark_knowledge_job_pending_dispatch(db, scan_unit.id)
        db.commit()
        dispatch_scan_unit_processing(str(scan_unit.id))
    else:
        db.commit()

    return ScanUnitResponse(
        id=str(scan_unit.id),
        source_document_id=str(scan_unit.source_document_id),
        source_ocr_result_id=str(scan_unit.source_ocr_result_id),
        page_count=scan_unit.page_count,
        status=scan_unit.status,
        segmentation_confidence=scan_unit.segmentation_confidence,
        classification_confidence=scan_unit.classification_confidence,
        assignment_confidence=scan_unit.assignment_confidence,
        created_at=scan_unit.created_at,
        updated_at=scan_unit.updated_at,
    )


@router.post("/documents/{document_id}/ensure", response_model=ScanUnitResponse)
def ensure_document_knowledge(
    document_id: str,
    db: Session = Depends(get_db_session),
):
    """Ensure a document with OCR result has a queued knowledge scan."""
    try:
        parsed_document_id = uuid.UUID(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid document ID") from exc

    ocr_result = db.execute(
        select(OCRResult)
        .where(OCRResult.document_id == parsed_document_id)
        .order_by(OCRResult.created_at.desc())
    ).scalars().first()
    if ocr_result is None:
        raise HTTPException(status_code=409, detail="OCR result not available yet")

    scan_unit, _, _, should_dispatch = ensure_scan_unit_for_ocr_result(db, ocr_result)
    if should_dispatch and not has_active_ingestion_jobs(db):
        mark_knowledge_job_pending_dispatch(db, scan_unit.id)
        db.commit()
        dispatch_scan_unit_processing(str(scan_unit.id))
    else:
        db.commit()

    return ScanUnitResponse(
        id=str(scan_unit.id),
        source_document_id=str(scan_unit.source_document_id),
        source_ocr_result_id=str(scan_unit.source_ocr_result_id),
        page_count=scan_unit.page_count,
        status=scan_unit.status,
        segmentation_confidence=scan_unit.segmentation_confidence,
        classification_confidence=scan_unit.classification_confidence,
        assignment_confidence=scan_unit.assignment_confidence,
        created_at=scan_unit.created_at,
        updated_at=scan_unit.updated_at,
    )


@router.post("/documents/{document_id}/ensure-specialists")
def ensure_document_specialists(
    document_id: str,
    db: Session = Depends(get_db_session),
):
    """Ensure specialist jobs exist for the latest knowledge scan of a document."""
    try:
        parsed_document_id = uuid.UUID(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid document ID") from exc

    scan_unit = db.execute(
        select(ScanUnit)
        .where(ScanUnit.source_document_id == parsed_document_id)
        .order_by(ScanUnit.created_at.desc())
    ).scalars().first()
    if scan_unit is None:
        raise HTTPException(status_code=404, detail="Knowledge scan not found")

    created_jobs = ensure_specialist_jobs_for_scan_unit(db, scan_unit.id)
    db.commit()
    for specialist_job in created_jobs:
        dispatch_specialist_job(str(specialist_job.id), specialist_job.specialist_type)

    return {
        "scan_unit_id": str(scan_unit.id),
        "created_jobs": len(created_jobs),
        "jobs": [
            {
                "id": str(job.id),
                "specialist_type": job.specialist_type,
                "status": job.status,
            }
            for job in created_jobs
        ],
    }


@router.get("/scan-units", response_model=list[ScanUnitResponse])
def list_scan_units(db: Session = Depends(get_db_session)):
    """List all scan units."""
    result = db.execute(select(ScanUnit).order_by(ScanUnit.created_at.desc()))
    scan_units = result.scalars().all()
    
    return [
        ScanUnitResponse(
            id=str(su.id),
            source_document_id=str(su.source_document_id),
            source_ocr_result_id=str(su.source_ocr_result_id),
            page_count=su.page_count,
            status=su.status,
            segmentation_confidence=su.segmentation_confidence,
            classification_confidence=su.classification_confidence,
            assignment_confidence=su.assignment_confidence,
            created_at=su.created_at,
            updated_at=su.updated_at,
        )
        for su in scan_units
    ]


@router.get("/scan-units/{scan_unit_id}", response_model=ScanUnitResponse)
def get_scan_unit(scan_unit_id: str, db: Session = Depends(get_db_session)):
    """Get a scan unit by ID."""
    result = db.execute(
        select(ScanUnit).where(ScanUnit.id == uuid.UUID(scan_unit_id))
    )
    scan_unit = result.scalar_one_or_none()
    if not scan_unit:
        raise HTTPException(status_code=404, detail="Scan unit not found")
    
    return ScanUnitResponse(
        id=str(scan_unit.id),
        source_document_id=str(scan_unit.source_document_id),
        source_ocr_result_id=str(scan_unit.source_ocr_result_id),
        page_count=scan_unit.page_count,
        status=scan_unit.status,
        segmentation_confidence=scan_unit.segmentation_confidence,
        classification_confidence=scan_unit.classification_confidence,
        assignment_confidence=scan_unit.assignment_confidence,
        created_at=scan_unit.created_at,
        updated_at=scan_unit.updated_at,
    )


# Document Units
@router.get("/scan-units/{scan_unit_id}/document-units", response_model=list[DocumentUnitResponse])
def list_document_units(scan_unit_id: str, db: Session = Depends(get_db_session)):
    """List document units for a scan unit."""
    result = db.execute(
        select(DocumentUnit)
        .options(
            selectinload(DocumentUnit.document_type),
            selectinload(DocumentUnit.entities),
            selectinload(DocumentUnit.topic_assignments).selectinload(DocumentUnitTopicAssignment.topic),
            selectinload(DocumentUnit.proposal).selectinload(TopicProposal.matched_topic),
            selectinload(DocumentUnit.scan_unit).selectinload(ScanUnit.document),
            selectinload(DocumentUnit.specialist_jobs),
            selectinload(DocumentUnit.specialist_results),
            selectinload(DocumentUnit.outgoing_links)
            .selectinload(DocumentUnitLink.target_document_unit)
            .selectinload(DocumentUnit.document_type),
            selectinload(DocumentUnit.outgoing_links)
            .selectinload(DocumentUnitLink.target_document_unit)
            .selectinload(DocumentUnit.scan_unit),
        )
        .where(DocumentUnit.scan_unit_id == uuid.UUID(scan_unit_id))
        .order_by(DocumentUnit.ordinal)
    )
    doc_units = result.scalars().all()

    return [DocumentUnitResponse(**_serialize_document_unit(du)) for du in doc_units]


@router.get("/document-units/{document_unit_id}", response_model=DocumentUnitResponse)
def get_document_unit(document_unit_id: str, db: Session = Depends(get_db_session)):
    """Get a document unit by ID."""
    result = db.execute(
        select(DocumentUnit)
        .options(
            selectinload(DocumentUnit.document_type),
            selectinload(DocumentUnit.entities),
            selectinload(DocumentUnit.topic_assignments).selectinload(DocumentUnitTopicAssignment.topic),
            selectinload(DocumentUnit.proposal).selectinload(TopicProposal.matched_topic),
            selectinload(DocumentUnit.scan_unit).selectinload(ScanUnit.document),
            selectinload(DocumentUnit.specialist_jobs),
            selectinload(DocumentUnit.specialist_results),
            selectinload(DocumentUnit.outgoing_links)
            .selectinload(DocumentUnitLink.target_document_unit)
            .selectinload(DocumentUnit.document_type),
            selectinload(DocumentUnit.outgoing_links)
            .selectinload(DocumentUnitLink.target_document_unit)
            .selectinload(DocumentUnit.scan_unit),
        )
        .where(DocumentUnit.id == uuid.UUID(document_unit_id))
    )
    doc_unit = result.scalar_one_or_none()
    if not doc_unit:
        raise HTTPException(status_code=404, detail="Document unit not found")

    return DocumentUnitResponse(**_serialize_document_unit(doc_unit))


@router.post("/document-units/{document_unit_id}/review", response_model=DocumentUnitResponse)
def review_document_unit(
    document_unit_id: str,
    update: ReviewUpdate,
    db: Session = Depends(get_db_session),
):
    """Update review status for a document unit."""
    result = db.execute(
        select(DocumentUnit)
        .options(
            selectinload(DocumentUnit.document_type),
            selectinload(DocumentUnit.entities),
            selectinload(DocumentUnit.topic_assignments).selectinload(DocumentUnitTopicAssignment.topic),
            selectinload(DocumentUnit.proposal).selectinload(TopicProposal.matched_topic),
            selectinload(DocumentUnit.scan_unit).selectinload(ScanUnit.document),
            selectinload(DocumentUnit.specialist_jobs),
            selectinload(DocumentUnit.specialist_results),
            selectinload(DocumentUnit.outgoing_links)
            .selectinload(DocumentUnitLink.target_document_unit)
            .selectinload(DocumentUnit.document_type),
            selectinload(DocumentUnit.outgoing_links)
            .selectinload(DocumentUnitLink.target_document_unit)
            .selectinload(DocumentUnit.scan_unit),
        )
        .where(DocumentUnit.id == uuid.UUID(document_unit_id))
    )
    doc_unit = result.scalar_one_or_none()
    if not doc_unit:
        raise HTTPException(status_code=404, detail="Document unit not found")
    
    if update.review_status:
        doc_unit.review_status = update.review_status
    if update.title:
        doc_unit.title = update.title
    if doc_unit.scan_unit is not None:
        _refresh_scan_unit_review_status(doc_unit.scan_unit)
    
    db.commit()

    return DocumentUnitResponse(**_serialize_document_unit(doc_unit))


@router.post("/document-units/{document_unit_id}/mark-reviewed", response_model=DocumentUnitResponse)
def mark_document_unit_reviewed(document_unit_id: str, db: Session = Depends(get_db_session)):
    """Mark a document unit as reviewed and refresh its parent scan status."""
    result = db.execute(
        select(DocumentUnit)
        .options(
            selectinload(DocumentUnit.document_type),
            selectinload(DocumentUnit.entities),
            selectinload(DocumentUnit.topic_assignments).selectinload(DocumentUnitTopicAssignment.topic),
            selectinload(DocumentUnit.proposal).selectinload(TopicProposal.matched_topic),
            selectinload(DocumentUnit.scan_unit).selectinload(ScanUnit.document_units),
            selectinload(DocumentUnit.specialist_jobs),
            selectinload(DocumentUnit.specialist_results),
            selectinload(DocumentUnit.outgoing_links)
            .selectinload(DocumentUnitLink.target_document_unit)
            .selectinload(DocumentUnit.document_type),
            selectinload(DocumentUnit.outgoing_links)
            .selectinload(DocumentUnitLink.target_document_unit)
            .selectinload(DocumentUnit.scan_unit),
        )
        .where(DocumentUnit.id == uuid.UUID(document_unit_id))
    )
    doc_unit = result.scalar_one_or_none()
    if doc_unit is None:
        raise HTTPException(status_code=404, detail="Document unit not found")
    if doc_unit.proposal is not None and doc_unit.proposal.proposal_status == "proposed":
        raise HTTPException(status_code=409, detail="Resolve pending topic proposal first")

    doc_unit.review_status = ReviewStatus.HUMAN_REVIEWED.value
    if doc_unit.scan_unit is not None:
        _refresh_scan_unit_review_status(doc_unit.scan_unit)
    db.commit()
    db.refresh(doc_unit)
    return DocumentUnitResponse(**_serialize_document_unit(doc_unit))


@router.post("/scan-units/{scan_unit_id}/mark-reviewed")
def mark_scan_unit_reviewed(scan_unit_id: str, db: Session = Depends(get_db_session)):
    """Mark all non-blocked document units in a scan as reviewed."""
    result = db.execute(
        select(ScanUnit)
        .options(
            selectinload(ScanUnit.document_units).selectinload(DocumentUnit.document_type),
            selectinload(ScanUnit.document_units).selectinload(DocumentUnit.entities),
            selectinload(ScanUnit.document_units)
            .selectinload(DocumentUnit.topic_assignments)
            .selectinload(DocumentUnitTopicAssignment.topic),
            selectinload(ScanUnit.document_units)
            .selectinload(DocumentUnit.proposal)
            .selectinload(TopicProposal.matched_topic),
            selectinload(ScanUnit.document_units).selectinload(DocumentUnit.specialist_jobs),
            selectinload(ScanUnit.document_units).selectinload(DocumentUnit.specialist_results),
            selectinload(ScanUnit.document_units)
            .selectinload(DocumentUnit.outgoing_links)
            .selectinload(DocumentUnitLink.target_document_unit)
            .selectinload(DocumentUnit.document_type),
            selectinload(ScanUnit.document_units)
            .selectinload(DocumentUnit.outgoing_links)
            .selectinload(DocumentUnitLink.target_document_unit)
            .selectinload(DocumentUnit.scan_unit),
        )
        .where(ScanUnit.id == uuid.UUID(scan_unit_id))
    )
    scan_unit = result.scalar_one_or_none()
    if scan_unit is None:
        raise HTTPException(status_code=404, detail="Scan unit not found")

    summary = _scan_unit_review_summary(scan_unit)
    blocking = [issue for issue in summary["issues"] if issue.get("severity") == "blocking"]
    if blocking:
        raise HTTPException(status_code=409, detail="Resolve pending topic proposals first")

    for doc_unit in scan_unit.document_units:
        if doc_unit.review_status == ReviewStatus.NEEDS_REVIEW.value:
            doc_unit.review_status = ReviewStatus.HUMAN_REVIEWED.value
    _refresh_scan_unit_review_status(scan_unit)
    db.commit()
    db.refresh(scan_unit)
    return _serialize_scan_unit(scan_unit, include_units=True, db=db)


@router.post("/document-units/{document_unit_id}/topic-assignments", response_model=DocumentUnitResponse)
def add_document_unit_topic_assignment(
    document_unit_id: str,
    payload: TopicAssignmentUpsert,
    db: Session = Depends(get_db_session),
):
    result = db.execute(
        select(DocumentUnit)
        .options(
            selectinload(DocumentUnit.document_type),
            selectinload(DocumentUnit.entities),
            selectinload(DocumentUnit.topic_assignments).selectinload(DocumentUnitTopicAssignment.topic),
            selectinload(DocumentUnit.proposal).selectinload(TopicProposal.matched_topic),
            selectinload(DocumentUnit.scan_unit).selectinload(ScanUnit.document),
        )
        .where(DocumentUnit.id == uuid.UUID(document_unit_id))
    )
    doc_unit = result.scalar_one_or_none()
    if doc_unit is None:
        raise HTTPException(status_code=404, detail="Document unit not found")

    topic: Topic | None = None
    if payload.topic_id:
        topic = db.execute(select(Topic).where(Topic.id == uuid.UUID(payload.topic_id))).scalar_one_or_none()
        if topic is None:
            raise HTTPException(status_code=404, detail="Topic not found")
    elif payload.create_topic is not None:
        topic = _get_or_create_topic_from_payload(payload.create_topic, db)
    else:
        raise HTTPException(status_code=400, detail="Either topic_id or create_topic is required")

    _assign_topic_to_document_unit(
        doc_unit,
        topic,
        payload.assignment_role,
        db,
        confidence=payload.confidence,
        rationale=payload.rationale,
    )
    doc_unit.review_status = ReviewStatus.HUMAN_REVIEWED.value
    db.commit()
    db.refresh(doc_unit)
    return DocumentUnitResponse(**_serialize_document_unit(doc_unit))


@router.delete("/document-units/{document_unit_id}/topic-assignments/{assignment_id}", response_model=DocumentUnitResponse)
def delete_document_unit_topic_assignment(
    document_unit_id: str,
    assignment_id: str,
    db: Session = Depends(get_db_session),
):
    result = db.execute(
        select(DocumentUnit)
        .options(
            selectinload(DocumentUnit.document_type),
            selectinload(DocumentUnit.entities),
            selectinload(DocumentUnit.topic_assignments).selectinload(DocumentUnitTopicAssignment.topic),
            selectinload(DocumentUnit.proposal).selectinload(TopicProposal.matched_topic),
            selectinload(DocumentUnit.scan_unit).selectinload(ScanUnit.document),
        )
        .where(DocumentUnit.id == uuid.UUID(document_unit_id))
    )
    doc_unit = result.scalar_one_or_none()
    if doc_unit is None:
        raise HTTPException(status_code=404, detail="Document unit not found")

    assignment = next((item for item in doc_unit.topic_assignments if str(item.id) == assignment_id), None)
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    db.delete(assignment)
    doc_unit.review_status = ReviewStatus.HUMAN_REVIEWED.value
    db.commit()
    db.refresh(doc_unit)
    return DocumentUnitResponse(**_serialize_document_unit(doc_unit))


@router.delete("/document-units/{document_unit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document_unit(
    document_unit_id: str,
    db: Session = Depends(get_db_session),
):
    """Delete a document unit and all its derived data (assignments, entities, assertions, specialist results, etc.)."""
    try:
        parsed_id = uuid.UUID(document_unit_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid document unit ID") from exc

    doc_unit = db.get(DocumentUnit, parsed_id)
    if doc_unit is None:
        raise HTTPException(status_code=404, detail="Document unit not found")

    # Delete linked data explicitly before the document unit to ensure clean cascade
    db.execute(delete(DocumentUnitTopicAssignment).where(DocumentUnitTopicAssignment.document_unit_id == parsed_id))
    db.execute(delete(DocumentUnitEntity).where(DocumentUnitEntity.document_unit_id == parsed_id))
    db.execute(delete(DocumentUnitMention).where(DocumentUnitMention.document_unit_id == parsed_id))
    db.execute(delete(KnowledgeAssertion).where(KnowledgeAssertion.document_unit_id == parsed_id))
    db.execute(delete(DocumentUnitLink).where(DocumentUnitLink.source_document_unit_id == parsed_id))
    db.execute(delete(DocumentUnitLink).where(DocumentUnitLink.target_document_unit_id == parsed_id))
    db.execute(delete(SpecialistJob).where(SpecialistJob.document_unit_id == parsed_id))
    db.execute(delete(SpecialistResult).where(SpecialistResult.document_unit_id == parsed_id))
    db.execute(delete(KnowledgeContextMembership).where(KnowledgeContextMembership.document_unit_id == parsed_id))
    db.execute(delete(TopicProposal).where(TopicProposal.source_document_unit_id == parsed_id))

    db.delete(doc_unit)
    db.commit()

    return None


# Topics
@router.get("/topics", response_model=list[TopicSummaryResponse])
def list_topics(
    include_inactive: bool = False,
    topic_kind: str | None = None,
    db: Session = Depends(get_db_session),
):
    """List topics with aggregate counts for knowledge-base browsing."""
    query = (
        select(Topic)
        .options(
            selectinload(Topic.aliases),
            selectinload(Topic.proposals),
            selectinload(Topic.assignments)
            .selectinload(DocumentUnitTopicAssignment.document_unit)
            .selectinload(DocumentUnit.scan_unit),
        )
        .order_by(Topic.created_at.desc())
    )
    if not include_inactive:
        query = query.where(Topic.is_active.is_(True))
    if topic_kind:
        query = query.where(Topic.topic_kind == topic_kind)

    topics = db.execute(query).scalars().unique().all()
    summaries = [_serialize_topic_summary(topic) for topic in topics]
    return sorted(
        summaries,
        key=lambda topic: (
            topic.assignment_count,
            topic.related_document_count,
            topic.proposal_count,
            topic.title.lower(),
        ),
        reverse=True,
    )


@router.get("/topics/{topic_id}", response_model=TopicDetailResponse)
def get_topic(topic_id: str, db: Session = Depends(get_db_session)):
    """Return a topic with aliases and related document units."""
    try:
        parsed_topic_id = uuid.UUID(topic_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid topic ID") from exc

    topic = db.execute(
        select(Topic)
        .options(
            selectinload(Topic.aliases),
            selectinload(Topic.proposals),
            selectinload(Topic.assignments)
            .selectinload(DocumentUnitTopicAssignment.document_unit)
            .selectinload(DocumentUnit.document_type),
            selectinload(Topic.assignments)
            .selectinload(DocumentUnitTopicAssignment.document_unit)
            .selectinload(DocumentUnit.scan_unit)
            .selectinload(ScanUnit.document),
        )
        .where(Topic.id == parsed_topic_id)
    ).scalar_one_or_none()
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return _serialize_topic_detail(topic)


@router.get("/search", response_model=KnowledgeSearchResponse)
def search_knowledge(
    q: str,
    include_inactive: bool = False,
    topic_kind: str | None = None,
    topic_class: str | None = None,
    limit: int = 12,
    db: Session = Depends(get_db_session),
):
    query = q.strip()
    if len(query) < 2:
        return KnowledgeSearchResponse(
            query=query,
            total_topic_hits=0,
            total_document_hits=0,
            topics=[],
            document_units=[],
        )

    pattern = f"%{query}%"

    topic_query = (
        select(Topic)
        .outerjoin(TopicAlias, TopicAlias.topic_id == Topic.id)
        .options(
            selectinload(Topic.aliases),
            selectinload(Topic.proposals),
            selectinload(Topic.assignments)
            .selectinload(DocumentUnitTopicAssignment.document_unit)
            .selectinload(DocumentUnit.scan_unit),
        )
        .where(
            or_(
                Topic.title.ilike(pattern),
                Topic.slug.ilike(pattern),
                Topic.description.ilike(pattern),
                TopicAlias.alias.ilike(pattern),
            )
        )
        .distinct()
        .order_by(Topic.created_at.desc())
    )
    if not include_inactive:
        topic_query = topic_query.where(Topic.is_active.is_(True))
    if topic_kind:
        topic_query = topic_query.where(Topic.topic_kind == topic_kind)
    if topic_class:
        topic_query = topic_query.where(Topic.topic_class == topic_class)

    topic_rows = db.execute(topic_query.limit(limit)).scalars().unique().all()
    topic_hits = [
        KnowledgeSearchTopicHit(
            topic=_serialize_topic_summary(topic),
            aliases=sorted({alias.alias for alias in topic.aliases}),
            matched_fields=_topic_matched_fields(topic, query),
        )
        for topic in topic_rows
    ]

    document_query = (
        select(DocumentUnit)
        .join(ScanUnit, ScanUnit.id == DocumentUnit.scan_unit_id)
        .join(Document, Document.id == ScanUnit.source_document_id)
        .join(OCRResult, OCRResult.id == ScanUnit.source_ocr_result_id)
        .outerjoin(
            DocumentUnitTopicAssignment,
            DocumentUnitTopicAssignment.document_unit_id == DocumentUnit.id,
        )
        .outerjoin(Topic, Topic.id == DocumentUnitTopicAssignment.topic_id)
        .options(
            selectinload(DocumentUnit.document_type),
            selectinload(DocumentUnit.topic_assignments).selectinload(DocumentUnitTopicAssignment.topic),
            selectinload(DocumentUnit.scan_unit).selectinload(ScanUnit.document),
            selectinload(DocumentUnit.scan_unit).selectinload(ScanUnit.ocr_result),
        )
        .where(
            or_(
                Document.original_filename.ilike(pattern),
                Document.external_id.ilike(pattern),
                DocumentUnit.title.ilike(pattern),
                DocumentUnit.extracted_summary.ilike(pattern),
                OCRResult.full_text.ilike(pattern),
                OCRResult.markdown_text.ilike(pattern),
                Topic.title.ilike(pattern),
                Topic.slug.ilike(pattern),
            )
        )
        .distinct()
        .order_by(DocumentUnit.created_at.desc())
    )
    if not include_inactive:
        document_query = document_query.where(or_(Topic.id.is_(None), Topic.is_active.is_(True)))
    if topic_kind:
        document_query = document_query.where(or_(Topic.id.is_(None), Topic.topic_kind == topic_kind))
    if topic_class:
        document_query = document_query.where(or_(Topic.id.is_(None), Topic.topic_class == topic_class))

    document_rows = db.execute(document_query.limit(limit)).scalars().unique().all()
    document_hits = [
        KnowledgeSearchDocumentHit(
            document_unit_id=str(doc_unit.id),
            document_id=str(doc_unit.scan_unit.document.id),
            original_filename=doc_unit.scan_unit.document.original_filename,
            external_id=doc_unit.scan_unit.document.external_id,
            title=doc_unit.title,
            summary=doc_unit.extracted_summary,
            start_page=doc_unit.start_page,
            end_page=doc_unit.end_page,
            review_status=doc_unit.review_status,
            document_type_code=doc_unit.document_type.code if doc_unit.document_type else None,
            topic_titles=[
                assignment.topic.title
                for assignment in doc_unit.topic_assignments
                if assignment.topic is not None and assignment.topic.is_active
            ],
            topic_kinds=[
                assignment.topic.topic_kind
                for assignment in doc_unit.topic_assignments
                if assignment.topic is not None and assignment.topic.is_active
            ],
            matched_fields=_document_unit_matched_fields(doc_unit, query),
        )
        for doc_unit in document_rows
        if doc_unit.scan_unit is not None and doc_unit.scan_unit.document is not None
    ]

    return KnowledgeSearchResponse(
        query=query,
        total_topic_hits=len(topic_hits),
        total_document_hits=len(document_hits),
        topics=topic_hits,
        document_units=document_hits,
    )


@router.get("/search/evidence")
def search_evidence(
    q: str = Query(min_length=2, max_length=1000),
    document_id: str | None = None,
    limit: int = Query(default=8, ge=1, le=20),
    db: Session = Depends(get_db_session),
):
    """Return fused, page-oriented evidence for agents and quality probes."""
    if document_id:
        try:
            uuid.UUID(document_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid document ID") from exc
    return _agent_retrieve_evidence(db, q, document_id=document_id, limit=limit)


@router.get("/specialists/utility-bills")
def list_specialist_utility_bills(
    q: str | None = None,
    issuer: str | None = None,
    payment_status: str | None = None,
    overdue_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    results = db.execute(
        select(SpecialistResult)
        .where(SpecialistResult.specialist_type == "utility_bill")
        .options(
            selectinload(SpecialistResult.document_unit).selectinload(DocumentUnit.document_type),
            selectinload(SpecialistResult.document_unit)
            .selectinload(DocumentUnit.scan_unit)
            .selectinload(ScanUnit.document),
            selectinload(SpecialistResult.document_unit)
            .selectinload(DocumentUnit.outgoing_links)
            .selectinload(DocumentUnitLink.target_document_unit)
            .selectinload(DocumentUnit.document_type),
            selectinload(SpecialistResult.document_unit)
            .selectinload(DocumentUnit.outgoing_links)
            .selectinload(DocumentUnitLink.target_document_unit)
            .selectinload(DocumentUnit.scan_unit),
        )
    ).scalars().all()

    today = _utcnow().date().isoformat()
    normalized_query = _normalize_search_value(q)
    normalized_issuer = _normalize_search_value(issuer)
    items: list[dict[str, Any]] = []
    for result in sorted(results, key=lambda item: item.created_at, reverse=True):
        document_unit = result.document_unit
        if document_unit is None:
            continue
        item = _serialize_specialist_utility_summary(result, document_unit)
        haystack = " ".join(
            str(item.get(field) or "")
            for field in ("issuer", "account_holder", "document_number", "summary", "original_filename", "supply_reference")
        ).lower()
        if normalized_query and normalized_query not in haystack:
            continue
        if normalized_issuer and normalized_issuer not in _normalize_search_value(str(item.get("issuer") or "")):
            continue
        if payment_status and payment_status != "all" and item.get("payment_status") != payment_status:
            continue
        if overdue_only:
            due_date = item.get("due_date")
            if not isinstance(due_date, str) or due_date >= today or item.get("payment_status") == "paid":
                continue
        items.append(item)
        if len(items) >= limit:
            break
    return {"total": len(items), "items": items}


def _serialize_calendar_event(event: CalendarEvent) -> dict[str, Any]:
    document_unit = event.source_document_unit
    document = None
    if document_unit is not None and document_unit.scan_unit is not None:
        document = document_unit.scan_unit.document
    return {
        "id": str(event.id),
        "event_type": event.event_type,
        "title": event.title,
        "subject": event.subject,
        "amount": float(event.amount) if event.amount is not None else None,
        "currency": event.currency,
        "due_date": event.due_date.isoformat(),
        "status": event.status,
        "confidence": event.confidence,
        "review_status": event.review_status,
        "source_document_unit_id": str(event.source_document_unit_id),
        "source_specialist_result_id": str(event.source_specialist_result_id) if event.source_specialist_result_id else None,
        "document_id": str(document.id) if document is not None else None,
        "original_filename": document.original_filename if document is not None else None,
        "document_unit_title": document_unit.title if document_unit is not None else None,
        "document_type_code": (
            document_unit.document_type.code
            if document_unit is not None and document_unit.document_type is not None
            else None
        ),
        "evidence": event.evidence_json or {},
        "created_at": event.created_at.isoformat(),
        "updated_at": event.updated_at.isoformat() if event.updated_at else None,
    }


@router.get("/calendar-events")
def list_calendar_events(
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    review_status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    statement = (
        select(CalendarEvent)
        .options(
            selectinload(CalendarEvent.source_document_unit).selectinload(DocumentUnit.document_type),
            selectinload(CalendarEvent.source_document_unit)
            .selectinload(DocumentUnit.scan_unit)
            .selectinload(ScanUnit.document),
        )
        .order_by(CalendarEvent.due_date.asc(), CalendarEvent.created_at.desc())
    )
    if date_from is not None:
        statement = statement.where(CalendarEvent.due_date >= date_from)
    if date_to is not None:
        statement = statement.where(CalendarEvent.due_date <= date_to)
    if status_filter and status_filter != "all":
        statement = statement.where(CalendarEvent.status == status_filter)
    if review_status and review_status != "all":
        statement = statement.where(CalendarEvent.review_status == review_status)

    normalized_query = _normalize_search_value(q)
    items: list[dict[str, Any]] = []
    for event in db.execute(statement.limit(limit * 2)).scalars().all():
        item = _serialize_calendar_event(event)
        haystack = " ".join(
            str(item.get(field) or "")
            for field in ("title", "subject", "original_filename", "document_unit_title", "document_type_code")
        )
        if normalized_query and normalized_query not in _normalize_search_value(haystack):
            continue
        items.append(item)
        if len(items) >= limit:
            break
    return {"total": len(items), "items": items}


@router.get("/payables")
def list_payables(
    q: str | None = None,
    review_status: str | None = None,
    missing_due_date: bool | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    statement = (
        select(Payable, Document)
        .join(DocumentUnit, DocumentUnit.id == Payable.source_document_unit_id)
        .join(ScanUnit, ScanUnit.id == DocumentUnit.scan_unit_id)
        .join(Document, Document.id == ScanUnit.source_document_id)
        .order_by(Payable.due_date.asc().nulls_first(), Payable.created_at.desc())
    )
    if review_status and review_status != "all":
        statement = statement.where(Payable.review_status == review_status)
    if missing_due_date is True:
        statement = statement.where(Payable.due_date.is_(None))
    normalized_query = _normalize_search_value(q)
    items: list[dict[str, Any]] = []
    for payable, document in db.execute(statement.limit(limit * 2)).all():
        item = {
            "id": str(payable.id),
            "payable_kind": payable.payable_kind,
            "issuer": payable.issuer,
            "recipient": payable.recipient,
            "subject": payable.subject,
            "issue_date": payable.issue_date.isoformat() if payable.issue_date else None,
            "due_date": payable.due_date.isoformat() if payable.due_date else None,
            "amount": float(payable.amount) if payable.amount is not None else None,
            "currency": payable.currency,
            "payment_reference": payable.payment_reference,
            "status": payable.status,
            "review_status": payable.review_status,
            "duplicate_of_id": str(payable.duplicate_of_id) if payable.duplicate_of_id else None,
            "confidence": payable.confidence,
            "evidence": payable.evidence_json or {},
            "document_id": str(document.id),
            "original_filename": document.original_filename,
            "source_document_unit_id": str(payable.source_document_unit_id),
            "source_specialist_result_id": str(payable.source_specialist_result_id),
        }
        haystack = " ".join(str(item.get(field) or "") for field in (
            "issuer", "recipient", "subject", "payment_reference", "original_filename"
        ))
        if normalized_query and normalized_query not in _normalize_search_value(haystack):
            continue
        items.append(item)
        if len(items) >= limit:
            break
    return {"total": len(items), "items": items}


@router.get("/specialists/accounting-statements")
def list_specialist_accounting_statements(
    q: str | None = None,
    statement_type: str | None = None,
    check_status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    results = db.execute(
        select(SpecialistResult)
        .where(SpecialistResult.specialist_type == "accounting_statement")
        .options(
            selectinload(SpecialistResult.document_unit).selectinload(DocumentUnit.document_type),
            selectinload(SpecialistResult.document_unit)
            .selectinload(DocumentUnit.scan_unit)
            .selectinload(ScanUnit.document),
        )
    ).scalars().all()

    normalized_query = _normalize_search_value(q)
    items: list[dict[str, Any]] = []
    for result in sorted(results, key=lambda item: item.created_at, reverse=True):
        document_unit = result.document_unit
        if document_unit is None:
            continue
        item = _serialize_specialist_accounting_summary(result, document_unit)
        haystack = " ".join(
            str(item.get(field) or "")
            for field in ("statement_type", "summary", "original_filename", "title")
        ).lower()
        if normalized_query and normalized_query not in haystack:
            continue
        if statement_type and statement_type != "all" and item.get("statement_type") != statement_type:
            continue
        if check_status and check_status != "all":
            statuses = {
                check.get("status")
                for check in item.get("validation_checks", [])
                if isinstance(check, dict)
            }
            if check_status not in statuses:
                continue
        items.append(item)
        if len(items) >= limit:
            break
    return {"total": len(items), "items": items}


@router.get("/specialist-results/{result_id}/export")
def export_specialist_result(
    result_id: uuid.UUID,
    format: str = Query(default="json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db_session),
):
    result = db.get(SpecialistResult, result_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Specialist result not found")
    if format == "json":
        return JSONResponse(content=result.result_json or {})
    csv_text = _specialist_result_to_csv(result)
    return PlainTextResponse(
        content=csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{result.specialist_type}-{result.id}.csv"',
        },
    )


@router.get("/entities", response_model=list[KnowledgeEntitySummaryResponse])
def list_knowledge_entities(
    q: str | None = None,
    entity_type: str | None = None,
    limit: int = 24,
    db: Session = Depends(get_db_session),
):
    pattern = f"%{q.strip()}%" if q and q.strip() else None
    entity_key = _entity_key_expr().label("entity_key")

    query = (
        select(
            DocumentUnitEntity.entity_type.label("entity_type"),
            entity_key,
            func.max(DocumentUnitEntity.entity_value).label("display_value"),
            func.count(DocumentUnitEntity.id).label("mention_count"),
            func.count(func.distinct(ScanUnit.source_document_id)).label("document_count"),
            func.count(func.distinct(DocumentUnitTopicAssignment.topic_id)).label("topic_count"),
        )
        .join(DocumentUnit, DocumentUnit.id == DocumentUnitEntity.document_unit_id)
        .join(ScanUnit, ScanUnit.id == DocumentUnit.scan_unit_id)
        .outerjoin(
            DocumentUnitTopicAssignment,
            DocumentUnitTopicAssignment.document_unit_id == DocumentUnit.id,
        )
        .group_by(DocumentUnitEntity.entity_type, entity_key)
        .order_by(
            func.count(func.distinct(ScanUnit.source_document_id)).desc(),
            func.count(DocumentUnitEntity.id).desc(),
            func.max(DocumentUnitEntity.entity_value).asc(),
        )
    )
    if entity_type:
        query = query.where(DocumentUnitEntity.entity_type == entity_type)
    if pattern:
        query = query.where(
            or_(
                DocumentUnitEntity.entity_value.ilike(pattern),
                DocumentUnitEntity.normalized_value.ilike(pattern),
            )
        )

    rows = db.execute(query.limit(limit)).all()
    return [
        KnowledgeEntitySummaryResponse(
            entity_type=row.entity_type,
            entity_key=row.entity_key,
            display_value=row.display_value,
            mention_count=row.mention_count,
            document_count=row.document_count,
            topic_count=row.topic_count,
        )
        for row in rows
    ]


@router.get("/entities/detail", response_model=KnowledgeEntityDetailResponse)
def get_knowledge_entity_detail(
    entity_type: str,
    entity_key: str,
    db: Session = Depends(get_db_session),
):
    normalized_key = entity_key.strip().lower()
    if not normalized_key:
        raise HTTPException(status_code=400, detail="entity_key is required")

    entity_key_sql = _entity_key_expr()
    summary_row = db.execute(
        select(
            DocumentUnitEntity.entity_type.label("entity_type"),
            entity_key_sql.label("entity_key"),
            func.max(DocumentUnitEntity.entity_value).label("display_value"),
            func.count(DocumentUnitEntity.id).label("mention_count"),
            func.count(func.distinct(ScanUnit.source_document_id)).label("document_count"),
            func.count(func.distinct(DocumentUnitTopicAssignment.topic_id)).label("topic_count"),
        )
        .join(DocumentUnit, DocumentUnit.id == DocumentUnitEntity.document_unit_id)
        .join(ScanUnit, ScanUnit.id == DocumentUnit.scan_unit_id)
        .outerjoin(
            DocumentUnitTopicAssignment,
            DocumentUnitTopicAssignment.document_unit_id == DocumentUnit.id,
        )
        .where(
            DocumentUnitEntity.entity_type == entity_type,
            entity_key_sql == normalized_key,
        )
        .group_by(DocumentUnitEntity.entity_type, entity_key_sql)
    ).first()
    if summary_row is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    document_units = db.execute(
        select(DocumentUnit)
        .join(DocumentUnitEntity, DocumentUnitEntity.document_unit_id == DocumentUnit.id)
        .join(ScanUnit, ScanUnit.id == DocumentUnit.scan_unit_id)
        .join(Document, Document.id == ScanUnit.source_document_id)
        .options(
            selectinload(DocumentUnit.topic_assignments).selectinload(DocumentUnitTopicAssignment.topic),
            selectinload(DocumentUnit.scan_unit).selectinload(ScanUnit.document),
        )
        .where(
            DocumentUnitEntity.entity_type == entity_type,
            entity_key_sql == normalized_key,
        )
        .order_by(Document.created_at.desc(), DocumentUnit.start_page.asc())
    ).scalars().unique().all()

    return KnowledgeEntityDetailResponse(
        entity_type=summary_row.entity_type,
        entity_key=summary_row.entity_key,
        display_value=summary_row.display_value,
        mention_count=summary_row.mention_count,
        document_count=summary_row.document_count,
        topic_count=summary_row.topic_count,
        documents=[
            KnowledgeEntityDocumentHitResponse(
                document_id=str(doc_unit.scan_unit.document.id),
                document_unit_id=str(doc_unit.id),
                original_filename=doc_unit.scan_unit.document.original_filename,
                external_id=doc_unit.scan_unit.document.external_id,
                title=doc_unit.title,
                summary=doc_unit.extracted_summary,
                review_status=doc_unit.review_status,
                start_page=doc_unit.start_page,
                end_page=doc_unit.end_page,
                topic_titles=[
                    assignment.topic.title
                    for assignment in doc_unit.topic_assignments
                    if assignment.topic is not None and assignment.topic.is_active
                ],
            )
            for doc_unit in document_units
            if doc_unit.scan_unit is not None and doc_unit.scan_unit.document is not None
        ],
    )


@router.get("/canonical-entities", response_model=list[CanonicalEntitySummaryResponse])
def list_canonical_entities(
    q: str | None = None,
    entity_type: str | None = None,
    limit: int = 24,
    db: Session = Depends(get_db_session),
):
    query = (
        select(CanonicalEntity)
        .options(selectinload(CanonicalEntity.variants))
        .order_by(CanonicalEntity.created_at.desc())
    )
    if entity_type:
        query = query.where(CanonicalEntity.entity_type == entity_type)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        query = query.where(
            or_(
                CanonicalEntity.display_value.ilike(pattern),
                CanonicalEntity.canonical_value.ilike(pattern),
            )
        )

    entities = db.execute(query.limit(limit)).scalars().unique().all()
    return [_serialize_canonical_entity_summary(entity) for entity in entities]


@router.post("/canonical-entities/merge", response_model=CanonicalEntityDetailResponse)
def merge_canonical_entities(
    payload: CanonicalEntityMergeRequest,
    db: Session = Depends(get_db_session),
):
    if not payload.entity_keys:
        raise HTTPException(status_code=400, detail="entity_keys is required")

    canonical_entity: CanonicalEntity | None = None
    if payload.target_canonical_entity_id:
        canonical_entity = db.execute(
            select(CanonicalEntity)
            .options(selectinload(CanonicalEntity.variants))
            .where(CanonicalEntity.id == uuid.UUID(payload.target_canonical_entity_id))
        ).scalar_one_or_none()
        if canonical_entity is None:
            raise HTTPException(status_code=404, detail="Canonical entity not found")
    elif payload.create_canonical_entity is not None:
        canonical_entity = get_or_create_canonical_entity(
            db,
            entity_type=payload.create_canonical_entity.entity_type,
            canonical_value=payload.create_canonical_entity.canonical_value,
            display_value=payload.create_canonical_entity.display_value,
            review_status="human_reviewed",
        )
    else:
        raise HTTPException(status_code=400, detail="Provide target_canonical_entity_id or create_canonical_entity")

    for entity_key in payload.entity_keys:
        entity_key_normalized = entity_key.strip().lower()
        if not entity_key_normalized:
            continue
        display_row = db.execute(
            select(func.max(DocumentUnitEntity.entity_value))
            .where(
                DocumentUnitEntity.entity_type == payload.entity_type,
                _entity_key_expr() == entity_key_normalized,
            )
        ).scalar_one_or_none()
        assign_entity_variant(
            db,
            canonical_entity,
            EntityVariantInput(
                entity_type=payload.entity_type,
                entity_key=entity_key_normalized,
                display_value=display_row or entity_key_normalized,
                review_status="human_reviewed",
            ),
        )

    canonical_entity.review_status = "human_reviewed"
    canonical_entity.updated_at = _utcnow()
    db.commit()

    rebuild_semantic_projections(db)
    db.commit()

    db.refresh(canonical_entity)
    document_units = db.execute(
        select(DocumentUnit)
        .join(DocumentUnitEntity, DocumentUnitEntity.document_unit_id == DocumentUnit.id)
        .join(ScanUnit, ScanUnit.id == DocumentUnit.scan_unit_id)
        .join(Document, Document.id == ScanUnit.source_document_id)
        .options(
            selectinload(DocumentUnit.topic_assignments).selectinload(DocumentUnitTopicAssignment.topic),
            selectinload(DocumentUnit.scan_unit).selectinload(ScanUnit.document),
        )
        .where(
            DocumentUnitEntity.entity_type == canonical_entity.entity_type,
            _entity_key_expr().in_([variant.entity_key for variant in canonical_entity.variants]),
        )
        .order_by(Document.created_at.desc(), DocumentUnit.start_page.asc())
    ).scalars().unique().all()

    return CanonicalEntityDetailResponse(
        entity=_serialize_canonical_entity_summary(canonical_entity, document_count=len({str(d.scan_unit.document.id) for d in document_units if d.scan_unit and d.scan_unit.document})),
        variants=[
            CanonicalEntityVariantResponse(
                id=str(variant.id),
                entity_type=variant.entity_type,
                entity_key=variant.entity_key,
                display_value=variant.display_value,
                review_status=variant.review_status,
            )
            for variant in canonical_entity.variants
        ],
        documents=[
            KnowledgeEntityDocumentHitResponse(
                document_id=str(doc_unit.scan_unit.document.id),
                document_unit_id=str(doc_unit.id),
                original_filename=doc_unit.scan_unit.document.original_filename,
                external_id=doc_unit.scan_unit.document.external_id,
                title=doc_unit.title,
                summary=doc_unit.extracted_summary,
                review_status=doc_unit.review_status,
                start_page=doc_unit.start_page,
                end_page=doc_unit.end_page,
                topic_titles=[
                    assignment.topic.title
                    for assignment in doc_unit.topic_assignments
                    if assignment.topic is not None and assignment.topic.is_active
                ],
            )
            for doc_unit in document_units
            if doc_unit.scan_unit is not None and doc_unit.scan_unit.document is not None
        ],
    )


@router.get("/contexts", response_model=list[KnowledgeContextSummaryResponse])
def list_knowledge_contexts(
    q: str | None = None,
    entity_type: str | None = None,
    limit: int = Query(default=30, ge=1, le=200),
    db: Session = Depends(get_db_session),
):
    query = (
        select(KnowledgeContext)
        .join(KnowledgeContextAnchor, KnowledgeContextAnchor.context_id == KnowledgeContext.id)
        .join(CanonicalEntity, CanonicalEntity.id == KnowledgeContextAnchor.canonical_entity_id)
        .options(*_knowledge_context_options())
        .distinct()
        .order_by(KnowledgeContext.label.asc())
    )
    if entity_type:
        query = query.where(CanonicalEntity.entity_type == entity_type)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        query = query.where(
            or_(
                KnowledgeContext.label.ilike(pattern),
                CanonicalEntity.canonical_value.ilike(pattern),
            )
        )
    contexts = db.execute(query.limit(limit)).scalars().unique().all()
    return [_serialize_knowledge_context_summary(context) for context in contexts]


@router.get("/contexts/{context_id}", response_model=KnowledgeContextDetailResponse)
def get_knowledge_context(context_id: uuid.UUID, db: Session = Depends(get_db_session)):
    context = db.execute(
        select(KnowledgeContext)
        .options(*_knowledge_context_options())
        .where(KnowledgeContext.id == context_id)
    ).scalar_one_or_none()
    if context is None:
        raise HTTPException(status_code=404, detail="Knowledge context not found")
    memberships = []
    for membership in context.memberships:
        document_unit = membership.document_unit
        if document_unit.scan_unit is None or document_unit.scan_unit.document is None:
            continue
        document = document_unit.scan_unit.document
        memberships.append(
            KnowledgeContextMembershipResponse(
                document=KnowledgeEntityDocumentHitResponse(
                    document_id=str(document.id),
                    document_unit_id=str(document_unit.id),
                    original_filename=document.original_filename,
                    external_id=document.external_id,
                    title=document_unit.title,
                    summary=document_unit.extracted_summary,
                    review_status=document_unit.review_status,
                    start_page=document_unit.start_page,
                    end_page=document_unit.end_page,
                    topic_titles=[
                        assignment.topic.title
                        for assignment in document_unit.topic_assignments
                        if assignment.topic is not None and assignment.topic.is_active
                    ],
                ),
                membership_role=membership.membership_role,
                confidence=membership.confidence,
                source_type=membership.source_type,
                evidence_json=membership.evidence_json,
            )
        )
    return KnowledgeContextDetailResponse(
        context=_serialize_knowledge_context_summary(context),
        anchors=[
            KnowledgeContextAnchorResponse(
                canonical_entity_id=str(anchor.canonical_entity_id),
                entity_type=anchor.canonical_entity.entity_type,
                canonical_value=anchor.canonical_entity.canonical_value,
                display_value=anchor.canonical_entity.display_value,
                anchor_role=anchor.anchor_role,
            )
            for anchor in context.anchors
        ],
        memberships=memberships,
    )


@router.post("/contexts/rebuild", response_model=KnowledgeContextStatsResponse)
def rebuild_context_projection(db: Session = Depends(get_db_session)):
    stats = rebuild_knowledge_contexts(db)
    db.commit()
    return KnowledgeContextStatsResponse(**stats.__dict__)


@router.get("/contexts/{context_id}/accounting/subjects", response_model=list[ContextAccountingSubjectResponse])
def list_context_accounting_subjects(
    context_id: uuid.UUID,
    q: str | None = None,
    account_key: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db_session),
):
    if db.get(KnowledgeContext, context_id) is None:
        raise HTTPException(status_code=404, detail="Knowledge context not found")
    return find_context_account_subjects(db, context_id, query=q, account_key=account_key, limit=limit)


@router.get("/contexts/{context_id}/accounting/compare", response_model=ContextAccountingComparisonResponse)
def compare_context_accounting(
    context_id: uuid.UUID,
    subject: str = Query(min_length=1),
    period_a_from: date = Query(),
    period_a_to: date = Query(),
    period_b_from: date = Query(),
    period_b_to: date = Query(),
    accounting_role: str = Query(default="actual_allocation"),
    account_key: str | None = None,
    db: Session = Depends(get_db_session),
):
    if db.get(KnowledgeContext, context_id) is None:
        raise HTTPException(status_code=404, detail="Knowledge context not found")
    return compare_context_accounting_periods(
        db,
        context_id,
        subject=subject,
        account_key=account_key,
        period_a_from=period_a_from,
        period_a_to=period_a_to,
        period_b_from=period_b_from,
        period_b_to=period_b_to,
        accounting_role=accounting_role,
    )


@router.post("/agent/chat", response_model=KnowledgeAgentChatResponse)
def chat_with_knowledge_agent(
    payload: KnowledgeAgentChatRequest,
    db: Session = Depends(get_db_session),
):
    started = time.monotonic()
    provider = _knowledge_agent_provider(db)
    if provider is None:
        raise HTTPException(status_code=503, detail="LLM backend is not configured")

    automatic_context, trace, seen_tool_signatures = _prepare_automatic_agent_evidence(db, payload)
    messages = _build_knowledge_agent_messages(payload, db, automatic_context=automatic_context)
    tool_budget = _agent_budget_from_trace(trace)
    vision_requests: list[KnowledgeAgentVisionRequest] = []
    final_action: _KnowledgeAgentAction | None = None
    blocked_tool_attempts = 0

    for step in range(1, payload.max_steps + 1):
        try:
            action, _ = provider.chat_with_json(messages, _KnowledgeAgentAction, temperature=0.1, max_retries=2)
            action = _KnowledgeAgentAction.model_validate(action)
        except Exception as exc:
            trace.append(
                KnowledgeAgentTraceStep(
                    step=step,
                    action="llm_error",
                    error=str(exc),
                )
            )
            break

        action_input = action.model_dump(
            mode="json",
            exclude={"answer", "confidence", "citations"},
            exclude_none=True,
        )
        if action.action == "final_answer":
            action = _normalize_knowledge_agent_final(action)
            final_error = _validate_knowledge_agent_final(action, trace)
            if final_error:
                trace.append(
                    KnowledgeAgentTraceStep(
                        step=step,
                        action="invalid_final_answer",
                        reasoning=action.reasoning,
                        input=action_input,
                        error=final_error,
                    )
                )
                messages.append(ChatMessage(role="assistant", content=action.model_dump_json(exclude_none=True)))
                messages.append(
                    ChatMessage(
                        role="user",
                        content=(
                            f"La final_answer non e' valida: {final_error}. "
                            "Prima leggi le pagine rilevanti con get_page_text se necessario, poi produci una "
                            "final_answer con answer non vuoto e citations contenenti document_id, page_from/page_to "
                            "e quote breve."
                        ),
                    )
                )
                continue
            final_action = action
            trace.append(
                KnowledgeAgentTraceStep(
                    step=step,
                    action=action.action,
                    reasoning=action.reasoning,
                    input=action_input,
                    output={"answer": action.answer, "confidence": action.confidence},
                )
            )
            break

        tool_output: dict[str, Any] | list[Any]
        error: str | None = None
        try:
            signature = _knowledge_agent_tool_signature(action)
            if signature in seen_tool_signatures:
                tool_output = {
                    "status": "repeated_tool_skipped",
                    "message": "Identical tool call already executed in this run; choose a different query/tool or finalize.",
                }
            else:
                seen_tool_signatures.add(signature)
                budget_error = tool_budget.consume(action.action)
                if budget_error:
                    tool_output = {"status": "tool_budget_exhausted", "message": budget_error}
                else:
                    tool_output = _run_knowledge_agent_tool(db, action, allow_vision=payload.allow_vision)
                    if action.action == "request_page_vision" and isinstance(tool_output, dict):
                        request = tool_output.get("vision_request")
                        if isinstance(request, dict):
                            vision_requests.append(KnowledgeAgentVisionRequest.model_validate(request))
        except Exception as exc:
            tool_output = {}
            error = str(exc)

        trace.append(
            KnowledgeAgentTraceStep(
                step=step,
                action=action.action,
                reasoning=action.reasoning,
                input=action_input,
                output=tool_output,
                error=error,
            )
        )
        messages.append(ChatMessage(role="assistant", content=action.model_dump_json(exclude_none=True)))
        messages.append(
            ChatMessage(
                role="user",
                content=f"Risultato tool {action.action}: {tool_output if error is None else {'error': error}}",
            )
        )
        if isinstance(tool_output, dict) and tool_output.get("status") in {
            "repeated_tool_skipped", "tool_budget_exhausted",
        }:
            blocked_tool_attempts += 1
            if blocked_tool_attempts >= 2:
                break
        else:
            blocked_tool_attempts = 0

    if final_action is None:
        final_action, final_step = _force_knowledge_agent_final_answer(provider, messages, trace, payload.max_steps + 1)
        if final_step is not None:
            trace.append(final_step)

    if final_action is None:
        response = KnowledgeAgentChatResponse(
            status="incomplete",
            answer=(
                "Non sono riuscito a produrre una risposta con fonti pagina verificabili. "
                "Controlla il trace: l'agente deve leggere le pagine con get_page_text prima di rispondere."
            ),
            confidence=None,
            tool_trace=trace,
            citations=[],
            vision_requests=vision_requests,
            model=provider.model_name,
        )
        response.run_id = _persist_knowledge_agent_run(
            db,
            payload=payload,
            response=response,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return response

    citations = [
        KnowledgeAgentCitation.model_validate(item)
        for item in final_action.citations
        if isinstance(item, dict) and any(value is not None for value in item.values())
    ]
    response = KnowledgeAgentChatResponse(
        status="answered",
        answer=final_action.answer or "",
        confidence=final_action.confidence,
        tool_trace=trace,
        citations=citations,
        vision_requests=vision_requests,
        model=provider.model_name,
    )
    response.run_id = _persist_knowledge_agent_run(
        db,
        payload=payload,
        response=response,
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return response


@router.get("/agent/runs", response_model=list[KnowledgeAgentRunSummary])
def list_knowledge_agent_runs(
    limit: int = Query(default=25, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db_session),
):
    stmt = select(KnowledgeAgentRun).order_by(KnowledgeAgentRun.created_at.desc()).limit(limit)
    if status_filter:
        stmt = stmt.where(KnowledgeAgentRun.status == status_filter)
    runs = db.execute(stmt).scalars().all()
    return [_serialize_knowledge_agent_run_summary(run) for run in runs]


@router.get("/agent/runs/{run_id}", response_model=KnowledgeAgentRunDetail)
def get_knowledge_agent_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db_session),
):
    run = db.get(KnowledgeAgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Knowledge agent run not found")
    return _serialize_knowledge_agent_run_detail(run)


@router.post("/agent/chat/stream")
def stream_knowledge_agent_chat(
    payload: KnowledgeAgentChatRequest,
    db: Session = Depends(get_db_session),
):
    provider = _knowledge_agent_provider(db)
    if provider is None:
        raise HTTPException(status_code=503, detail="LLM backend is not configured")

    def event_stream():
        started = time.monotonic()
        automatic_context, trace, seen_tool_signatures = _prepare_automatic_agent_evidence(db, payload)
        messages = _build_knowledge_agent_messages(payload, db, automatic_context=automatic_context)
        tool_budget = _agent_budget_from_trace(trace)
        vision_requests: list[KnowledgeAgentVisionRequest] = []
        final_action: _KnowledgeAgentAction | None = None
        blocked_tool_attempts = 0

        yield _knowledge_agent_stream_event("status", {"status": "running", "model": provider.model_name})
        for trace_step in trace:
            yield _knowledge_agent_stream_event("step", trace_step.model_dump(mode="json"))
        for step in range(1, payload.max_steps + 1):
            try:
                action, _ = provider.chat_with_json(messages, _KnowledgeAgentAction, temperature=0.1, max_retries=2)
                action = _KnowledgeAgentAction.model_validate(action)
            except Exception as exc:
                trace_step = KnowledgeAgentTraceStep(step=step, action="llm_error", error=str(exc))
                trace.append(trace_step)
                yield _knowledge_agent_stream_event("step", trace_step.model_dump(mode="json"))
                break

            action_input = action.model_dump(
                mode="json",
                exclude={"answer", "confidence", "citations"},
                exclude_none=True,
            )
            if action.action == "final_answer":
                action = _normalize_knowledge_agent_final(action)
                final_error = _validate_knowledge_agent_final(action, trace)
                if final_error:
                    trace_step = KnowledgeAgentTraceStep(
                        step=step,
                        action="invalid_final_answer",
                        reasoning=action.reasoning,
                        input=action_input,
                        error=final_error,
                    )
                    trace.append(trace_step)
                    yield _knowledge_agent_stream_event("step", trace_step.model_dump(mode="json"))
                    messages.append(ChatMessage(role="assistant", content=action.model_dump_json(exclude_none=True)))
                    messages.append(
                        ChatMessage(
                            role="user",
                            content=(
                                f"La final_answer non e' valida: {final_error}. "
                                "Prima leggi le pagine rilevanti con get_page_text se necessario, poi produci una "
                                "final_answer con answer non vuoto e citations contenenti document_id, page_from/page_to "
                                "e quote breve."
                            ),
                        )
                    )
                    continue
                final_action = action
                trace_step = KnowledgeAgentTraceStep(
                    step=step,
                    action=action.action,
                    reasoning=action.reasoning,
                    input=action_input,
                    output={"answer": action.answer, "confidence": action.confidence},
                )
                trace.append(trace_step)
                yield _knowledge_agent_stream_event("step", trace_step.model_dump(mode="json"))
                break

            tool_output: dict[str, Any] | list[Any]
            error: str | None = None
            try:
                signature = _knowledge_agent_tool_signature(action)
                if signature in seen_tool_signatures:
                    tool_output = {
                        "status": "repeated_tool_skipped",
                        "message": "Identical tool call already executed in this run; choose a different query/tool or finalize.",
                    }
                else:
                    seen_tool_signatures.add(signature)
                    budget_error = tool_budget.consume(action.action)
                    if budget_error:
                        tool_output = {"status": "tool_budget_exhausted", "message": budget_error}
                    else:
                        tool_output = _run_knowledge_agent_tool(db, action, allow_vision=payload.allow_vision)
                        if action.action == "request_page_vision" and isinstance(tool_output, dict):
                            request = tool_output.get("vision_request")
                            if isinstance(request, dict):
                                vision_requests.append(KnowledgeAgentVisionRequest.model_validate(request))
            except Exception as exc:
                tool_output = {}
                error = str(exc)

            trace_step = KnowledgeAgentTraceStep(
                step=step,
                action=action.action,
                reasoning=action.reasoning,
                input=action_input,
                output=tool_output,
                error=error,
            )
            trace.append(trace_step)
            yield _knowledge_agent_stream_event("step", trace_step.model_dump(mode="json"))
            messages.append(ChatMessage(role="assistant", content=action.model_dump_json(exclude_none=True)))
            messages.append(
                ChatMessage(
                    role="user",
                    content=f"Risultato tool {action.action}: {tool_output if error is None else {'error': error}}",
                )
            )
            if isinstance(tool_output, dict) and tool_output.get("status") in {
                "repeated_tool_skipped", "tool_budget_exhausted",
            }:
                blocked_tool_attempts += 1
                if blocked_tool_attempts >= 2:
                    break
            else:
                blocked_tool_attempts = 0

        if final_action is None:
            final_action, final_step = _force_knowledge_agent_final_answer(provider, messages, trace, payload.max_steps + 1)
            if final_step is not None:
                trace.append(final_step)
                yield _knowledge_agent_stream_event("step", final_step.model_dump(mode="json"))

        if final_action is None:
            response = KnowledgeAgentChatResponse(
                status="incomplete",
                answer=(
                    "Non sono riuscito a produrre una risposta con fonti pagina verificabili. "
                    "Controlla il trace: l'agente deve leggere le pagine con get_page_text prima di rispondere."
                ),
                confidence=None,
                tool_trace=trace,
                citations=[],
                vision_requests=vision_requests,
                model=provider.model_name,
            )
        else:
            citations = [
                KnowledgeAgentCitation.model_validate(item)
                for item in final_action.citations
                if isinstance(item, dict) and any(value is not None for value in item.values())
            ]
            response = KnowledgeAgentChatResponse(
                status="answered",
                answer=final_action.answer or "",
                confidence=final_action.confidence,
                tool_trace=trace,
                citations=citations,
                vision_requests=vision_requests,
                model=provider.model_name,
            )
        response.run_id = _persist_knowledge_agent_run(
            db,
            payload=payload,
            response=response,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        yield _knowledge_agent_stream_event("final", response.model_dump(mode="json"))

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.get("/agent/search-index/stats", response_model=KnowledgeSearchIndexStats)
def get_knowledge_search_index_stats(
    db: Session = Depends(get_db_session),
):
    return _knowledge_search_index_stats(db)


@router.post("/agent/search-index/rebuild", response_model=KnowledgeSearchIndexRebuildResponse)
def rebuild_knowledge_search_index(
    db: Session = Depends(get_db_session),
):
    try:
        return _rebuild_knowledge_search_index(db)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Embedding backend unavailable or incompatible: {exc}",
        ) from exc


@router.post(
    "/agent/search-index/documents/{document_id}/refresh",
    response_model=KnowledgeSearchIndexRebuildResponse,
)
def refresh_document_search_index(
    document_id: str,
    db: Session = Depends(get_db_session),
):
    try:
        parsed_id = uuid.UUID(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid document ID") from exc
    if db.get(Document, parsed_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        return _refresh_document_search_index(db, parsed_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Embedding backend unavailable or incompatible: {exc}",
        ) from exc


def _validate_knowledge_agent_final(
    action: _KnowledgeAgentAction,
    trace: list[KnowledgeAgentTraceStep],
) -> str | None:
    if not action.answer or not action.answer.strip():
        return "final_answer requires a non-empty answer"

    citations = [
        KnowledgeAgentCitation.model_validate(item)
        for item in action.citations
        if isinstance(item, dict) and any(value is not None for value in item.values())
    ]
    if not citations:
        if _is_supported_no_evidence_answer(action, trace):
            return None
        return "final_answer requires at least one citation"

    for citation in citations:
        if not citation.document_id:
            return "each citation requires document_id"
        if citation.page_from is None and citation.page_to is None:
            return "each citation requires page_from or page_to"
        if not _trace_has_page_evidence_for_citation(trace, citation):
            return "each cited document/page must have been read with get_page_text or analyze_page_image before final_answer"
    return None


def _build_knowledge_agent_messages(
    payload: KnowledgeAgentChatRequest,
    db: Session | None = None,
    *,
    automatic_context: str = "",
) -> list[ChatMessage]:
    messages = [
        ChatMessage(
            role="system",
            content=(
                "Sei un agente read-only che interroga un archivio documentale tramite tool. "
                "Non inventare fatti: usa i tool per cercare documenti, topic, testo OCR e risultati specialistici. "
                "Per trovare documenti e pagine usa prima retrieve_evidence, che fonde ricerca keyword e semantica. "
                "Prima di rispondere su un documento devi leggere il testo OCR con get_page_text per le pagine rilevanti. "
                "Dopo aver identificato un documento lungo, richiama retrieve_evidence con document_id per localizzare "
                "le pagine rilevanti invece di sfogliarlo pagina per pagina. "
                "Le PAGINE LETTE AUTOMATICAMENTE nel contesto sono evidenze gia' verificate e citabili: "
                "rispondi direttamente se bastano, senza ripetere retrieve_evidence o get_page_text. "
                "Non ripetere la stessa azione con gli stessi parametri se il risultato precedente non era utile: "
                "allarga la query, leggi una pagina candidata, oppure produci una final_answer negativa se non ci sono prove. "
                "Per domande su bollette da pagare, scadenze, fornitori, importi o calendari usa search_calendar_events: "
                "supplier/query sono ricerche testuali substring case-insensitive, mentre date_from/date_to e "
                "amount_min/amount_max sono filtri liberi su scadenza e importo. "
                "Per domande su bilanci, riparti, spese per soggetto o confronti tra esercizi usa "
                "query_accounting_tables: passa la domanda in query, l'eventuale document_id, subject e i due "
                "intervalli period_a/period_b se sono espliciti. Il tool esegue i calcoli sulle tabelle specialistiche "
                "e restituisce evidence; leggi poi le pagine indicate prima di citarle. "
                "Non inventare mai document_id o document_unit_id da nomi descrittivi: usa solo id restituiti dai tool "
                "o gia' presenti nella conversazione. "
                "Se l'utente ha selezionato documenti, trattali come contesto iniziale forte ma non come vincolo: "
                "puoi e devi usare comunque tutti i tool sull'intero archivio quando serve. "
                "La final_answer deve includere answer non vuoto e citations con document_id, page_from/page_to "
                "e quote breve per ogni affermazione documentale. Non mettere la risposta solo in reasoning. "
                "Se il testo OCR non basta e servirebbe vedere la pagina, usa analyze_page_image quando vision e' consentita. "
                "Se vision non e' consentita ma servirebbe, usa request_page_vision. "
                "Non fingere di aver visto immagini: cita solo analisi prodotte dal tool analyze_page_image."
            ),
        )
    ]
    selected_context = _build_selected_document_context(db, payload.selected_document_ids)
    if selected_context:
        messages.append(
            ChatMessage(
                role="user",
                content=(
                    "Documenti selezionati dall'utente come contesto iniziale. "
                    "Questo contesto non limita lo scope dei tool.\n\n"
                    f"{selected_context}"
                ),
            )
        )
    if automatic_context:
        messages.append(
            ChatMessage(
                role="user",
                content=(
                    "Evidenze recuperate e lette automaticamente prima del ragionamento. "
                    "Ogni blocco riporta documento e pagina e puo' essere citato nella final_answer.\n\n"
                    f"{automatic_context}"
                ),
            )
        )
    for item in payload.history[-12:]:
        messages.append(
            ChatMessage(
                role=item.role,
                content=f"Messaggio precedente ({item.role}): {item.content}",
            )
        )
    messages.append(
        ChatMessage(
            role="user",
            content=(
                f"Domanda utente: {payload.question}\n"
                f"Vision consentita dall'utente: {payload.allow_vision}.\n"
                "Scegli una sola azione JSON alla volta."
            ),
        )
    )
    return messages


def _prepare_automatic_agent_evidence(
    db: Session,
    payload: KnowledgeAgentChatRequest,
    *,
    page_limit: int = 3,
) -> tuple[str, list[KnowledgeAgentTraceStep], set[str]]:
    trace: list[KnowledgeAgentTraceStep] = []
    signatures: set[str] = set()
    try:
        retrieval = _agent_retrieve_evidence(db, payload.question, document_id=None, limit=max(page_limit * 2, 6))
    except Exception as exc:
        trace.append(KnowledgeAgentTraceStep(step=0, action="automatic_retrieve_evidence", error=str(exc)))
        return "", trace, signatures

    retrieval_action = _KnowledgeAgentAction(action="retrieve_evidence", query=payload.question, limit=max(page_limit * 2, 6))
    signatures.add(_knowledge_agent_tool_signature(retrieval_action))
    trace.append(
        KnowledgeAgentTraceStep(
            step=0,
            action="retrieve_evidence",
            reasoning="automatic evidence retrieval",
            input={"query": payload.question, "limit": max(page_limit * 2, 6)},
            output=retrieval,
        )
    )
    blocks: list[str] = []
    seen_pages: set[tuple[str, int]] = set()
    for candidate in retrieval.get("results", []):
        document_id = candidate.get("document_id")
        page_number = candidate.get("page_from")
        if not document_id or not isinstance(page_number, int):
            continue
        page_key = (document_id, page_number)
        if page_key in seen_pages:
            continue
        seen_pages.add(page_key)
        try:
            page = _agent_page_text(db, document_id, page_number)
        except Exception as exc:
            trace.append(
                KnowledgeAgentTraceStep(
                    step=0,
                    action="get_page_text",
                    input={"document_id": document_id, "page_number": page_number},
                    error=str(exc),
                )
            )
            continue
        action = _KnowledgeAgentAction(
            action="get_page_text",
            document_id=document_id,
            page_number=page_number,
        )
        signatures.add(_knowledge_agent_tool_signature(action))
        trace.append(
            KnowledgeAgentTraceStep(
                step=0,
                action="get_page_text",
                reasoning="automatic evidence read",
                input={"document_id": document_id, "page_number": page_number},
                output=page,
            )
        )
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        blocks.append(
            "\n".join(
                [
                    "PAGINA LETTA AUTOMATICAMENTE",
                    f"document_id: {document_id}",
                    f"filename: {metadata.get('original_filename') or 'n/d'}",
                    f"page: {page_number}",
                    f"text: {page.get('text', '')}",
                ]
            )
        )
        if len(blocks) >= page_limit:
            break
    return "\n\n---\n\n".join(blocks), trace, signatures


def _build_selected_document_context(db: Session | None, document_ids: list[str]) -> str:
    if db is None or not document_ids:
        return ""
    unique_ids = list(dict.fromkeys(document_ids))[:8]
    blocks: list[str] = []
    for raw_id in unique_ids:
        try:
            doc_uuid = uuid.UUID(raw_id)
        except ValueError:
            blocks.append(f"Documento selezionato non valido: {raw_id}")
            continue
        document = db.get(Document, doc_uuid)
        if document is None:
            blocks.append(f"Documento selezionato non trovato: {raw_id}")
            continue
        ocr = db.execute(
            select(OCRResult)
            .where(OCRResult.document_id == doc_uuid)
            .order_by(OCRResult.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        units = db.execute(
            select(DocumentUnit)
            .join(ScanUnit, ScanUnit.id == DocumentUnit.scan_unit_id)
            .where(ScanUnit.source_document_id == doc_uuid)
            .options(
                selectinload(DocumentUnit.document_type),
                selectinload(DocumentUnit.topic_assignments).selectinload(DocumentUnitTopicAssignment.topic),
            )
            .order_by(DocumentUnit.ordinal)
        ).scalars().all()

        lines = [
            "DOCUMENTO SELEZIONATO",
            f"document_id: {document.id}",
            f"filename: {document.original_filename}",
            f"external_id: {document.external_id or 'n/d'}",
            f"size_bytes: {document.size_bytes}",
        ]
        if ocr is not None:
            lines.append(f"ocr_pages: {ocr.page_count}")
        if units:
            lines.append("document_units:")
            for unit in units[:20]:
                topic_titles = [
                    assignment.topic.title
                    for assignment in unit.topic_assignments
                    if assignment.topic is not None
                ]
                unit_type = unit.document_type.code if unit.document_type is not None else "n/d"
                lines.append(
                    "- "
                    f"document_unit_id={unit.id}; "
                    f"title={unit.title or 'n/d'}; "
                    f"type={unit_type}; "
                    f"pages={unit.start_page}-{unit.end_page}; "
                    f"topics={', '.join(topic_titles) if topic_titles else 'n/d'}; "
                    f"summary={(unit.extracted_summary or 'n/d')[:900]}"
                )
        if ocr is None:
            lines.append("ocr_text: n/d")
        elif len(ocr.full_text) <= 12000:
            lines.append("ocr_text_full:")
            lines.append(ocr.full_text)
        else:
            lines.append(
                "ocr_text_full: omesso per lunghezza; usa search_document_text e get_page_text per leggere pagine specifiche."
            )
            if not units:
                lines.append("ocr_text_excerpt:")
                lines.append(ocr.full_text[:3000])
        blocks.append("\n".join(lines))
    return "\n\n---\n\n".join(blocks)


def _build_question_presearch_context(db: Session | None, question: str) -> str:
    if db is None:
        return ""
    collected: list[dict[str, Any]] = []
    seen: set[tuple[str | None, int | None]] = set()
    for query in _presearch_query_variants(question):
        try:
            result = _agent_search_document_text(db, None, query, limit=5)
        except Exception:
            continue
        hits = result.get("hits") if isinstance(result, dict) else None
        if not isinstance(hits, list):
            continue
        for hit in hits:
            key = (hit.get("document_id"), hit.get("page_number"))
            if key in seen:
                continue
            seen.add(key)
            collected.append({**hit, "matched_query": query})
            if len(collected) >= 8:
                break
        if len(collected) >= 8:
            break
    if not collected:
        return ""
    lines = ["PAGINE CANDIDATE DA VERIFICARE:"]
    for hit in collected[:8]:
        lines.append(
            "- "
            f"query={hit.get('matched_query')}; "
            f"document_id={hit.get('document_id')}; "
            f"filename={hit.get('original_filename') or 'n/d'}; "
            f"page={hit.get('page_number')}; "
            f"score={hit.get('score')}; "
            f"snippet={hit.get('snippet')}"
        )
    return "\n".join(lines)


def _presearch_query_variants(question: str) -> list[str]:
    variants: list[str] = []
    normalized = _normalize_search_text(question)
    years = re.findall(r"\b(?:19|20)\d{2}\b", question)
    if (
        ("imposta" in normalized or "tassa" in normalized or "tribut" in normalized)
        and ("casa" in normalized or "immobil" in normalized or "abitaz" in normalized)
    ):
        suffix = f" {' '.join(years)}" if years else ""
        variants.append(f"ICI imposta comunale immobili{suffix}")
        variants.append(f"quietanza pagamento ICI{suffix}")
    variants.append(question)
    return list(dict.fromkeys(item.strip() for item in variants if item.strip()))


def _knowledge_agent_stream_event(event_type: str, payload: dict[str, Any]) -> str:
    return json.dumps({"type": event_type, "payload": payload}, default=str, ensure_ascii=False) + "\n"


def _force_knowledge_agent_final_answer(
    provider: OpenAICompatibleProvider,
    messages: list[ChatMessage],
    trace: list[KnowledgeAgentTraceStep],
    step: int,
) -> tuple[_KnowledgeAgentAction | None, KnowledgeAgentTraceStep | None]:
    forced_messages = [
        *messages,
        ChatMessage(
            role="user",
            content=(
                "Il budget di tool e' esaurito. Non chiamare altri tool. "
                "Se nel trace hai gia' letto pagine rilevanti con get_page_text o analyze_page_image, produci ora solo final_answer "
                "con answer non vuoto e citations document_id/page_from/page_to. "
                "Se non hai trovato prove dopo ricerche reali, produci final_answer negativa spiegando che non ci sono "
                "fonti disponibili nel trace e lascia citations vuoto."
            ),
        ),
    ]
    try:
        action, _ = provider.chat_with_json(forced_messages, _KnowledgeAgentAction, temperature=0.1, max_retries=2)
        action = _KnowledgeAgentAction.model_validate(action)
    except Exception as exc:
        return None, KnowledgeAgentTraceStep(step=step, action="llm_error", error=str(exc))

    action_input = action.model_dump(
        mode="json",
        exclude={"answer", "confidence", "citations"},
        exclude_none=True,
    )
    if action.action != "final_answer":
        return None, KnowledgeAgentTraceStep(
            step=step,
            action="invalid_final_answer",
            reasoning=action.reasoning,
            input=action_input,
            error="forced finalization returned another tool action",
        )

    action = _normalize_knowledge_agent_final(action)
    final_error = _validate_knowledge_agent_final(action, trace)
    if final_error:
        return None, KnowledgeAgentTraceStep(
            step=step,
            action="invalid_final_answer",
            reasoning=action.reasoning,
            input=action_input,
            error=final_error,
        )
    return action, KnowledgeAgentTraceStep(
        step=step,
        action=action.action,
        reasoning=action.reasoning,
        input=action_input,
        output={"answer": action.answer, "confidence": action.confidence},
    )


def _normalize_knowledge_agent_final(action: _KnowledgeAgentAction) -> _KnowledgeAgentAction:
    if action.action != "final_answer":
        return action

    patch: dict[str, Any] = {}
    if (not action.answer or not action.answer.strip()) and action.reasoning.strip():
        patch["answer"] = action.reasoning.strip()

    if not action.citations and action.document_id and action.page_number is not None:
        citation: dict[str, Any] = {
            "document_id": action.document_id,
            "page_from": action.page_number,
            "page_to": action.page_number,
        }
        patch["citations"] = [citation]

    if not patch:
        return action
    return action.model_copy(update=patch)


def _trace_has_page_evidence_for_citation(
    trace: list[KnowledgeAgentTraceStep],
    citation: KnowledgeAgentCitation,
) -> bool:
    page_from = citation.page_from if citation.page_from is not None else citation.page_to
    page_to = citation.page_to if citation.page_to is not None else citation.page_from
    if page_from is None or page_to is None:
        return False

    for step in trace:
        if step.action not in {"get_page_text", "analyze_page_image"} or step.error:
            continue
        output = step.output
        if not isinstance(output, dict):
            continue
        if str(output.get("document_id")) != citation.document_id:
            continue
        page_number = output.get("page_number")
        if isinstance(page_number, int) and page_from <= page_number <= page_to:
            if step.action == "get_page_text":
                text = output.get("text")
                return isinstance(text, str) and bool(text.strip())
            analysis = output.get("analysis")
            if not isinstance(analysis, dict):
                return False
            evidence = analysis.get("page_summary") or analysis.get("relevant_text") or analysis.get("answer_hint")
            return isinstance(evidence, str) and bool(evidence.strip())
    return False


def _is_supported_no_evidence_answer(
    action: _KnowledgeAgentAction,
    trace: list[KnowledgeAgentTraceStep],
) -> bool:
    text = f"{action.answer or ''} {action.reasoning or ''}".lower()
    no_evidence_markers = (
        "non ho trovato",
        "non sono stati trovati",
        "nessun documento",
        "nessuna fonte",
        "nessuna evidenza",
        "non risultano",
        "non e' possibile fornire",
        "non è possibile fornire",
    )
    if not any(marker in text for marker in no_evidence_markers):
        return False
    searched_steps = 0
    for step in trace:
        if step.error:
            continue
        if step.action in {"retrieve_evidence", "search_archive", "semantic_search", "search_document_text", "search_calendar_events", "list_topics"}:
            searched_steps += 1
    return searched_steps >= 2


def _persist_knowledge_agent_run(
    db: Session,
    *,
    payload: KnowledgeAgentChatRequest,
    response: KnowledgeAgentChatResponse,
    duration_ms: int,
) -> str:
    run = KnowledgeAgentRun(
        question=payload.question,
        answer=response.answer,
        status=response.status,
        model=response.model,
        confidence=response.confidence,
        allow_vision=payload.allow_vision,
        max_steps=payload.max_steps,
        tool_trace_json=[step.model_dump(mode="json") for step in response.tool_trace],
        citations_json=[citation.model_dump(mode="json") for citation in response.citations],
        vision_requests_json=[request.model_dump(mode="json") for request in response.vision_requests],
        duration_ms=duration_ms,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return str(run.id)


def _serialize_knowledge_agent_run_summary(run: KnowledgeAgentRun) -> KnowledgeAgentRunSummary:
    return KnowledgeAgentRunSummary(
        id=str(run.id),
        question=run.question,
        answer=run.answer,
        status=run.status,
        model=run.model,
        confidence=run.confidence,
        allow_vision=run.allow_vision,
        max_steps=run.max_steps,
        tool_step_count=len(run.tool_trace_json or []),
        citation_count=len(run.citations_json or []),
        vision_request_count=len(run.vision_requests_json or []),
        duration_ms=run.duration_ms,
        created_at=run.created_at,
    )


def _serialize_knowledge_agent_run_detail(run: KnowledgeAgentRun) -> KnowledgeAgentRunDetail:
    summary = _serialize_knowledge_agent_run_summary(run)
    return KnowledgeAgentRunDetail(
        **summary.model_dump(),
        tool_trace=[
            KnowledgeAgentTraceStep.model_validate(item)
            for item in (run.tool_trace_json or [])
            if isinstance(item, dict)
        ],
        citations=[
            KnowledgeAgentCitation.model_validate(item)
            for item in (run.citations_json or [])
            if isinstance(item, dict)
        ],
        vision_requests=[
            KnowledgeAgentVisionRequest.model_validate(item)
            for item in (run.vision_requests_json or [])
            if isinstance(item, dict)
        ],
    )


def _embedding_provider(db: Session) -> OpenAICompatibleProvider:
    settings = get_knowledge_settings()
    defaults = {
        "embedding_endpoint": (
        os.getenv("KN_EMBEDDING_ENDPOINT")
        or os.getenv("KN_WORKER_LLM_ENDPOINT")
        or settings.embedding_endpoint
        or settings.llm_endpoint
        ),
        "embedding_model": os.getenv("KN_EMBEDDING_MODEL", settings.embedding_model),
    }
    runtime = resolve_runtime_settings(db, defaults)
    return OpenAICompatibleProvider(
        base_url=runtime["embedding_endpoint"],
        model=runtime["embedding_model"],
        api_key=settings.llm_api_key,
        timeout=max(settings.embedding_timeout, 120),
        max_tokens=None,
    )


def _agent_semantic_search(
    db: Session,
    query: str,
    *,
    limit: int,
    document_id: str | None = None,
) -> dict[str, Any]:
    if not query.strip():
        return {"query": query, "results": [], "warning": "semantic_search requires a non-empty query"}
    provider = _embedding_provider(db)
    query_embedding = provider.embed(query)[0]
    document_filter = "AND document_id = CAST(:document_id AS uuid)" if document_id else ""
    rows = db.execute(
        text(
            f"""
            SELECT
                source_type,
                source_id::text AS source_id,
                document_id::text AS document_id,
                document_unit_id::text AS document_unit_id,
                page_from,
                page_to,
                left(text, 900) AS snippet,
                metadata_json,
                embedding_model,
                (embedding <=> CAST(:embedding AS vector)) AS distance
            FROM knowledge_search_chunks
            WHERE embedding_model = :embedding_model
              {document_filter}
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
            """
        ),
        {
            "embedding": _vector_literal(query_embedding),
            "embedding_model": provider.model_name,
            "document_id": document_id,
            "limit": limit,
        },
    ).mappings().all()
    return {
        "query": query,
        "embedding_model": provider.model_name,
        "results": [
            {
                "source_type": row["source_type"],
                "source_id": row["source_id"],
                "document_id": row["document_id"],
                "document_unit_id": row["document_unit_id"],
                "page_from": row["page_from"],
                "page_to": row["page_to"],
                "snippet": row["snippet"],
                "metadata": row["metadata_json"],
                "embedding_model": row["embedding_model"],
                "distance": float(row["distance"]),
                "score": max(0.0, 1.0 - float(row["distance"])),
            }
            for row in rows
        ],
    }


def _agent_lexical_index_search(
    db: Session,
    query: str,
    *,
    limit: int,
    document_id: str | None = None,
) -> dict[str, Any]:
    if not query.strip():
        return {"query": query, "hits": [], "warning": "query is empty"}
    provider = _embedding_provider(db)
    terms = [term for term in re.findall(r"[\w]+", query.lower()) if len(term) >= 3]
    if not terms:
        return {"query": query, "hits": [], "warning": "query has no searchable terms"}
    ts_query = " | ".join(f"{term}:*" for term in terms)
    document_filter = "AND document_id = CAST(:document_id AS uuid)" if document_id else ""
    rows = db.execute(
        text(f"""
            SELECT
                source_type,
                source_id::text AS source_id,
                document_id::text AS document_id,
                document_unit_id::text AS document_unit_id,
                page_from,
                page_to,
                left(text, 900) AS snippet,
                metadata_json,
                greatest(
                    ts_rank_cd(to_tsvector('simple', text), to_tsquery('simple', :ts_query)),
                    similarity(text, :query)
                ) AS score
            FROM knowledge_search_chunks
            WHERE embedding_model = :embedding_model
              {document_filter}
              AND (
                  to_tsvector('simple', text) @@ to_tsquery('simple', :ts_query)
                  OR text % :query
              )
            ORDER BY score DESC, page_from NULLS LAST
            LIMIT :limit
        """),
        {
            "query": query.strip(),
            "ts_query": ts_query,
            "embedding_model": provider.model_name,
            "document_id": document_id,
            "limit": limit,
        },
    ).mappings().all()
    return {
        "query": query,
        "hits": [
            {
                "source_type": row["source_type"],
                "source_id": row["source_id"],
                "document_id": row["document_id"],
                "document_unit_id": row["document_unit_id"],
                "page_from": row["page_from"],
                "page_to": row["page_to"],
                "snippet": row["snippet"],
                "metadata": row["metadata_json"],
                "score": float(row["score"]),
            }
            for row in rows
        ],
    }


def _knowledge_search_index_stats(db: Session) -> KnowledgeSearchIndexStats:
    active_model = _embedding_provider(db).model_name
    total = int(db.execute(
        text("SELECT count(*) FROM knowledge_search_chunks WHERE embedding_model = :model"),
        {"model": active_model},
    ).scalar_one())
    by_source = {
        row["source_type"]: int(row["count"])
        for row in db.execute(
            text(
                """
                SELECT source_type, count(*) AS count
                FROM knowledge_search_chunks
                WHERE embedding_model = :model
                GROUP BY source_type
                ORDER BY source_type
                """
            ),
            {"model": active_model},
        ).mappings()
    }
    models = [
        row["embedding_model"]
        for row in db.execute(
            text(
                """
                SELECT DISTINCT embedding_model
                FROM knowledge_search_chunks
                ORDER BY embedding_model
                """
            )
        ).mappings()
    ]
    indexed_at = db.execute(
        text("SELECT max(created_at) FROM knowledge_search_chunks WHERE embedding_model = :model"),
        {"model": active_model},
    ).scalar_one()
    source_updated_at = db.execute(text("""
        SELECT max(changed_at) FROM (
            SELECT max(created_at) AS changed_at FROM ocr_results
            UNION ALL SELECT max(COALESCE(updated_at, created_at)) FROM document_units
            UNION ALL SELECT max(COALESCE(updated_at, created_at)) FROM specialist_results
            UNION ALL SELECT max(COALESCE(updated_at, created_at)) FROM topics
        ) AS source_changes
    """)).scalar_one()
    return KnowledgeSearchIndexStats(
        total_chunks=total,
        by_source_type=by_source,
        embedding_models=models,
        active_model=active_model,
        indexed_at=indexed_at,
        source_updated_at=source_updated_at,
        is_stale=source_updated_at is not None and (indexed_at is None or source_updated_at > indexed_at),
    )


def _rebuild_knowledge_search_index(db: Session) -> KnowledgeSearchIndexRebuildResponse:
    provider = _embedding_provider(db)
    chunks = _collect_knowledge_search_chunks(db)
    db.execute(text("DELETE FROM knowledge_search_chunks WHERE embedding_model = :model"), {"model": provider.model_name})
    chunks_indexed, chunks_skipped = _index_knowledge_search_chunks(db, provider, chunks)
    db.commit()
    stats = _knowledge_search_index_stats(db)
    return KnowledgeSearchIndexRebuildResponse(
        status="rebuilt",
        chunks_indexed=chunks_indexed,
        chunks_skipped=chunks_skipped,
        **stats.model_dump(),
    )


def _refresh_document_search_index(
    db: Session,
    document_id: uuid.UUID,
) -> KnowledgeSearchIndexRebuildResponse:
    provider = _embedding_provider(db)
    chunks = _collect_knowledge_search_chunks(db, document_id=document_id)
    db.execute(
        text("""
            DELETE FROM knowledge_search_chunks
            WHERE embedding_model = :model AND document_id = :document_id
        """),
        {"model": provider.model_name, "document_id": document_id},
    )
    chunks_indexed, chunks_skipped = _index_knowledge_search_chunks(db, provider, chunks)
    db.commit()
    stats = _knowledge_search_index_stats(db)
    return KnowledgeSearchIndexRebuildResponse(
        status="document_refreshed",
        chunks_indexed=chunks_indexed,
        chunks_skipped=chunks_skipped,
        **stats.model_dump(),
    )


def _index_knowledge_search_chunks(
    db: Session,
    provider: OpenAICompatibleProvider,
    chunks: list[dict[str, Any]],
) -> tuple[int, int]:
    chunks_indexed = 0
    chunks_skipped = 0
    batch_size = 12
    for offset in range(0, len(chunks), batch_size):
        batch = chunks[offset : offset + batch_size]
        embeddings = None
        for attempt, delay in enumerate((0, 5, 15), start=1):
            if delay:
                time.sleep(delay)
            try:
                embeddings = provider.embed([chunk["text"] for chunk in batch])
                break
            except Exception:
                if attempt == 3:
                    db.rollback()
                    raise
        if embeddings is None:
            raise RuntimeError("Embedding provider returned no batch")
        for chunk, embedding in zip(batch, embeddings, strict=False):
            if not embedding:
                chunks_skipped += 1
                continue
            insert_result = db.execute(
                text(
                    """
                    INSERT INTO knowledge_search_chunks (
                        id,
                        source_type,
                        source_id,
                        document_id,
                        document_unit_id,
                        page_from,
                        page_to,
                        text,
                        text_hash,
                        metadata_json,
                        embedding,
                        embedding_model
                    )
                    VALUES (
                        :id,
                        :source_type,
                        CAST(:source_id AS uuid),
                        CAST(:document_id AS uuid),
                        CAST(:document_unit_id AS uuid),
                        :page_from,
                        :page_to,
                        :text_value,
                        :text_hash,
                        CAST(:metadata_json AS json),
                        CAST(:embedding AS vector),
                        :embedding_model
                    )
                    ON CONFLICT (text_hash, embedding_model) DO NOTHING
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "source_type": chunk["source_type"],
                    "source_id": chunk.get("source_id"),
                    "document_id": chunk.get("document_id"),
                    "document_unit_id": chunk.get("document_unit_id"),
                    "page_from": chunk.get("page_from"),
                    "page_to": chunk.get("page_to"),
                    "text_value": chunk["text"],
                    "text_hash": chunk["text_hash"],
                    "metadata_json": json.dumps(chunk.get("metadata", {}), ensure_ascii=True),
                    "embedding": _vector_literal(embedding),
                    "embedding_model": provider.model_name,
                },
            )
            if insert_result.rowcount:
                chunks_indexed += 1
            else:
                chunks_skipped += 1
    return chunks_indexed, chunks_skipped


def _collect_knowledge_search_chunks(
    db: Session,
    document_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    topics = [] if document_id else db.execute(
        select(Topic)
        .where(Topic.is_active.is_(True))
        .options(selectinload(Topic.aliases))
        .order_by(Topic.created_at.asc())
    ).scalars().all()
    for topic in topics:
        aliases = [alias.alias for alias in topic.aliases]
        text_value = "\n".join(
            item
            for item in [
                f"Topic: {topic.title}",
                f"Slug: {topic.slug}",
                f"Classe: {topic.topic_class}",
                f"Tipo: {topic.topic_kind}",
                f"Alias: {', '.join(aliases)}" if aliases else "",
                f"Descrizione: {topic.description}" if topic.description else "",
            ]
            if item
        )
        chunks.append(
            _make_search_chunk(
                source_type="topic",
                source_id=str(topic.id),
                document_id=None,
                document_unit_id=None,
                page_from=None,
                page_to=None,
                text_value=text_value,
                metadata={"title": topic.title, "slug": topic.slug, "aliases": aliases},
            )
        )

    units_query = (
        select(DocumentUnit)
        .options(
            selectinload(DocumentUnit.scan_unit).selectinload(ScanUnit.document),
            selectinload(DocumentUnit.document_type),
            selectinload(DocumentUnit.topic_assignments).selectinload(DocumentUnitTopicAssignment.topic),
        )
        .order_by(DocumentUnit.created_at.asc())
    )
    if document_id:
        units_query = units_query.join(DocumentUnit.scan_unit).where(
            ScanUnit.source_document_id == document_id
        )
    units = db.execute(units_query).scalars().unique().all()
    for unit in units:
        document = unit.scan_unit.document if unit.scan_unit else None
        topic_titles = [
            assignment.topic.title
            for assignment in unit.topic_assignments
            if assignment.topic and assignment.topic.is_active
        ]
        text_value = "\n".join(
            item
            for item in [
                f"Documento: {document.original_filename}" if document else "",
                f"Unita: {unit.title}" if unit.title else "",
                f"Tipo: {unit.document_type.code}" if unit.document_type else "",
                f"Pagine: {unit.start_page}-{unit.end_page}",
                f"Topic: {', '.join(topic_titles)}" if topic_titles else "",
                f"Sommario: {unit.extracted_summary}" if unit.extracted_summary else "",
            ]
            if item
        )
        chunks.append(
            _make_search_chunk(
                source_type="document_unit",
                source_id=str(unit.id),
                document_id=str(document.id) if document else None,
                document_unit_id=str(unit.id),
                page_from=unit.start_page,
                page_to=unit.end_page,
                text_value=text_value,
                metadata={
                    "title": unit.title,
                    "original_filename": document.original_filename if document else None,
                    "document_type_code": unit.document_type.code if unit.document_type else None,
                    "topic_titles": topic_titles,
                },
            )
        )

    latest_ocr_by_document: dict[uuid.UUID, OCRResult] = {}
    ocr_query = select(OCRResult).order_by(OCRResult.created_at.asc())
    if document_id:
        ocr_query = ocr_query.where(OCRResult.document_id == document_id)
    for ocr in db.execute(ocr_query).scalars().all():
        latest_ocr_by_document[ocr.document_id] = ocr
    unit_by_document_page: dict[tuple[str, int], DocumentUnit] = {}
    for unit in units:
        document = unit.scan_unit.document if unit.scan_unit else None
        if not document:
            continue
        for page_number in range(unit.start_page, unit.end_page + 1):
            unit_by_document_page[(str(document.id), page_number)] = unit

    for ocr in latest_ocr_by_document.values():
        for page_number in range(1, max(ocr.page_count, 1) + 1):
            page_text = _extract_ocr_page_text(ocr, page_number).strip()
            if not page_text:
                continue
            unit = unit_by_document_page.get((str(ocr.document_id), page_number))
            page_chunks = _split_search_text(page_text)
            for chunk_index, page_chunk in enumerate(page_chunks):
                chunks.append(
                    _make_search_chunk(
                        source_type="ocr_page",
                        source_id=str(ocr.id),
                        document_id=str(ocr.document_id),
                        document_unit_id=str(unit.id) if unit else None,
                        page_from=page_number,
                        page_to=page_number,
                        text_value=page_chunk,
                        metadata={
                            "page_number": page_number,
                            "chunk_index": chunk_index,
                            "page_chunk_count": len(page_chunks),
                            "document_unit_title": unit.title if unit else None,
                        },
                    )
                )

    latest_specialist_by_unit_type: dict[tuple[uuid.UUID, str], SpecialistResult] = {}
    specialist_results = db.execute(
        select(SpecialistResult).order_by(SpecialistResult.created_at.asc())
    ).scalars().all()
    for result in specialist_results:
        latest_specialist_by_unit_type[(result.document_unit_id, result.specialist_type)] = result
    units_by_id = {unit.id: unit for unit in units}
    for result in latest_specialist_by_unit_type.values():
        unit = units_by_id.get(result.document_unit_id)
        document = unit.scan_unit.document if unit and unit.scan_unit else None
        if not unit or not document:
            continue
        for evidence in _specialist_search_evidence(result, unit):
            chunks.append(
                _make_search_chunk(
                    source_type="specialist_result",
                    source_id=str(result.id),
                    document_id=str(document.id),
                    document_unit_id=str(unit.id),
                    page_from=evidence["page_from"],
                    page_to=evidence["page_to"],
                    text_value=evidence["text"],
                    metadata={
                        "specialist_type": result.specialist_type,
                        "review_status": result.review_status,
                        "confidence": result.confidence,
                        "document_unit_title": unit.title,
                        **evidence.get("metadata", {}),
                    },
                )
            )
    return chunks


def _specialist_search_evidence(
    result: SpecialistResult,
    unit: DocumentUnit,
) -> list[dict[str, Any]]:
    payload = result.result_json if isinstance(result.result_json, dict) else {}
    values = [f"Specialista: {result.specialist_type}"]
    if result.specialist_type == "utility_bill":
        labels = {
            "issuer": "Fornitore",
            "service_type": "Servizio",
            "account_holder": "Intestatario",
            "issue_date": "Data emissione",
            "due_date": "Scadenza",
            "billing_period_from": "Periodo da",
            "billing_period_to": "Periodo a",
            "total_amount": "Importo",
            "currency": "Valuta",
            "document_number": "Numero documento",
            "contract_code": "Contratto",
            "supply_reference": "Fornitura",
        }
        values.extend(
            f"{label}: {payload[key]}"
            for key, label in labels.items()
            if payload.get(key) not in (None, "")
        )
        return [{
            "text": "\n".join(values),
            "page_from": unit.start_page,
            "page_to": unit.end_page,
            "metadata": {},
        }]
    if result.specialist_type == "accounting_statement":
        values.extend(
            f"{label}: {payload[key]}"
            for key, label in {
                "statement_type": "Tipo bilancio",
                "accounting_period_from": "Periodo da",
                "accounting_period_to": "Periodo a",
                "currency": "Valuta",
            }.items()
            if payload.get(key) not in (None, "")
        )
        evidence: list[dict[str, Any]] = []
        for table in payload.get("tables", []) or []:
            if not isinstance(table, dict):
                continue
            explanation = table.get("llm_explanation")
            description = (
                explanation.get("summary") if isinstance(explanation, dict) else None
            ) or table.get("description") or table.get("explanation") or table.get("title")
            page_number = table.get("page_number")
            page = int(page_number) if isinstance(page_number, (int, float)) else unit.start_page
            table_values = [
                *values,
                f"Tabella: {table.get('table_type') or table.get('table_id')}",
                f"Descrizione: {description}" if description else "",
                f"Colonne: {', '.join(str(header) for header in table.get('headers', [])[:20])}",
            ]
            evidence.append({
                "text": "\n".join(value for value in table_values if value),
                "page_from": page,
                "page_to": page,
                "metadata": {
                    "table_id": table.get("table_id"),
                    "table_type": table.get("table_type"),
                    "explanation_source": explanation.get("source") if isinstance(explanation, dict) else None,
                },
            })
        return evidence or [{
            "text": "\n".join(values),
            "page_from": unit.start_page,
            "page_to": unit.end_page,
            "metadata": {},
        }]
    summary = payload.get("summary") or payload.get("description")
    if summary:
        values.append(f"Sintesi: {summary}")
    return [{
        "text": "\n".join(values),
        "page_from": unit.start_page,
        "page_to": unit.end_page,
        "metadata": {},
    }]


def _make_search_chunk(
    *,
    source_type: str,
    source_id: str | None,
    document_id: str | None,
    document_unit_id: str | None,
    page_from: int | None,
    page_to: int | None,
    text_value: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    normalized_text = re.sub(r"\s+", " ", text_value).strip()[:400]
    text_hash = hashlib.sha256(
        (
            f"{source_type}\n{source_id}\n{document_id}\n{document_unit_id}\n"
            f"{page_from}\n{page_to}\n{normalized_text}"
        ).encode("utf-8")
    ).hexdigest()
    return {
        "source_type": source_type,
        "source_id": source_id,
        "document_id": document_id,
        "document_unit_id": document_unit_id,
        "page_from": page_from,
        "page_to": page_to,
        "text": normalized_text,
        "text_hash": text_hash,
        "metadata": metadata,
    }


def _split_search_text(text_value: str, *, max_chars: int = 400, overlap: int = 60) -> list[str]:
    normalized = re.sub(r"\s+", " ", text_value).strip()
    if len(normalized) <= max_chars:
        return [normalized] if normalized else []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + max_chars)
        if end < len(normalized):
            boundary = normalized.rfind(" ", start + max_chars // 2, end)
            if boundary > start:
                end = boundary
        chunks.append(normalized[start:end].strip())
        if end >= len(normalized):
            break
        start = max(start + 1, end - overlap)
    return [chunk for chunk in chunks if chunk]


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.8f}" for value in values) + "]"


@router.post("/accounting/ask", response_model=AccountingAskResponse)
def ask_accounting(
    payload: AccountingAskRequest,
    db: Session = Depends(get_db_session),
):
    """Answer natural-language accounting questions over LLM-guided table views.

    This endpoint treats specialist ``summary_view`` payloads as dataframe-like
    tables. The LLM is used only to plan the query; arithmetic and evidence
    collection remain deterministic.
    """
    if payload.context_id and payload.document_id:
        raise HTTPException(status_code=400, detail="Use either context_id or document_id, not both")

    tables = _accounting_summary_dataframes(
        db,
        context_id=payload.context_id,
        document_id=payload.document_id,
    )
    if not tables:
        return {
            "status": "no_accounting_tables",
            "answer": "Non ho trovato tabelle contabili sintetiche nello scope richiesto.",
            "warnings": ["Serve almeno un risultato contabile con summary_view."],
            "plan": {},
            "tables_used": [],
            "computed_table": [],
            "evidence": [],
        }

    plan = _plan_accounting_question(db, payload, tables)
    subject = payload.subject or plan.subject or _fallback_subject_from_question(payload.question)
    if not subject:
        return {
            "status": "needs_subject",
            "answer": "Non riesco a identificare il soggetto contabile nella domanda.",
            "warnings": ["Specifica un cognome, nominativo o codice unita."],
            "plan": plan.model_dump(mode="json"),
            "tables_used": _accounting_table_summaries(tables),
            "computed_table": [],
            "evidence": [],
        }

    period_a_from = payload.period_a_from or plan.period_a_from
    period_a_to = payload.period_a_to or plan.period_a_to
    period_b_from = payload.period_b_from or plan.period_b_from
    period_b_to = payload.period_b_to or plan.period_b_to
    if not all([period_a_from, period_a_to, period_b_from, period_b_to]):
        inferred = _infer_two_periods(tables)
        period_a_from = period_a_from or inferred.get("period_a_from")
        period_a_to = period_a_to or inferred.get("period_a_to")
        period_b_from = period_b_from or inferred.get("period_b_from")
        period_b_to = period_b_to or inferred.get("period_b_to")
    if not period_a_from or not period_a_to:
        inferred_latest = _infer_latest_period(tables)
        period_a_from = period_a_from or inferred_latest.get("period_from")
        period_a_to = period_a_to or inferred_latest.get("period_to")

    matching_rows = _matching_accounting_rows(tables, subject)
    if not matching_rows:
        return {
            "status": "subject_not_found",
            "answer": f"Non ho trovato righe contabili corrispondenti a '{subject}'.",
            "warnings": [],
            "plan": plan.model_dump(mode="json") | {"subject": subject},
            "tables_used": _accounting_table_summaries(tables),
            "computed_table": [],
            "evidence": [],
        }

    period_a_rows = _rows_for_period(matching_rows, period_a_from, period_a_to)
    period_b_rows = _rows_for_period(matching_rows, period_b_from, period_b_to)
    if period_a_rows and not period_b_rows and not payload.period_b_from and not payload.period_b_to:
        summary = _summarize_accounting_dataframe_rows(period_a_rows)
        answer = _accounting_single_period_answer_text(subject, summary)
        return {
            "status": "answered_single_period",
            "answer": answer,
            "warnings": summary["warnings"],
            "plan": plan.model_dump(mode="json") | {
                "subject": subject,
                "period_a_from": period_a_from.isoformat() if period_a_from else None,
                "period_a_to": period_a_to.isoformat() if period_a_to else None,
                "period_b_from": None,
                "period_b_to": None,
            },
            "tables_used": _accounting_table_summaries(tables),
            "computed_table": summary["rows"],
            "evidence": summary["evidence"],
        }
    if not period_a_rows or not period_b_rows:
        available = sorted({
            f"{row['period_from']} - {row['period_to']}"
            for row in matching_rows
            if row.get("period_from") or row.get("period_to")
        })
        return {
            "status": "insufficient_periods",
            "answer": "Ho trovato il soggetto, ma non ho due periodi confrontabili nello scope richiesto.",
            "warnings": [f"Periodi disponibili: {', '.join(available) or 'n/d'}"],
            "plan": plan.model_dump(mode="json") | {"subject": subject},
            "tables_used": _accounting_table_summaries(tables),
            "computed_table": [],
            "evidence": [],
        }

    comparison = _compare_accounting_dataframe_rows(period_a_rows, period_b_rows)
    answer = _accounting_answer_text(subject, comparison)
    return {
        "status": "answered",
        "answer": answer,
        "warnings": comparison["warnings"],
        "plan": plan.model_dump(mode="json") | {
            "subject": subject,
            "period_a_from": period_a_from.isoformat() if period_a_from else None,
            "period_a_to": period_a_to.isoformat() if period_a_to else None,
            "period_b_from": period_b_from.isoformat() if period_b_from else None,
            "period_b_to": period_b_to.isoformat() if period_b_to else None,
        },
        "tables_used": _accounting_table_summaries(tables),
        "computed_table": comparison["rows"],
        "evidence": comparison["evidence"],
    }


def _normalize_search_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value.lower())
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", ascii_value).strip()


def _accounting_llm_provider(db: Session) -> OpenAICompatibleProvider | None:
    settings = get_knowledge_settings()
    runtime = resolve_runtime_settings(db, {
        "llm_endpoint": os.getenv("KN_WORKER_LLM_ENDPOINT", settings.llm_endpoint),
        "llm_model": settings.llm_model,
    })
    endpoint = runtime["llm_endpoint"]
    if endpoint.startswith("mock://"):
        return None
    return OpenAICompatibleProvider(
        base_url=endpoint,
        model=runtime["llm_model"],
        api_key=settings.llm_api_key,
        timeout=max(settings.llm_timeout, 120),
        max_tokens=min(settings.llm_max_tokens, 2048),
    )


def _knowledge_agent_provider(db: Session) -> OpenAICompatibleProvider | None:
    settings = get_knowledge_settings()
    runtime = resolve_runtime_settings(db, {
        "llm_endpoint": os.getenv("KN_WORKER_LLM_ENDPOINT", settings.llm_endpoint),
        "llm_model": settings.llm_model,
    })
    endpoint = runtime["llm_endpoint"]
    if endpoint.startswith("mock://"):
        return None
    return OpenAICompatibleProvider(
        base_url=endpoint,
        model=runtime["llm_model"],
        api_key=settings.llm_api_key,
        timeout=max(settings.llm_timeout, 180),
        max_tokens=min(settings.llm_max_tokens, 4096),
    )


def _run_knowledge_agent_tool(
    db: Session,
    action: _KnowledgeAgentAction,
    *,
    allow_vision: bool,
) -> dict[str, Any] | list[Any]:
    limit = max(1, min(action.limit or 8, 20))
    if action.action == "retrieve_evidence":
        return _agent_retrieve_evidence(
            db, action.query or "", document_id=action.document_id, limit=limit
        )
    if action.action == "search_archive":
        return _agent_search_archive(db, action.query or "", limit=limit)
    if action.action == "semantic_search":
        return _agent_semantic_search(db, action.query or "", limit=limit)
    if action.action == "list_topics":
        return _agent_list_topics(db, action.query, limit=limit)
    if action.action == "get_document_unit":
        if not action.document_unit_id:
            raise ValueError("document_unit_id is required")
        return _agent_document_unit(db, action.document_unit_id)
    if action.action == "get_document":
        if not action.document_id:
            raise ValueError("document_id is required")
        return _agent_document(db, action.document_id)
    if action.action == "search_document_text":
        return _agent_search_document_text(db, action.document_id, action.query or "", limit=limit)
    if action.action == "get_page_text":
        if not action.document_id or action.page_number is None:
            raise ValueError("document_id and page_number are required")
        return _agent_page_text(db, action.document_id, action.page_number)
    if action.action == "analyze_page_image":
        if not allow_vision:
            return {"status": "vision_not_allowed_by_user"}
        if not action.document_id or action.page_number is None:
            raise ValueError("document_id and page_number are required")
        return _agent_analyze_page_image(db, action.document_id, action.page_number, action.reasoning)
    if action.action == "request_page_vision":
        if not allow_vision:
            return {"vision_request": None, "status": "vision_not_allowed_by_user"}
        if not action.document_id or action.page_number is None:
            raise ValueError("document_id and page_number are required")
        return {
            "status": "vision_requested",
            "vision_request": {
                "document_id": action.document_id,
                "page_number": action.page_number,
                "reason": action.reasoning or None,
            },
            "note": "Il provider chat corrente accetta solo testo; la richiesta e' esposta alla UI e alla futura esecuzione multimodale.",
        }
    if action.action == "search_calendar_events":
        return _agent_search_calendar_events(
            db,
            query=action.query,
            supplier=action.supplier,
            date_from=action.date_from,
            date_to=action.date_to,
            amount_min=action.amount_min,
            amount_max=action.amount_max,
            status=action.status,
            review_status=action.review_status,
            limit=limit,
        )
    if action.action == "query_accounting_tables":
        if not action.query:
            raise ValueError("query is required")
        return ask_accounting(
            AccountingAskRequest(
                question=action.query,
                document_id=action.document_id,
                subject=action.subject,
                period_a_from=action.period_a_from,
                period_a_to=action.period_a_to,
                period_b_from=action.period_b_from,
                period_b_to=action.period_b_to,
            ),
            db,
        )
    raise ValueError(f"Unsupported action: {action.action}")


def _knowledge_agent_tool_signature(action: _KnowledgeAgentAction) -> str:
    payload = action.model_dump(
        mode="json",
        exclude={"reasoning", "answer", "confidence", "citations"},
        exclude_none=True,
    )
    for key, value in list(payload.items()):
        if isinstance(value, str):
            payload[key] = " ".join(value.strip().lower().split())
    if action.action in SEARCH_ACTIONS and action.query:
        payload["query"] = canonical_query(action.query)
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)


def _agent_budget_from_trace(trace: list[KnowledgeAgentTraceStep]) -> AgentToolBudget:
    budget = AgentToolBudget()
    for step in trace:
        if not step.error and step.action in {
            "retrieve_evidence",
            "get_page_text",
            "analyze_page_image",
            "search_calendar_events",
            "query_accounting_tables",
        }:
            budget.consume(step.action)
    return budget


def _agent_search_calendar_events(
    db: Session,
    *,
    query: str | None,
    supplier: str | None,
    date_from: date | None,
    date_to: date | None,
    amount_min: float | None,
    amount_max: float | None,
    status: str | None,
    review_status: str | None,
    limit: int,
) -> dict[str, Any]:
    statement = (
        select(CalendarEvent)
        .options(
            selectinload(CalendarEvent.source_document_unit).selectinload(DocumentUnit.document_type),
            selectinload(CalendarEvent.source_document_unit)
            .selectinload(DocumentUnit.scan_unit)
            .selectinload(ScanUnit.document),
        )
        .order_by(CalendarEvent.due_date.asc(), CalendarEvent.created_at.desc())
    )
    if date_from is not None:
        statement = statement.where(CalendarEvent.due_date >= date_from)
    if date_to is not None:
        statement = statement.where(CalendarEvent.due_date <= date_to)
    if amount_min is not None:
        statement = statement.where(CalendarEvent.amount >= amount_min)
    if amount_max is not None:
        statement = statement.where(CalendarEvent.amount <= amount_max)
    if status and status != "all":
        statement = statement.where(CalendarEvent.status == status)
    if review_status and review_status != "all":
        statement = statement.where(CalendarEvent.review_status == review_status)

    normalized_query = _normalize_search_value(query)
    normalized_supplier = _normalize_search_value(supplier)
    items: list[dict[str, Any]] = []
    scanned = 0
    for event in db.execute(statement.limit(max(limit * 5, 50))).scalars().all():
        scanned += 1
        item = _agent_calendar_event_summary(event)
        text_haystack = _normalize_search_value(
            " ".join(
                str(item.get(field) or "")
                for field in (
                    "title",
                    "subject",
                    "supplier",
                    "original_filename",
                    "document_unit_title",
                    "document_type_code",
                )
            )
        )
        supplier_haystack = _normalize_search_value(
            " ".join(str(value or "") for value in (item.get("supplier"), item.get("title"), item.get("subject")))
        )
        if normalized_query and normalized_query not in text_haystack:
            continue
        if normalized_supplier and normalized_supplier not in supplier_haystack:
            continue
        items.append(item)
        if len(items) >= limit:
            break
    return {
        "total_returned": len(items),
        "scanned_after_structured_filters": scanned,
        "filters": {
            "query": query,
            "supplier": supplier,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "amount_min": amount_min,
            "amount_max": amount_max,
            "status": status,
            "review_status": review_status,
        },
        "events": items,
    }


def _agent_calendar_event_summary(event: CalendarEvent) -> dict[str, Any]:
    document_unit = event.source_document_unit
    document = document_unit.scan_unit.document if document_unit is not None and document_unit.scan_unit else None
    evidence = event.evidence_json or {}
    supplier = evidence.get("issuer") if isinstance(evidence, dict) else None
    return {
        "calendar_event_id": str(event.id),
        "event_type": event.event_type,
        "title": event.title,
        "subject": event.subject,
        "supplier": supplier,
        "amount": float(event.amount) if event.amount is not None else None,
        "currency": event.currency,
        "due_date": event.due_date.isoformat(),
        "status": event.status,
        "review_status": event.review_status,
        "confidence": event.confidence,
        "document_id": str(document.id) if document else None,
        "document_unit_id": str(event.source_document_unit_id),
        "document_unit_title": document_unit.title if document_unit else None,
        "document_type_code": document_unit.document_type.code if document_unit and document_unit.document_type else None,
        "original_filename": document.original_filename if document else None,
        "page_from": document_unit.start_page if document_unit else None,
        "page_to": document_unit.end_page if document_unit else None,
        "source_specialist_result_id": str(event.source_specialist_result_id) if event.source_specialist_result_id else None,
        "issues": evidence.get("issues", []) if isinstance(evidence, dict) else [],
    }


def _agent_search_archive(db: Session, query: str, *, limit: int) -> dict[str, Any]:
    normalized = f"%{query.strip().lower()}%" if query.strip() else "%"
    units = db.execute(
        select(DocumentUnit)
        .join(DocumentUnit.scan_unit)
        .join(ScanUnit.document)
        .outerjoin(DocumentUnit.document_type)
        .options(
            selectinload(DocumentUnit.scan_unit).selectinload(ScanUnit.document),
            selectinload(DocumentUnit.document_type),
            selectinload(DocumentUnit.topic_assignments).selectinload(DocumentUnitTopicAssignment.topic),
            selectinload(DocumentUnit.entities),
        )
        .where(
            or_(
                func.lower(DocumentUnit.title).like(normalized),
                func.lower(DocumentUnit.extracted_summary).like(normalized),
                func.lower(Document.original_filename).like(normalized),
            )
        )
        .order_by(Document.created_at.desc(), DocumentUnit.ordinal.asc())
        .limit(limit)
    ).scalars().all()
    topics = _agent_list_topics(db, query, limit=min(limit, 8))
    return {
        "query": query,
        "document_units": [_agent_document_unit_brief(unit) for unit in units],
        "topics": topics,
    }


def _agent_retrieve_evidence(
    db: Session,
    query: str,
    *,
    document_id: str | None,
    limit: int,
) -> dict[str, Any]:
    def lexical(search_query: str, search_limit: int) -> dict[str, Any]:
        return _agent_lexical_index_search(
            db,
            search_query,
            document_id=document_id,
            limit=search_limit,
        )

    def semantic(search_query: str, search_limit: int) -> dict[str, Any]:
        return _agent_semantic_search(
            db,
            search_query,
            limit=search_limit,
            document_id=document_id,
        )

    result = RetrievalService(
        lexical_search=lexical,
        semantic_search=semantic,
        max_per_document=limit if document_id else 2,
    ).retrieve(query, limit=limit)
    result["scope"] = "document" if document_id else "archive"
    result["document_id"] = document_id
    return result


def _agent_list_topics(db: Session, query: str | None, *, limit: int) -> list[dict[str, Any]]:
    stmt = select(Topic).where(Topic.is_active.is_(True)).order_by(Topic.updated_at.desc().nullslast(), Topic.created_at.desc())
    if query and query.strip():
        pattern = f"%{query.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Topic.title).like(pattern),
                func.lower(Topic.slug).like(pattern),
                func.lower(Topic.description).like(pattern),
            )
        )
    topics = db.execute(stmt.limit(limit)).scalars().all()
    return [
        {
            "topic_id": str(topic.id),
            "title": topic.title,
            "slug": topic.slug,
            "topic_class": topic.topic_class,
            "topic_kind": topic.topic_kind,
            "description": topic.description,
        }
        for topic in topics
    ]


def _agent_document(db: Session, document_id: str) -> dict[str, Any]:
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError as exc:
        raise ValueError("Invalid document_id") from exc
    document = db.get(Document, doc_uuid)
    if document is None:
        raise ValueError("Document not found")
    units = db.execute(
        select(DocumentUnit)
        .join(DocumentUnit.scan_unit)
        .where(ScanUnit.source_document_id == doc_uuid)
        .options(
            selectinload(DocumentUnit.scan_unit).selectinload(ScanUnit.document),
            selectinload(DocumentUnit.document_type),
            selectinload(DocumentUnit.topic_assignments).selectinload(DocumentUnitTopicAssignment.topic),
            selectinload(DocumentUnit.specialist_results),
        )
        .order_by(DocumentUnit.start_page.asc(), DocumentUnit.ordinal.asc())
    ).scalars().all()
    return {
        "document_id": str(document.id),
        "original_filename": document.original_filename,
        "created_at": document.created_at.isoformat() if document.created_at else None,
        "document_units": [_agent_document_unit_brief(unit) for unit in units],
    }


def _agent_document_unit(db: Session, document_unit_id: str) -> dict[str, Any]:
    try:
        unit_uuid = uuid.UUID(document_unit_id)
    except ValueError as exc:
        raise ValueError("Invalid document_unit_id") from exc
    unit = db.execute(
        select(DocumentUnit)
        .where(DocumentUnit.id == unit_uuid)
        .options(
            selectinload(DocumentUnit.scan_unit).selectinload(ScanUnit.document),
            selectinload(DocumentUnit.document_type),
            selectinload(DocumentUnit.topic_assignments).selectinload(DocumentUnitTopicAssignment.topic),
            selectinload(DocumentUnit.entities),
            selectinload(DocumentUnit.specialist_results),
        )
    ).scalar_one_or_none()
    if unit is None:
        raise ValueError("Document unit not found")
    return _agent_document_unit_detail(unit)


def _agent_page_text(db: Session, document_id: str, page_number: int) -> dict[str, Any]:
    if page_number < 1:
        raise ValueError("page_number must be >= 1")
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError as exc:
        raise ValueError("Invalid document_id") from exc
    ocr = db.execute(
        select(OCRResult)
        .where(OCRResult.document_id == doc_uuid)
        .order_by(OCRResult.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if ocr is None:
        raise ValueError("OCR result not found")
    return {
        "document_id": document_id,
        "page_number": page_number,
        "page_count": ocr.page_count,
        "text": _extract_ocr_page_text(ocr, page_number)[:5000],
    }


def _agent_analyze_page_image(
    db: Session,
    document_id: str,
    page_number: int,
    reason: str | None,
) -> dict[str, Any]:
    if page_number < 1:
        raise ValueError("page_number must be >= 1")
    provider = _knowledge_agent_provider(db)
    if provider is None:
        raise ValueError("LLM backend is not configured")
    image_base64, render_info = _render_document_page_png_base64(db, document_id, page_number)
    prompt = (
        "Analizza l'immagine della pagina del documento per aiutare una risposta archivistica. "
        "Trascrivi solo il testo visibile rilevante, segnala tabelle/importi/etichette se presenti, "
        "e non inventare contenuti non leggibili.\n"
        f"Documento: {document_id}\nPagina: {page_number}\n"
        f"Motivo della richiesta: {reason or 'n/d'}"
    )
    parsed, _ = provider.chat_with_image_json(
        [
            ChatMessage(
                role="system",
                content=(
                    "Sei un lettore visuale di pagine PDF. Rispondi solo con JSON valido. "
                    "Se la pagina non e' leggibile, dichiaralo esplicitamente."
                ),
            )
        ],
        image_base64=image_base64,
        image_media_type="image/png",
        prompt=prompt,
        schema=_KnowledgeAgentVisionAnalysis,
        temperature=0.1,
        max_retries=2,
    )
    analysis = _KnowledgeAgentVisionAnalysis.model_validate(parsed)
    return {
        "status": "vision_analyzed",
        "document_id": document_id,
        "page_number": page_number,
        "rendered_page_number": render_info["rendered_page_number"],
        "page_mapping": render_info,
        "analysis": analysis.model_dump(mode="json"),
    }


def _render_document_page_png_base64(db: Session, document_id: str, page_number: int) -> tuple[str, dict[str, Any]]:
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError as exc:
        raise ValueError("Invalid document_id") from exc
    scan_unit = db.execute(
        select(ScanUnit)
        .where(ScanUnit.source_document_id == doc_uuid)
        .order_by(ScanUnit.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    preflight = _load_preflight(scan_unit, db) if scan_unit is not None else None
    rendered_page_number = page_number
    rotation_degrees = 0
    if scan_unit is not None and preflight:
        if preflight.get("page_order_reversed"):
            rendered_page_number = scan_unit.page_count - page_number + 1
        rotation_applied = preflight.get("rotation_applied")
        if isinstance(rotation_applied, int):
            rotation_degrees = rotation_applied % 360
    version = db.execute(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == doc_uuid)
        .order_by(DocumentVersion.version_number.desc())
        .limit(1)
    ).scalar_one_or_none()
    if version is None:
        raise ValueError("Document version not found")
    storage = get_storage_backend(get_settings())
    pdf_bytes = storage.read_bytes(version.storage_bucket, version.storage_object_key)
    with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
        if rendered_page_number < 1 or rendered_page_number > pdf.page_count:
            raise ValueError("page_number exceeds document page count")
        page = pdf.load_page(rendered_page_number - 1)
        pixmap = page.get_pixmap(
            matrix=fitz.Matrix(1.6, 1.6).prerotate(rotation_degrees),
            alpha=False,
        )
        png_bytes = pixmap.tobytes("png")
    return base64.b64encode(png_bytes).decode("ascii"), {
        "requested_page_number": page_number,
        "rendered_page_number": rendered_page_number,
        "page_order_reversed": bool(preflight.get("page_order_reversed")) if preflight else False,
        "rotation_applied": rotation_degrees,
        "coordinate_space": "ocr_logical_page",
    }


def _agent_search_document_text(db: Session, document_id: str | None, query: str, *, limit: int) -> dict[str, Any]:
    if not query.strip():
        return {"document_id": document_id, "query": query, "hits": [], "warning": "query is empty"}

    terms = [term for term in re.split(r"\W+", query.lower()) if len(term) >= 3]
    if not terms:
        return {"document_id": document_id, "query": query, "hits": [], "warning": "query has no searchable terms"}

    ocr_rows: list[OCRResult]
    if document_id:
        try:
            doc_uuid = uuid.UUID(document_id)
        except ValueError as exc:
            raise ValueError("Invalid document_id") from exc
        ocr = db.execute(
            select(OCRResult)
            .where(OCRResult.document_id == doc_uuid)
            .order_by(OCRResult.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if ocr is None:
            raise ValueError("OCR result not found")
        ocr_rows = [ocr]
    else:
        latest_ocr_ids = (
            select(func.max(OCRResult.created_at).label("created_at"), OCRResult.document_id.label("document_id"))
            .group_by(OCRResult.document_id)
            .subquery()
        )
        ocr_rows = db.execute(
            select(OCRResult)
            .join(
                latest_ocr_ids,
                (OCRResult.document_id == latest_ocr_ids.c.document_id)
                & (OCRResult.created_at == latest_ocr_ids.c.created_at),
            )
            .options(selectinload(OCRResult.document))
            .order_by(OCRResult.created_at.desc())
        ).scalars().all()

    hits: list[dict[str, Any]] = []
    for ocr in ocr_rows:
        document = ocr.document
        for page_number in range(1, max(ocr.page_count, 1) + 1):
            page_text = _extract_ocr_page_text(ocr, page_number)
            if not page_text.strip():
                continue
            hit = _text_page_hit(page_text, terms)
            if hit is None:
                continue
            start, end, score = hit
            snippet = page_text[max(0, start - 180) : min(len(page_text), end + 180)]
            hits.append(
                {
                    "document_id": str(ocr.document_id),
                    "original_filename": document.original_filename if document else None,
                    "page_number": page_number,
                    "score": score,
                    "snippet": " ".join(snippet.split()),
                }
            )
    hits.sort(key=lambda item: (-item["score"], item["page_number"]))
    return {"document_id": document_id, "query": query, "scope": "document" if document_id else "archive", "hits": hits[:limit]}


def _text_page_hit(text: str, terms: list[str]) -> tuple[int, int, int] | None:
    if not terms:
        return None
    lowered = text.lower()
    positions: list[tuple[int, int]] = []
    matched_terms = 0
    for term in terms:
        position = lowered.find(term)
        if position < 0:
            continue
        matched_terms += 1
        positions.append((position, position + len(term)))
    if not positions:
        return None
    start = min(position[0] for position in positions)
    end = max(position[1] for position in positions)
    return start, end, matched_terms


def _agent_document_unit_brief(unit: DocumentUnit) -> dict[str, Any]:
    document = unit.scan_unit.document if unit.scan_unit else None
    return {
        "document_unit_id": str(unit.id),
        "document_id": str(document.id) if document else None,
        "original_filename": document.original_filename if document else None,
        "title": unit.title,
        "document_type_code": unit.document_type.code if unit.document_type else None,
        "pages": [unit.start_page, unit.end_page],
        "summary": (unit.extracted_summary or "")[:700] or None,
        "review_status": unit.review_status,
        "topics": [
            {
                "topic_id": str(assignment.topic.id),
                "title": assignment.topic.title,
                "role": assignment.assignment_role,
                "confidence": assignment.confidence,
            }
            for assignment in unit.topic_assignments
            if assignment.topic and assignment.topic.is_active
        ],
    }


def _agent_document_unit_detail(unit: DocumentUnit) -> dict[str, Any]:
    detail = _agent_document_unit_brief(unit)
    detail["entities"] = [
        {
            "type": entity.entity_type,
            "value": entity.entity_value,
            "normalized": entity.normalized_value,
            "confidence": entity.confidence,
            "pages": [entity.page_from, entity.page_to],
        }
        for entity in unit.entities
    ][:40]
    detail["specialist_results"] = [
        _agent_specialist_result_summary(result)
        for result in sorted(unit.specialist_results, key=lambda item: item.created_at, reverse=True)
    ][:8]
    return detail


def _agent_specialist_result_summary(result: SpecialistResult) -> dict[str, Any]:
    payload = result.result_json or {}
    summary_view = payload.get("summary_view") if isinstance(payload, dict) else None
    raw_tables = payload.get("raw_tables") if isinstance(payload, dict) else None
    return {
        "result_id": str(result.id),
        "specialist_type": result.specialist_type,
        "review_status": result.review_status,
        "confidence": result.confidence,
        "summary": payload.get("summary") if isinstance(payload, dict) else None,
        "statement_type": payload.get("statement_type") if isinstance(payload, dict) else None,
        "period": {
            "from": payload.get("accounting_period_from") if isinstance(payload, dict) else None,
            "to": payload.get("accounting_period_to") if isinstance(payload, dict) else None,
        },
        "summary_view": {
            "columns": (summary_view or {}).get("columns", [])[:30] if isinstance(summary_view, dict) else [],
            "row_count": len((summary_view or {}).get("rows", [])) if isinstance(summary_view, dict) else 0,
            "sample_rows": (summary_view or {}).get("rows", [])[:5] if isinstance(summary_view, dict) else [],
            "explanation": (summary_view or {}).get("explanation") if isinstance(summary_view, dict) else None,
        },
        "raw_table_count": len(raw_tables) if isinstance(raw_tables, list) else None,
    }


def _extract_ocr_page_text(ocr: OCRResult, page_number: int) -> str:
    return get_page_artifact_text(
        structured_json=ocr.structured_json,
        markdown_text=ocr.markdown_text,
        full_text=ocr.full_text,
        page_count=ocr.page_count,
        page_number=page_number,
        engine_name=ocr.engine_name,
        engine_version=ocr.engine_version,
        confidence_summary=ocr.confidence_summary,
    )


def _plan_accounting_question(
    db: Session,
    payload: AccountingAskRequest,
    tables: list[dict[str, Any]],
) -> _AccountingAskPlan:
    provider = _accounting_llm_provider(db)
    if provider is None:
        return _fallback_accounting_plan(payload.question)
    table_summary = [
        {
            "document_unit_title": table.get("document_unit_title"),
            "period_from": table.get("period_from"),
            "period_to": table.get("period_to"),
            "columns": table.get("columns", [])[:30],
            "sample_subjects": [
                f"{row.get('unit_code', '')} {row.get('subject_label', '')}".strip()
                for row in table.get("rows", [])[:8]
            ],
        }
        for table in tables[:12]
    ]
    try:
        parsed, _ = provider.chat_with_json(
            [
                ChatMessage(
                    role="system",
                    content=(
                        "Sei un planner per interrogazioni contabili condominiali. "
                        "Estrai solo soggetto e periodi dalla domanda. Non calcolare importi."
                    ),
                ),
                ChatMessage(
                    role="user",
                    content=(
                        "Dato questo insieme di tabelle contabili, produci un piano JSON. "
                        "Se la domanda chiede 'nel 2022 rispetto al 2023' e i periodi disponibili "
                        "sono esercizi 2022-07/2023-06 e 2023-07/2024-06, usa quegli intervalli. "
                        f"Domanda: {payload.question}\n"
                        f"Tabelle disponibili: {table_summary}"
                    ),
                ),
            ],
            _AccountingAskPlan,
        )
        return _AccountingAskPlan.model_validate(parsed)
    except Exception:
        return _fallback_accounting_plan(payload.question)


def _fallback_accounting_plan(question: str) -> _AccountingAskPlan:
    years = [int(item) for item in re.findall(r"\b(20\d{2})\b", question)]
    kwargs: dict[str, Any] = {"subject": _fallback_subject_from_question(question)}
    if len(years) >= 2:
        kwargs.update(
            {
                "period_a_from": date(years[0], 1, 1),
                "period_a_to": date(years[0], 12, 31),
                "period_b_from": date(years[1], 1, 1),
                "period_b_to": date(years[1], 12, 31),
            }
        )
    return _AccountingAskPlan(**kwargs)


def _fallback_subject_from_question(question: str) -> str | None:
    stop = {
        "ha", "speso", "piu", "meno", "nel", "nella", "rispetto", "quali",
        "voci", "sono", "cambiate", "confronta", "bilancio", "condominiale",
    }
    candidates = [
        token.strip(" ?.,;:").lower()
        for token in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ']{3,}", question)
    ]
    for token in candidates:
        normalized = _normalize_search_text(token)
        if normalized and normalized not in stop:
            return token
    return None


def _accounting_summary_dataframes(
    db: Session,
    *,
    context_id: str | None,
    document_id: str | None,
) -> list[dict[str, Any]]:
    stmt = (
        select(DocumentUnit, SpecialistResult, Document)
        .join(SpecialistResult, SpecialistResult.document_unit_id == DocumentUnit.id)
        .join(ScanUnit, ScanUnit.id == DocumentUnit.scan_unit_id)
        .join(Document, Document.id == ScanUnit.source_document_id)
        .where(SpecialistResult.specialist_type == "accounting_statement")
        .order_by(Document.created_at.asc(), DocumentUnit.ordinal.asc(), SpecialistResult.created_at.desc())
    )
    if document_id:
        try:
            parsed_document_id = uuid.UUID(document_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid document_id") from exc
        stmt = stmt.where(Document.id == parsed_document_id)
    if context_id:
        try:
            parsed_context_id = uuid.UUID(context_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid context_id") from exc
        stmt = stmt.join(
            KnowledgeContextMembership,
            KnowledgeContextMembership.document_unit_id == DocumentUnit.id,
        ).where(KnowledgeContextMembership.context_id == parsed_context_id)

    seen_units: set[str] = set()
    tables: list[dict[str, Any]] = []
    for doc_unit, result, document in db.execute(stmt).all():
        unit_id = str(doc_unit.id)
        if unit_id in seen_units:
            continue
        seen_units.add(unit_id)
        if not isinstance(result.result_json, dict):
            continue
        summary_view = result.result_json.get("summary_view")
        if not isinstance(summary_view, dict):
            continue
        rows = summary_view.get("rows")
        columns = summary_view.get("columns")
        if not isinstance(rows, list) or not rows or not isinstance(columns, list):
            continue
        tables.append(
            {
                "document_id": str(document.id),
                "document_unit_id": unit_id,
                "document_unit_title": doc_unit.title or f"Pagine {doc_unit.start_page}-{doc_unit.end_page}",
                "original_filename": document.original_filename,
                "start_page": doc_unit.start_page,
                "end_page": doc_unit.end_page,
                "period_from": result.result_json.get("accounting_period_from"),
                "period_to": result.result_json.get("accounting_period_to"),
                "columns": columns,
                "rows": rows,
                "source_columns": summary_view.get("source_columns", []),
            }
        )
    return tables


def _accounting_table_summaries(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "document_id": table["document_id"],
            "document_unit_id": table["document_unit_id"],
            "title": table["document_unit_title"],
            "filename": table["original_filename"],
            "period_from": table.get("period_from"),
            "period_to": table.get("period_to"),
            "columns": table.get("columns", []),
            "row_count": len(table.get("rows", [])),
        }
        for table in tables
    ]


def _matching_accounting_rows(tables: list[dict[str, Any]], subject: str) -> list[dict[str, Any]]:
    needle = _normalize_search_text(subject)
    matches: list[dict[str, Any]] = []
    for table in tables:
        for row in table.get("rows", []):
            haystack = _normalize_search_text(
                f"{row.get('unit_code', '')} {row.get('subject_label', '')} {row.get('account_key', '')}"
            )
            if needle and needle in haystack:
                matches.append({**row, **{key: table[key] for key in (
                    "document_id", "document_unit_id", "document_unit_title",
                    "original_filename", "start_page", "end_page",
                    "period_from", "period_to",
                )}})
    return matches


def _parse_date_value(value: str | date | None) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _rows_for_period(
    rows: list[dict[str, Any]],
    period_from: date | None,
    period_to: date | None,
) -> list[dict[str, Any]]:
    if period_from is None or period_to is None:
        return []
    selected = []
    for row in rows:
        row_from = _parse_date_value(row.get("period_from"))
        row_to = _parse_date_value(row.get("period_to"))
        if row_from is None or row_to is None:
            continue
        if row_from <= period_to and row_to >= period_from:
            selected.append(row)
    return selected


def _infer_two_periods(tables: list[dict[str, Any]]) -> dict[str, date]:
    periods: list[tuple[date, date]] = []
    for table in tables:
        period_from = _parse_date_value(table.get("period_from"))
        period_to = _parse_date_value(table.get("period_to"))
        if period_from and period_to and (period_from, period_to) not in periods:
            periods.append((period_from, period_to))
    periods.sort()
    if len(periods) < 2:
        return {}
    return {
        "period_a_from": periods[-2][0],
        "period_a_to": periods[-2][1],
        "period_b_from": periods[-1][0],
        "period_b_to": periods[-1][1],
    }


def _infer_latest_period(tables: list[dict[str, Any]]) -> dict[str, date]:
    periods: list[tuple[date, date]] = []
    for table in tables:
        period_from = _parse_date_value(table.get("period_from"))
        period_to = _parse_date_value(table.get("period_to"))
        if period_from and period_to and (period_from, period_to) not in periods:
            periods.append((period_from, period_to))
    periods.sort()
    if not periods:
        return {}
    return {"period_from": periods[-1][0], "period_to": periods[-1][1]}


def _summarize_accounting_dataframe_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    categories = sorted({
        column
        for row in rows
        for column in (row.get("cells") or {}).keys()
    })
    computed_rows: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for category in categories:
        amount, category_evidence = _sum_category(rows, category)
        if amount == 0:
            continue
        computed_rows.append({"category": category, "amount": float(amount)})
        evidence.extend(category_evidence)
    total = _summary_total_amount(computed_rows)
    return {
        "total": float(total),
        "rows": computed_rows,
        "evidence": evidence[:80],
        "warnings": [],
    }


def _compare_accounting_dataframe_rows(
    period_a_rows: list[dict[str, Any]],
    period_b_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    categories = sorted({
        column
        for row in [*period_a_rows, *period_b_rows]
        for column in (row.get("cells") or {}).keys()
    })
    rows: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []

    for category in categories:
        amount_a, evidence_a = _sum_category(period_a_rows, category)
        amount_b, evidence_b = _sum_category(period_b_rows, category)
        if amount_a == 0 and amount_b == 0:
            continue
        delta = amount_b - amount_a
        rows.append(
            {
                "category": category,
                "amount_a": float(amount_a),
                "amount_b": float(amount_b),
                "delta": float(delta),
                "percentage_change": (
                    round(float((delta / amount_a) * Decimal("100")), 2)
                    if amount_a != 0 else None
                ),
            }
        )
        evidence.extend(evidence_a)
        evidence.extend(evidence_b)

    total_a = _comparison_total_amount(rows, "amount_a")
    total_b = _comparison_total_amount(rows, "amount_b")
    delta_total = total_b - total_a
    return {
        "total_a": float(total_a),
        "total_b": float(total_b),
        "delta": float(delta_total),
        "direction": "period_b_more" if delta_total > 0 else "period_b_less" if delta_total < 0 else "equal",
        "rows": rows,
        "evidence": evidence[:80],
        "warnings": [],
    }


def _is_total_category(category: str) -> bool:
    normalized = _normalize_search_text(category)
    return normalized == "totale" or normalized.startswith("totale ")


def _summary_total_amount(rows: list[dict[str, Any]]) -> Decimal:
    total_rows = [
        Decimal(str(row.get("amount") or 0))
        for row in rows
        if _is_total_category(str(row.get("category") or ""))
    ]
    if total_rows:
        return sum(total_rows, Decimal("0"))
    return sum(
        (
            Decimal(str(row.get("amount") or 0))
            for row in rows
            if not _is_total_category(str(row.get("category") or ""))
        ),
        Decimal("0"),
    )


def _comparison_total_amount(rows: list[dict[str, Any]], amount_key: str) -> Decimal:
    total_rows = [
        Decimal(str(row.get(amount_key) or 0))
        for row in rows
        if _is_total_category(str(row.get("category") or ""))
    ]
    if total_rows:
        return sum(total_rows, Decimal("0"))
    return sum(
        (
            Decimal(str(row.get(amount_key) or 0))
            for row in rows
            if not _is_total_category(str(row.get("category") or ""))
        ),
        Decimal("0"),
    )


def _sum_category(rows: list[dict[str, Any]], category: str) -> tuple[Decimal, list[dict[str, Any]]]:
    total = Decimal("0")
    evidence: list[dict[str, Any]] = []
    for row in rows:
        cell = (row.get("cells") or {}).get(category)
        if not isinstance(cell, dict):
            continue
        amount = Decimal(str(cell.get("amount") or 0))
        total += amount
        for fact in cell.get("facts", []) or [{"evidence": cell.get("evidence")}]:
            if not isinstance(fact, dict):
                continue
            ev = fact.get("evidence") if isinstance(fact.get("evidence"), dict) else {}
            evidence.append(
                {
                    "category": category,
                    "amount": float(amount),
                    "document_id": row.get("document_id"),
                    "document_unit_id": row.get("document_unit_id"),
                    "filename": row.get("original_filename"),
                    "period_from": row.get("period_from"),
                    "period_to": row.get("period_to"),
                    "unit_code": row.get("unit_code"),
                    "subject_label": row.get("subject_label"),
                    "table_id": ev.get("table_id"),
                    "row_id": ev.get("row_id"),
                    "column": ev.get("column"),
                    "page_number": ev.get("page_number"),
                    "raw_value": ev.get("raw_value"),
                }
            )
    return total, evidence


def _accounting_answer_text(subject: str, comparison: dict[str, Any]) -> str:
    direction = comparison["direction"]
    total_a = format(float(comparison["total_a"]), ".2f")
    total_b = format(float(comparison["total_b"]), ".2f")
    delta = format(float(comparison["delta"]), ".2f")
    if direction == "period_b_more":
        prefix = f"{subject} risulta avere un totale maggiore nel periodo B"
    elif direction == "period_b_less":
        prefix = f"{subject} risulta avere un totale minore nel periodo B"
    else:
        prefix = f"{subject} risulta avere lo stesso totale nei due periodi"
    changed = sorted(
        comparison["rows"],
        key=lambda row: abs(float(row["delta"])),
        reverse=True,
    )[:5]
    changed_text = "; ".join(
        f"{row['category']}: {row['amount_a']:.2f} -> {row['amount_b']:.2f} (delta {row['delta']:.2f})"
        for row in changed
    )
    return f"{prefix}: A={total_a}, B={total_b}, delta={delta}. Voci principali: {changed_text or 'nessuna variazione'}."


def _accounting_single_period_answer_text(subject: str, summary: dict[str, Any]) -> str:
    total = format(float(summary["total"]), ".2f")
    main_rows = sorted(
        summary["rows"],
        key=lambda row: abs(float(row["amount"])),
        reverse=True,
    )[:8]
    detail = "; ".join(
        f"{row['category']}: {row['amount']:.2f}"
        for row in main_rows
    )
    return f"{subject} risulta avere un totale di {total}. Voci principali: {detail or 'nessuna voce valorizzata'}."


@router.patch("/specialists/accounting-facts/{fact_id}/correction", response_model=AccountingFactCorrectionResponse)
def correct_accounting_fact(
    fact_id: uuid.UUID,
    payload: AccountingFactCorrectionRequest,
    db: Session = Depends(get_db_session),
):
    try:
        corrected = apply_manual_accounting_correction(
            db,
            fact_id,
            corrected_amount=payload.corrected_amount,
            corrected_category_label=payload.corrected_category_label,
            corrected_is_total=payload.corrected_is_total,
            excluded=payload.excluded,
            note=payload.note,
            acted_by=payload.acted_by,
        )
    except ValueError as exc:
        message = str(exc)
        response_status = 404 if message == "Accounting fact not found." else 400
        raise HTTPException(status_code=response_status, detail=message) from exc
    db.commit()
    return corrected


def _knowledge_node_options():
    return (
        selectinload(KnowledgeNode.aliases),
        selectinload(KnowledgeNode.mentions)
        .selectinload(DocumentUnitMention.document_unit)
        .selectinload(DocumentUnit.scan_unit)
        .selectinload(ScanUnit.document),
        selectinload(KnowledgeNode.mentions)
        .selectinload(DocumentUnitMention.document_unit)
        .selectinload(DocumentUnit.document_type),
        selectinload(KnowledgeNode.object_assertions).selectinload(KnowledgeAssertion.predicate),
        selectinload(KnowledgeNode.object_assertions).selectinload(KnowledgeAssertion.object_node),
        selectinload(KnowledgeNode.object_assertions)
        .selectinload(KnowledgeAssertion.document_unit)
        .selectinload(DocumentUnit.scan_unit)
        .selectinload(ScanUnit.document),
        selectinload(KnowledgeNode.object_assertions)
        .selectinload(KnowledgeAssertion.document_unit)
        .selectinload(DocumentUnit.document_type),
        selectinload(KnowledgeNode.subject_assertions),
    )


@router.get("/graph/stats", response_model=KnowledgeGraphStatsResponse)
def get_knowledge_graph_stats(db: Session = Depends(get_db_session)):
    stats = graph_stats(db)
    return KnowledgeGraphStatsResponse(**stats.__dict__)


@router.post("/graph/rebuild", response_model=KnowledgeGraphStatsResponse)
def rebuild_graph_projection(db: Session = Depends(get_db_session)):
    stats = rebuild_knowledge_graph(db)
    rebuild_knowledge_contexts(db)
    db.commit()
    return KnowledgeGraphStatsResponse(**stats.__dict__)


@router.get("/nodes", response_model=list[KnowledgeNodeSummaryResponse])
def list_knowledge_nodes(
    q: str | None = None,
    node_kind: str | None = None,
    limit: int = Query(default=30, ge=1, le=200),
    db: Session = Depends(get_db_session),
):
    query = (
        select(KnowledgeNode)
        .outerjoin(KnowledgeNodeAlias, KnowledgeNodeAlias.node_id == KnowledgeNode.id)
        .options(*_knowledge_node_options())
        .distinct()
        .order_by(KnowledgeNode.label.asc())
    )
    if node_kind:
        query = query.where(KnowledgeNode.node_kind == node_kind)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        query = query.where(
            or_(
                KnowledgeNode.label.ilike(pattern),
                KnowledgeNode.canonical_key.ilike(pattern),
                KnowledgeNodeAlias.alias.ilike(pattern),
            )
        )
    nodes = db.execute(query.limit(limit)).scalars().unique().all()
    return [_serialize_knowledge_node_summary(node) for node in nodes]


@router.get("/nodes/{node_id}", response_model=KnowledgeNodeDetailResponse)
def get_knowledge_node(node_id: uuid.UUID, db: Session = Depends(get_db_session)):
    node = db.execute(
        select(KnowledgeNode)
        .options(*_knowledge_node_options())
        .where(KnowledgeNode.id == node_id)
    ).scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=404, detail="Knowledge node not found")

    documents = []
    for document_unit in _node_document_units(node):
        if document_unit.scan_unit is None or document_unit.scan_unit.document is None:
            continue
        document = document_unit.scan_unit.document
        documents.append(
            KnowledgeEntityDocumentHitResponse(
                document_id=str(document.id),
                document_unit_id=str(document_unit.id),
                original_filename=document.original_filename,
                external_id=document.external_id,
                title=document_unit.title,
                summary=document_unit.extracted_summary,
                review_status=document_unit.review_status,
                start_page=document_unit.start_page,
                end_page=document_unit.end_page,
                topic_titles=[],
            )
        )
    linked_unit_ids = [unit.id for unit in _node_document_units(node)]
    assertions = db.execute(
        select(KnowledgeAssertion)
        .options(
            selectinload(KnowledgeAssertion.predicate),
            selectinload(KnowledgeAssertion.object_node),
        )
        .where(KnowledgeAssertion.document_unit_id.in_(linked_unit_ids))
        .order_by(KnowledgeAssertion.created_at.desc())
    ).scalars().unique().all()
    return KnowledgeNodeDetailResponse(
        node=_serialize_knowledge_node_summary(node),
        aliases=sorted({alias.alias for alias in node.aliases}),
        documents=documents,
        assertions=[_serialize_knowledge_assertion(assertion) for assertion in assertions],
    )


@router.get("/assertions", response_model=list[KnowledgeAssertionResponse])
def list_knowledge_assertions(
    q: str | None = None,
    predicate: str | None = None,
    node_id: uuid.UUID | None = None,
    limit: int = Query(default=60, ge=1, le=300),
    db: Session = Depends(get_db_session),
):
    query = (
        select(KnowledgeAssertion)
        .outerjoin(KnowledgeNode, KnowledgeNode.id == KnowledgeAssertion.object_node_id)
        .options(
            selectinload(KnowledgeAssertion.predicate),
            selectinload(KnowledgeAssertion.object_node),
        )
        .order_by(KnowledgeAssertion.created_at.desc())
    )
    if predicate:
        query = query.where(KnowledgeAssertion.predicate_code == predicate)
    if node_id:
        linked_unit_ids = select(DocumentUnitMention.document_unit_id).where(
            DocumentUnitMention.node_id == node_id
        ).union(
            select(KnowledgeAssertion.document_unit_id).where(
                or_(
                    KnowledgeAssertion.subject_node_id == node_id,
                    KnowledgeAssertion.object_node_id == node_id,
                )
            )
        )
        query = query.where(KnowledgeAssertion.document_unit_id.in_(linked_unit_ids))
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        query = query.where(
            or_(
                KnowledgeAssertion.value_text.ilike(pattern),
                KnowledgeAssertion.predicate_code.ilike(pattern),
                KnowledgeNode.label.ilike(pattern),
            )
        )
    assertions = db.execute(query.limit(limit)).scalars().unique().all()
    return [_serialize_knowledge_assertion(assertion) for assertion in assertions]


@router.post("/topics", response_model=TopicResponse, status_code=status.HTTP_201_CREATED)
def create_topic(data: TopicCreate, db: Session = Depends(get_db_session)):
    """Create a new topic."""
    topic = _get_or_create_topic_from_payload(data, db)
    db.commit()
    
    return TopicResponse(
        id=str(topic.id),
        slug=topic.slug,
        title=topic.title,
        topic_class=topic.topic_class,
        topic_kind=topic.topic_kind,
        description=topic.description,
        canonical=topic.canonical,
        is_active=topic.is_active,
        created_at=topic.created_at,
        updated_at=topic.updated_at,
    )


@router.post("/consolidate/run-sync", response_model=ConsolidationResponse)
def run_consolidation_sync():
    """Merge semantically near-duplicate topics across the current knowledge base."""
    db = SessionLocal()
    try:
        service = KnowledgeBaseConsolidationService(db)
        stats = service.consolidate_topics()
        db.commit()
        return ConsolidationResponse(
            topics_before=stats.topics_before,
            topics_after=stats.topics_after,
            topics_merged=stats.topics_merged,
            aliases_created=stats.aliases_created,
            assignments_retargeted=stats.assignments_retargeted,
            proposals_retargeted=stats.proposals_retargeted,
        )
    finally:
        db.close()


# Topic Proposals
@router.get("/topic-proposals", response_model=list[TopicProposalResponse])
def list_topic_proposals(
    include_consolidated: bool = False,
    db: Session = Depends(get_db_session),
):
    """List topic proposals that need review."""
    statuses = ["proposed", "merged_into_existing"] if include_consolidated else ["proposed"]
    result = db.execute(
        select(TopicProposal)
        .options(
            selectinload(TopicProposal.source_document_unit)
            .selectinload(DocumentUnit.scan_unit)
            .selectinload(ScanUnit.document),
            selectinload(TopicProposal.matched_topic),
        )
        .where(TopicProposal.proposal_status.in_(statuses))
        .order_by(TopicProposal.created_at.desc())
    )
    proposals = result.scalars().all()

    return [TopicProposalResponse(**_serialize_topic_proposal(p)) for p in proposals]


@router.post("/topic-proposals/{proposal_id}/approve", response_model=DocumentUnitResponse)
def approve_topic_proposal(
    proposal_id: str,
    resolution: TopicProposalResolution | None = None,
    db: Session = Depends(get_db_session),
):
    """Resolve a topic proposal by creating or merging topics and assignments."""
    result = db.execute(
        select(TopicProposal)
        .options(
            selectinload(TopicProposal.matched_topic),
            selectinload(TopicProposal.source_document_unit).selectinload(DocumentUnit.topic_assignments).selectinload(DocumentUnitTopicAssignment.topic),
            selectinload(TopicProposal.source_document_unit).selectinload(DocumentUnit.document_type),
            selectinload(TopicProposal.source_document_unit).selectinload(DocumentUnit.entities),
            selectinload(TopicProposal.source_document_unit).selectinload(DocumentUnit.scan_unit).selectinload(ScanUnit.document),
        )
        .where(TopicProposal.id == uuid.UUID(proposal_id))
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    if proposal.proposal_status != "proposed":
        raise HTTPException(status_code=409, detail="Only pending proposals can be approved")

    if resolution is None:
        resolution = TopicProposalResolution(
            action="merge_into_existing" if proposal.matched_existing_topic_id else "approve_new_topic",
            assignment_role="subject",
        )

    if resolution.action in {"merge_into_existing", "add_secondary_topic"}:
        target_topic_id = resolution.target_topic_id or (
            str(proposal.matched_existing_topic_id) if proposal.matched_existing_topic_id else None
        )
        if target_topic_id is None:
            raise HTTPException(status_code=400, detail="target_topic_id is required")
        topic = db.execute(select(Topic).where(Topic.id == uuid.UUID(target_topic_id))).scalar_one_or_none()
        if topic is None:
            raise HTTPException(status_code=404, detail="Target topic not found")
        topic.canonical = True
        topic.is_active = True
        topic.updated_at = _utcnow()
    else:
        create_topic_payload = resolution.create_topic or TopicCreate(
            slug=proposal.proposed_slug,
            title=proposal.proposed_title,
            topic_class=proposal.topic_class,
            topic_kind=proposal.proposed_topic_kind,
            description=proposal.description,
            aliases=[],
        )
        topic = _get_or_create_topic_from_payload(create_topic_payload, db)

    if proposal.source_document_unit is not None:
        if resolution.action == "merge_into_existing":
            provisional_assignments = [
                assignment
                for assignment in proposal.source_document_unit.topic_assignments
                if assignment.topic_id == proposal.matched_existing_topic_id
                or (
                    assignment.assignment_role == "primary"
                    and (assignment.topic is None or not assignment.topic.is_active or not assignment.topic.canonical)
                )
            ]
            if provisional_assignments:
                primary_assignment = provisional_assignments[0]
                primary_assignment.topic_id = topic.id
                primary_assignment.assignment_role = resolution.assignment_role
                primary_assignment.confidence = proposal.confidence
                primary_assignment.rationale = proposal.rationale
                for duplicate_assignment in provisional_assignments[1:]:
                    db.delete(duplicate_assignment)
            else:
                _assign_topic_to_document_unit(
                    proposal.source_document_unit,
                    topic,
                    resolution.assignment_role,
                    db,
                    confidence=proposal.confidence,
                    rationale=proposal.rationale,
                )
        else:
            _assign_topic_to_document_unit(
                proposal.source_document_unit,
                topic,
                resolution.assignment_role,
                db,
                confidence=proposal.confidence,
                rationale=proposal.rationale,
            )
        proposal.source_document_unit.review_status = ReviewStatus.HUMAN_REVIEWED.value
        if proposal.source_document_unit.scan_unit is not None:
            _refresh_scan_unit_review_status(proposal.source_document_unit.scan_unit)

    proposal.proposal_status = "approved"
    proposal.matched_existing_topic_id = topic.id
    proposal.reviewed_at = _utcnow()

    db.commit()
    if proposal.source_document_unit is None:
        raise HTTPException(status_code=409, detail="Proposal has no source document unit")
    db.refresh(proposal.source_document_unit)
    return DocumentUnitResponse(**_serialize_document_unit(proposal.source_document_unit))


@router.post("/topic-proposals/{proposal_id}/reject", response_model=TopicProposalResponse)
def reject_topic_proposal(proposal_id: str, db: Session = Depends(get_db_session)):
    """Reject a topic proposal."""
    result = db.execute(
        select(TopicProposal)
        .options(
            selectinload(TopicProposal.matched_topic).selectinload(Topic.assignments),
            selectinload(TopicProposal.source_document_unit).selectinload(DocumentUnit.topic_assignments),
        )
        .where(TopicProposal.id == uuid.UUID(proposal_id))
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    if proposal.proposal_status != "proposed":
        raise HTTPException(status_code=409, detail="Only pending proposals can be rejected")

    if proposal.source_document_unit is not None:
        removable_assignments = [
            assignment
            for assignment in proposal.source_document_unit.topic_assignments
            if assignment.topic_id == proposal.matched_existing_topic_id
        ]
        for assignment in removable_assignments:
            db.delete(assignment)
        proposal.source_document_unit.review_status = ReviewStatus.HUMAN_REVIEWED.value
        if proposal.source_document_unit.scan_unit is not None:
            _refresh_scan_unit_review_status(proposal.source_document_unit.scan_unit)

    provisional_topic = proposal.matched_topic
    provisional_topic_id = provisional_topic.id if provisional_topic is not None else None
    proposal.proposal_status = "rejected"
    proposal.reviewed_at = _utcnow()
    db.flush()

    if provisional_topic is not None and provisional_topic_id is not None:
        has_assignments = db.execute(
            select(DocumentUnitTopicAssignment).where(
                DocumentUnitTopicAssignment.topic_id == provisional_topic_id
            )
        ).first() is not None
        has_pending_proposals = db.execute(
            select(TopicProposal).where(
                TopicProposal.matched_existing_topic_id == provisional_topic_id,
                TopicProposal.proposal_status == "proposed",
            )
        ).first() is not None
        if not provisional_topic.is_active and not provisional_topic.canonical and not has_assignments and not has_pending_proposals:
            db.delete(provisional_topic)

    db.commit()

    return TopicProposalResponse(**_serialize_topic_proposal(proposal))


# Document Types
@router.get("/document-types", response_model=list[DocumentTypeResponse])
def list_document_types(db: Session = Depends(get_db_session)):
    """List all document types."""
    result = db.execute(select(DocumentType).order_by(DocumentType.code))
    types = result.scalars().all()
    
    return [
        DocumentTypeResponse(
            id=str(dt.id),
            code=dt.code,
            name=dt.name,
            description=dt.description,
            parent_code=dt.parent_code,
            is_active=dt.is_active,
            created_at=dt.created_at,
        )
        for dt in types
    ]


# Jobs
@router.get("/jobs/{job_id}", response_model=KnowledgeJobResponse)
def get_job(job_id: str, db: Session = Depends(get_db_session)):
    """Get a knowledge job by ID."""
    result = db.execute(
        select(KnowledgeJob).where(KnowledgeJob.id == uuid.UUID(job_id))
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return KnowledgeJobResponse(
        id=str(job.id),
        scan_unit_id=str(job.scan_unit_id),
        job_type=job.job_type,
        status=job.status,
        attempt_count=job.attempt_count,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.post("/jobs/{job_id}/run-sync")
def run_job_sync(job_id: str, db: Session = Depends(get_db_session)):
    """Run a job synchronously (for testing)."""
    import asyncio
    
    result = db.execute(
        select(KnowledgeJob).where(KnowledgeJob.id == uuid.UUID(job_id))
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job.status = "running"
    db.flush()
    
    try:
        # For now, just mark as completed - full pipeline requires async session
        job.status = "completed"
        db.commit()
        return {"status": "completed", "message": "Sync execution not fully implemented"}
    except Exception as e:
        job.status = "failed"
        job.error_message = str(e)
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/consolidation/suggestions", response_model=GraphConsolidationSuggestionsResponse)
def get_graph_consolidation_suggestions(
    limit_per_axis: int = 12,
    db: Session = Depends(get_db_session),
):
    service = KnowledgeBaseConsolidationService(db)
    suggestions = service.suggest_graph_merges(limit_per_axis=limit_per_axis)

    def serialize_suggestion(item) -> GraphMergeSuggestionResponse:
        return GraphMergeSuggestionResponse(
            axis=item.axis,
            score=item.score,
            rationale=item.rationale,
            shared_entity_keys=item.shared_entity_keys,
            shared_document_count=item.shared_document_count,
            source_topic=GraphSuggestionTopicSummaryResponse(
                id=item.source_topic.id,
                title=item.source_topic.title,
                slug=item.source_topic.slug,
                topic_kind=item.source_topic.topic_kind,
                topic_class=item.source_topic.topic_class,
                assignment_count=item.source_topic.assignment_count,
                dominant_assignment_role=item.source_topic.dominant_assignment_role,
            ),
            target_topic=GraphSuggestionTopicSummaryResponse(
                id=item.target_topic.id,
                title=item.target_topic.title,
                slug=item.target_topic.slug,
                topic_kind=item.target_topic.topic_kind,
                topic_class=item.target_topic.topic_class,
                assignment_count=item.target_topic.assignment_count,
                dominant_assignment_role=item.target_topic.dominant_assignment_role,
            ),
        )

    return GraphConsolidationSuggestionsResponse(
        subject=[serialize_suggestion(item) for item in suggestions.get("subject", [])],
        document_family=[serialize_suggestion(item) for item in suggestions.get("document_family", [])],
        case_or_issue=[serialize_suggestion(item) for item in suggestions.get("case_or_issue", [])],
    )


@router.post("/consolidation/review", response_model=GraphConsolidationReviewResponse)
def review_graph_consolidation_suggestion(
    payload: GraphConsolidationReviewRequest,
    db: Session = Depends(get_db_session),
):
    service = KnowledgeBaseConsolidationService(db)
    try:
        affected_assignments = service.review_graph_suggestion(
            axis=payload.axis,
            source_topic_id=payload.source_topic_id,
            target_topic_id=payload.target_topic_id,
            action=payload.action,
            note=payload.note,
            acted_by=payload.acted_by,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return GraphConsolidationReviewResponse(
        status="ok",
        action=payload.action,
        source_topic_id=payload.source_topic_id,
        target_topic_id=payload.target_topic_id,
        affected_assignments=affected_assignments,
    )


@router.post("/topics/{source_id}/merge", response_model=TopicMergeResponse)
def merge_topic(
    source_id: str,
    payload: TopicMergeRequest,
    db: Session = Depends(get_db_session),
):
    """Merge source topic into target topic.

    Moves assignments, retargets proposals, creates aliases from source
    title/slug, marks source as inactive, and records an audit entry.
    """
    source_topic = db.get(Topic, source_id)
    target_topic = db.get(Topic, payload.target_topic_id)

    if source_topic is None:
        raise HTTPException(status_code=404, detail="Source topic not found")
    if target_topic is None:
        raise HTTPException(status_code=404, detail="Target topic not found")
    if str(source_topic.id) == str(target_topic.id):
        raise HTTPException(status_code=400, detail="Cannot merge a topic into itself")
    if not source_topic.is_active:
        raise HTTPException(status_code=400, detail="Source topic is already inactive")

    from knowledge_classifier.services.consolidation import ConsolidationStats

    service = KnowledgeBaseConsolidationService(db)
    stats = ConsolidationStats()

    # Reuse the existing merge logic
    service._merge_topic_into(target_topic, source_topic, stats)

    # Record audit
    review = GraphConsolidationReview(
        axis="manual_merge",
        source_topic_id=source_topic.id,
        target_topic_id=target_topic.id,
        action="merge_into_target",
        note=payload.note,
        acted_by=payload.acted_by,
    )
    db.add(review)

    # Rebuild derived projections so graph/contexts reflect the merge.
    # Commit after rebuilds so both merge and projections are persisted together.
    try:
        rebuild_knowledge_graph(db)
        rebuild_knowledge_contexts(db)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return TopicMergeResponse(
        status="ok",
        source_topic_id=str(source_topic.id),
        target_topic_id=str(target_topic.id),
        source_topic_title=source_topic.title,
        target_topic_title=target_topic.title,
        affected_assignments=stats.assignments_retargeted,
        aliases_created=stats.aliases_created,
    )


@router.get("/documents/{document_id}/accounting-table")
def get_document_accounting_table(
    document_id: str,
    db: Session = Depends(get_db_session),
):
    """Return accounting data pivoted into a 2D spreadsheet for a document.

    Rows = accounts (units), Columns = categories, Cells = {amount, evidence}.
    The response includes page_number in each cell's evidence for PDF drill-down.
    Page numbers are transformed to original PDF coordinates when the scan
    had page_order_reversed or rotation applied.
    """
    try:
        parsed_id = uuid.UUID(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid document ID") from exc

    # Find document units with accounting results
    doc_units = db.execute(
        select(DocumentUnit)
        .join(ScanUnit, ScanUnit.id == DocumentUnit.scan_unit_id)
        .where(ScanUnit.source_document_id == parsed_id)
        .where(DocumentUnit.specialist_results.any(
            SpecialistResult.specialist_type == "accounting_statement"
        ))
        .options(selectinload(DocumentUnit.specialist_results))
        .order_by(DocumentUnit.ordinal)
    ).scalars().all()

    if not doc_units:
        raise HTTPException(status_code=404, detail="No accounting data found for this document")

    # Load preflight info for page number transformation
    # Group document units by scan unit to load preflight once per scan unit
    scan_unit_ids = set(du.scan_unit_id for du in doc_units)
    preflight_map: dict[uuid.UUID, dict] = {}
    scan_unit_page_counts: dict[uuid.UUID, int] = {}
    for su_id in scan_unit_ids:
        scan_unit = db.get(ScanUnit, su_id)
        if scan_unit is not None:
            preflight = _load_preflight(scan_unit, db)
            if preflight is not None:
                preflight_map[su_id] = preflight
            scan_unit_page_counts[su_id] = scan_unit.page_count

    tables = []
    for du in doc_units:
        table = _accounting_specialist_summary_view(du) or get_accounting_table(db, du.id)
        if table is not None:
            source_explanations = _accounting_source_table_explanations(du)
            table["document_unit_id"] = str(du.id)
            table["title"] = du.title or f"Pagine {du.start_page}-{du.end_page}"
            table["ordinal"] = du.ordinal
            table["start_page"] = du.start_page
            table["end_page"] = du.end_page
            table["explanation"] = _accounting_summary_table_explanation(table, source_explanations)

            # Transform page numbers if page order was reversed
            # The evidence page_number is in corrected (post-preflight) coordinates.
            # We need original PDF coordinates for the viewer.
            preflight = preflight_map.get(du.scan_unit_id)
            page_count = scan_unit_page_counts.get(du.scan_unit_id)
            if preflight and preflight.get("page_order_reversed") and page_count:
                for row in table.get("rows", []):
                    for cell in row.get("cells", {}).values():
                        if isinstance(cell, dict):
                            _transform_accounting_cell_page_numbers(cell, page_count)

            tables.append(table)

    return {"document_id": document_id, "tables": tables}


def _accounting_specialist_summary_view(doc_unit: DocumentUnit) -> dict[str, Any] | None:
    for result in sorted(doc_unit.specialist_results, key=lambda item: item.created_at, reverse=True):
        if result.specialist_type != "accounting_statement" or not isinstance(result.result_json, dict):
            continue
        summary_view = result.result_json.get("summary_view")
        if not isinstance(summary_view, dict):
            continue
        rows = summary_view.get("rows")
        columns = summary_view.get("columns")
        totals = summary_view.get("totals")
        if isinstance(rows, list) and rows and isinstance(columns, list) and isinstance(totals, dict):
            return {
                "document_unit_id": str(doc_unit.id),
                "source": summary_view.get("source") or "specialist_summary_view",
                "columns": columns,
                "rows": rows,
                "totals": totals,
                "explanation": summary_view.get("explanation"),
                "source_columns": summary_view.get("source_columns", []),
            }
    return None


def _transform_accounting_cell_page_numbers(cell: dict[str, Any], page_count: int) -> None:
    ev = cell.get("evidence", {})
    if isinstance(ev, dict) and ev.get("page_number") is not None:
        ev["page_number"] = page_count - ev["page_number"] + 1
    for fact in cell.get("facts", []) or []:
        if not isinstance(fact, dict):
            continue
        fact_ev = fact.get("evidence", {})
        if isinstance(fact_ev, dict) and fact_ev.get("page_number") is not None:
            fact_ev["page_number"] = page_count - fact_ev["page_number"] + 1


@router.get("/documents/{document_id}/accounting-table/cell-detail")
def get_document_accounting_cell_detail(
    document_id: str,
    table_id: str = Query(..., description="Table ID from the accounting table"),
    row_id: str = Query(..., description="Row ID within the table"),
    column: str = Query(..., description="Column/category name"),
    db: Session = Depends(get_db_session),
):
    """Return detail for a single cell in the accounting table.

    Looks up the raw specialist result to find the table, row, and column,
    returning page_number, raw_value, and surrounding table context for
    PDF drill-down.
    """
    try:
        parsed_id = uuid.UUID(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid document ID") from exc

    detail = get_accounting_cell_detail(
        session=db,
        document_id=parsed_id,
        table_id=table_id,
        row_id=row_id,
        column=column,
    )

    if detail is None:
        raise HTTPException(status_code=404, detail="Cell not found")

    # Transform page number if page order was reversed
    if detail.get("page_number") is not None:
        # Find the scan unit for this document unit to get preflight info
        du_id = detail.get("document_unit_id")
        if du_id:
            doc_unit = db.get(DocumentUnit, uuid.UUID(du_id))
            if doc_unit is not None:
                scan_unit = db.get(ScanUnit, doc_unit.scan_unit_id)
                if scan_unit is not None:
                    preflight = _load_preflight(scan_unit, db)
                    if preflight and preflight.get("page_order_reversed"):
                        detail["page_number"] = scan_unit.page_count - detail["page_number"] + 1

    return detail


def _fallback_accounting_table_explanation(table: dict[str, Any]) -> dict[str, Any]:
    role = table.get("role") or table.get("section_role")
    table_type = table.get("table_type")
    rows = table.get("rows")
    row_count = len(rows) if isinstance(rows, list) else 0
    headers = table.get("headers")
    header_count = len(headers) if isinstance(headers, list) else 0
    context = table.get("accounting_context")
    period = ""
    if isinstance(context, dict):
        period_from = context.get("period_from")
        period_to = context.get("period_to")
        if period_from or period_to:
            period = f" per il periodo {period_from or '?'} - {period_to or '?'}"

    role_descriptions = {
        "actual_summary": "riassume dati di consuntivo o rendiconto",
        "actual_allocation": "ripartisce spese consuntive tra unita e soggetti",
        "actual_payments": "elenca pagamenti o movimenti registrati",
        "actual_personal_charge": "raccoglie addebiti personali",
        "budget_summary": "riassume dati di preventivo",
        "budget_allocation": "ripartisce spese preventive tra unita e soggetti",
        "budget_installment_schedule": "mostra rate e scadenze da versare",
        "allocation": "ripartisce importi tra unita e soggetti",
    }
    type_descriptions = {
        "expense_allocation": "una tabella di riparto spese",
        "payment_schedule": "un piano rate o scadenze",
        "summary": "una tabella riepilogativa",
        "balance": "una tabella di saldi",
        "payment_ledger": "un registro pagamenti",
        "unknown": "una tabella non classificata con certezza",
    }
    description = role_descriptions.get(str(role), type_descriptions.get(str(table_type), "una tabella estratta dal documento"))
    summary = (
        f"Questa tabella {description}{period}. "
        f"Contiene {row_count} righe e {header_count} colonne; le celle sono il testo strutturato estratto dall'OCR "
        "e possono includere importi, millesimi, descrizioni o totali non ancora promossi a fatti contabili normalizzati."
    )
    return {
        "summary": summary,
        "role": role or table_type,
        "source": "api_fallback",
        "review_status": "fallback",
    }


def _accounting_source_table_explanations(doc_unit: DocumentUnit) -> dict[str, dict[str, Any]]:
    explanations: dict[str, dict[str, Any]] = {}
    for result in doc_unit.specialist_results:
        if result.specialist_type != "accounting_statement" or not isinstance(result.result_json, dict):
            continue
        for raw_table in result.result_json.get("tables", []) or []:
            if not isinstance(raw_table, dict):
                continue
            table_id = raw_table.get("table_id")
            if table_id is None:
                continue
            explanation = raw_table.get("llm_explanation")
            if isinstance(explanation, dict) and explanation.get("summary"):
                explanations[str(table_id)] = explanation
    return explanations


def _accounting_summary_table_explanation(
    table: dict[str, Any],
    source_explanations: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source_ids: list[str] = []
    for row in table.get("rows", []) or []:
        if not isinstance(row, dict):
            continue
        for cell in (row.get("cells") or {}).values():
            if not isinstance(cell, dict):
                continue
            for fact in cell.get("facts", []) or []:
                evidence = fact.get("evidence") if isinstance(fact, dict) else None
                table_id = evidence.get("table_id") if isinstance(evidence, dict) else None
                if table_id is not None and str(table_id) not in source_ids:
                    source_ids.append(str(table_id))

    selected = [source_explanations[table_id] for table_id in source_ids if table_id in source_explanations]
    if selected:
        joined = " ".join(str(item.get("summary", "")).strip() for item in selected[:4] if item.get("summary"))
        if len(selected) > 4:
            joined += f" Altre {len(selected) - 4} tabelle contribuiscono alla sintesi."
        return {
            "summary": (
                "Questa vista e una sintesi normalizzata costruita aggregando fatti contabili "
                f"estratti dalle tabelle sorgenti. {joined}"
            ).strip(),
            "role": "normalized_accounting_summary",
            "source": "source_table_llm_explanations",
            "review_status": "unverified",
            "source_table_ids": source_ids,
        }
    return {
        "summary": (
            "Questa vista e una sintesi normalizzata costruita aggregando i fatti contabili "
            "materializzati dalle tabelle sorgenti. Le celle possono sommare piu righe quando "
            "piu fatti condividono la stessa unita e categoria."
        ),
        "role": "normalized_accounting_summary",
        "source": "api_fallback",
        "review_status": "fallback",
        "source_table_ids": source_ids,
    }


@router.get("/documents/{document_id}/accounting-raw-tables")
def get_document_accounting_raw_tables(
    document_id: str,
    db: Session = Depends(get_db_session),
):
    """Return raw accounting tables extracted by the specialist worker.

    This is intentionally separate from the normalized accounting_facts pivot:
    it exposes the original table headers and rows so humans can inspect
    detailed allocations that are not yet promoted to queryable facts.
    """
    try:
        parsed_id = uuid.UUID(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid document ID") from exc

    doc_units = db.execute(
        select(DocumentUnit)
        .join(ScanUnit, ScanUnit.id == DocumentUnit.scan_unit_id)
        .where(ScanUnit.source_document_id == parsed_id)
        .where(DocumentUnit.specialist_results.any(
            SpecialistResult.specialist_type == "accounting_statement"
        ))
        .options(selectinload(DocumentUnit.specialist_results))
        .order_by(DocumentUnit.ordinal)
    ).scalars().all()

    tables = []
    for du in doc_units:
        scan_unit = db.get(ScanUnit, du.scan_unit_id)
        preflight = _load_preflight(scan_unit, db) if scan_unit is not None else None
        for result in du.specialist_results:
            if result.specialist_type != "accounting_statement":
                continue
            result_tables = result.result_json.get("tables", []) if isinstance(result.result_json, dict) else []
            for table in result_tables:
                if not isinstance(table, dict):
                    continue
                page_number = table.get("page_number")
                if (
                    page_number is not None
                    and scan_unit is not None
                    and preflight
                    and preflight.get("page_order_reversed")
                ):
                    page_number = scan_unit.page_count - page_number + 1
                rows = []
                for row in table.get("rows", []) or []:
                    if not isinstance(row, dict):
                        continue
                    cells = row.get("cells", {})
                    rows.append(
                        {
                            "row_id": row.get("row_id"),
                            "cells": cells if isinstance(cells, dict) else {},
                        }
                    )
                tables.append(
                    {
                        "document_unit_id": str(du.id),
                        "document_unit_title": du.title or f"Pagine {du.start_page}-{du.end_page}",
                        "document_unit_ordinal": du.ordinal,
                        "start_page": du.start_page,
                        "end_page": du.end_page,
                        "table_id": table.get("table_id"),
                        "table_type": table.get("table_type"),
                        "page_number": page_number,
                        "role": table.get("role"),
                        "section_id": table.get("section_id"),
                        "section_label": table.get("section_label"),
                        "section_role": table.get("section_role"),
                        "accounting_context": table.get("accounting_context") if isinstance(table.get("accounting_context"), dict) else None,
                        "title": table.get("title"),
                        "headers": table.get("headers", []) if isinstance(table.get("headers", []), list) else [],
                        "rows": rows,
                        "explanation": (
                            table.get("llm_explanation")
                            if isinstance(table.get("llm_explanation"), dict) and table.get("llm_explanation", {}).get("summary")
                            else _fallback_accounting_table_explanation(table)
                        ),
                    }
                )

    return {"document_id": document_id, "tables": tables}


@router.get("/cleanup/report", response_model=CleanupReportResponse)
def get_cleanup_report(
    min_similarity: float = Query(0.90, description="Minimum title similarity for duplicate detection"),
    db: Session = Depends(get_db_session),
):
    """Generate a read-only cleanup report for topic backlog.

    Returns candidate groups for merge/review, same categories as the
    scripts/topic_cleanup_report.py script.
    """
    from knowledge_classifier.services.consolidation import KnowledgeBaseConsolidationService

    service = KnowledgeBaseConsolidationService(db)
    report = service.generate_cleanup_report(min_similarity=min_similarity)
    return CleanupReportResponse(
        categories=report.get("categories", {}),
        summary=report.get("summary", {}),
    )


def _inactive_topic_cleanup_items(db: Session) -> list[dict[str, Any]]:
    assignment_counts = dict(
        db.execute(
            select(
                DocumentUnitTopicAssignment.topic_id,
                func.count(DocumentUnitTopicAssignment.id),
            ).group_by(DocumentUnitTopicAssignment.topic_id)
        ).all()
    )
    pending_counts = dict(
        db.execute(
            select(
                TopicProposal.matched_existing_topic_id,
                func.count(TopicProposal.id),
            )
            .where(
                TopicProposal.matched_existing_topic_id.is_not(None),
                TopicProposal.proposal_status == "proposed",
            )
            .group_by(TopicProposal.matched_existing_topic_id)
        ).all()
    )
    topics = db.execute(
        select(Topic)
        .where(Topic.is_active.is_(False))
        .order_by(Topic.created_at.asc())
    ).scalars().all()

    items: list[dict[str, Any]] = []
    for topic in topics:
        assignment_count = int(assignment_counts.get(topic.id, 0))
        pending_proposal_count = int(pending_counts.get(topic.id, 0))
        deletable = (
            not topic.canonical
            and assignment_count == 0
            and pending_proposal_count == 0
        )
        if topic.canonical:
            reason = "Topic canonico: non cancellabile automaticamente."
        elif assignment_count > 0:
            reason = "Ha ancora assegnazioni: prima va unito o ritargettizzato."
        elif pending_proposal_count > 0:
            reason = "Ha proposte pendenti: prima vanno risolte."
        else:
            reason = "Inattivo, non canonico, senza assegnazioni o proposte pendenti."
        items.append(
            {
                "id": str(topic.id),
                "title": topic.title,
                "slug": topic.slug,
                "topic_kind": topic.topic_kind,
                "topic_class": topic.topic_class,
                "assignment_count": assignment_count,
                "pending_proposal_count": pending_proposal_count,
                "deletable": deletable,
                "reason": reason,
            }
        )
    return items


@router.get("/cleanup/inactive-topics", response_model=InactiveTopicCleanupResponse)
def preview_inactive_topic_cleanup(db: Session = Depends(get_db_session)):
    """Preview inactive topics and which ones can be safely deleted."""
    items = _inactive_topic_cleanup_items(db)
    return InactiveTopicCleanupResponse(
        items=items,
        deletable_count=sum(1 for item in items if item["deletable"]),
        deleted_count=0,
    )


@router.delete("/cleanup/inactive-topics", response_model=InactiveTopicCleanupResponse)
def delete_deletable_inactive_topics(db: Session = Depends(get_db_session)):
    """Delete only inactive non-canonical topics with no assignments or pending proposals."""
    items_before = _inactive_topic_cleanup_items(db)
    deletable_ids = [uuid.UUID(item["id"]) for item in items_before if item["deletable"]]
    if deletable_ids:
        db.execute(delete(Topic).where(Topic.id.in_(deletable_ids)))
        db.commit()
    items_after = _inactive_topic_cleanup_items(db)
    return InactiveTopicCleanupResponse(
        items=items_after,
        deletable_count=sum(1 for item in items_after if item["deletable"]),
        deleted_count=len(deletable_ids),
    )
