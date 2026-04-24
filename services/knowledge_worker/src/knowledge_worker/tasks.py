"""Celery tasks for knowledge processing."""

import logging
import os
from datetime import datetime, timezone

from celery import shared_task
from sqlalchemy import select
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from common.db.models import KnowledgeJob
from knowledge_classifier.config import get_settings
from knowledge_classifier.llm.mock import MockDeterministicProvider
from knowledge_classifier.llm.openai_compat import OpenAICompatibleProvider
from knowledge_classifier.services.pipeline import KnowledgePipelineService

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def process_scan_unit_task(self, scan_unit_id: str):
    """Process a scan unit through the knowledge pipeline.
    
    Args:
        scan_unit_id: ID of the scan unit to process
    """
    logger.info(f"Task started: process_scan_unit {scan_unit_id}")
    
    settings = get_settings()
    
    # Create DB session
    engine = create_engine(
        os.getenv("DATABASE_URL", "postgresql+psycopg://megadoc:megadoc@postgres:5432/megadoc"),
        echo=False,
    )
    
    with Session(engine) as session:
        try:
            knowledge_job = _get_latest_knowledge_job(session, scan_unit_id)
            if knowledge_job is not None:
                knowledge_job.status = "processing"
                knowledge_job.started_at = datetime.now(timezone.utc)
                knowledge_job.attempt_count += 1
                knowledge_job.error_message = None
                session.flush()

            # Initialize LLM provider
            if settings.use_mock_llm:
                llm_provider = MockDeterministicProvider(model=settings.llm_model)
            else:
                llm_provider = OpenAICompatibleProvider(
                    base_url=settings.llm_endpoint,
                    model=settings.llm_model,
                    api_key=settings.llm_api_key,
                    timeout=settings.llm_timeout,
                    max_tokens=settings.llm_max_tokens,
                )
            
            # Create pipeline service
            pipeline = KnowledgePipelineService(llm_provider, session)
            
            # Process scan unit (sync)
            result = pipeline.process_scan_unit(scan_unit_id)

            if knowledge_job is not None:
                knowledge_job.status = "succeeded"
                knowledge_job.finished_at = datetime.now(timezone.utc)
                knowledge_job.error_message = None
            
            # Commit changes
            session.commit()
            
            logger.info(f"Task completed: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Task failed: {e}", exc_info=True)
            session.rollback()
            knowledge_job = _get_latest_knowledge_job(session, scan_unit_id)
            if knowledge_job is not None:
                knowledge_job.status = "failed"
                knowledge_job.finished_at = datetime.now(timezone.utc)
                knowledge_job.error_message = str(e)
                session.commit()
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        finally:
            session.close()


def _get_latest_knowledge_job(session: Session, scan_unit_id: str) -> KnowledgeJob | None:
    return session.execute(
        select(KnowledgeJob)
        .where(KnowledgeJob.scan_unit_id == scan_unit_id)
        .order_by(KnowledgeJob.created_at.desc())
    ).scalar_one_or_none()
