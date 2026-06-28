"""Knowledge classifier API router."""

import csv
import io
import os
import re
import unicodedata
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
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
from common.db.models import (
    CanonicalEntity,
    CanonicalEntityVariant,
    KnowledgeContext,
    KnowledgeContextAnchor,
    KnowledgeContextMembership,
    Document,
    DocumentType,
    OCRResult,
    ScanUnit,
    DocumentUnit,
    DocumentUnitEntity,
    DocumentUnitTopicAssignment,
    Topic,
    TopicAlias,
    TopicProposal,
    KnowledgeJob,
    GraphConsolidationReview,
    SpecialistJob,
    SpecialistResult,
    DocumentUnitLink,
    DocumentUnitMention,
    KnowledgeAssertion,
    KnowledgeNode,
    KnowledgeNodeAlias,
)
from common.db.session import SessionLocal, get_db_session
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
    existing = db.execute(select(Topic).where(Topic.slug == payload.slug)).scalar_one_or_none()
    if existing is not None:
        existing.title = payload.title
        existing.topic_class = payload.topic_class
        existing.topic_kind = payload.topic_kind
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
            topic_kind=payload.topic_kind,
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
        canonical_entity = CanonicalEntity(
            entity_type=payload.create_canonical_entity.entity_type,
            canonical_value=payload.create_canonical_entity.canonical_value,
            display_value=payload.create_canonical_entity.display_value,
            review_status="human_reviewed",
        )
        db.add(canonical_entity)
        db.flush()
    else:
        raise HTTPException(status_code=400, detail="Provide target_canonical_entity_id or create_canonical_entity")

    for entity_key in payload.entity_keys:
        entity_key_normalized = entity_key.strip().lower()
        if not entity_key_normalized:
            continue
        existing_variant = db.execute(
            select(CanonicalEntityVariant).where(
                CanonicalEntityVariant.entity_type == payload.entity_type,
                CanonicalEntityVariant.entity_key == entity_key_normalized,
            )
        ).scalar_one_or_none()
        if existing_variant is not None:
            existing_variant.canonical_entity_id = canonical_entity.id
            existing_variant.review_status = "human_reviewed"
            existing_variant.updated_at = _utcnow()
            continue

        display_row = db.execute(
            select(func.max(DocumentUnitEntity.entity_value))
            .where(
                DocumentUnitEntity.entity_type == payload.entity_type,
                _entity_key_expr() == entity_key_normalized,
            )
        ).scalar_one_or_none()
        db.add(
            CanonicalEntityVariant(
                canonical_entity_id=canonical_entity.id,
                entity_type=payload.entity_type,
                entity_key=entity_key_normalized,
                display_value=display_row or entity_key_normalized,
                review_status="human_reviewed",
            )
        )

    canonical_entity.review_status = "human_reviewed"
    canonical_entity.updated_at = _utcnow()
    db.commit()

    rebuild_knowledge_graph(db)
    rebuild_knowledge_contexts(db)
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

    plan = _plan_accounting_question(payload, tables)
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


def _accounting_llm_provider() -> OpenAICompatibleProvider | None:
    settings = get_knowledge_settings()
    endpoint = os.getenv("KN_WORKER_LLM_ENDPOINT", settings.llm_endpoint)
    if endpoint.startswith("mock://"):
        return None
    return OpenAICompatibleProvider(
        base_url=endpoint,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        timeout=max(settings.llm_timeout, 120),
        max_tokens=min(settings.llm_max_tokens, 2048),
    )


def _plan_accounting_question(
    payload: AccountingAskRequest,
    tables: list[dict[str, Any]],
) -> _AccountingAskPlan:
    provider = _accounting_llm_provider()
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
