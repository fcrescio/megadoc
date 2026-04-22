"""Celery tasks for knowledge processing."""

import logging
import os
import uuid

from celery import shared_task
from sqlalchemy.ext.asyncio import create_async_engine, async_session

from common.db.base import Base
from knowledge_classifier.config import get_settings
from knowledge_classifier.llm.mock import MockDeterministicProvider
from knowledge_classifier.llm.openai_compat import OpenAICompatibleProvider
from knowledge_classifier.services.pipeline import KnowledgePipelineService

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
async def process_scan_unit_task(self, scan_unit_id: str):
    """Process a scan unit through the knowledge pipeline.
    
    Args:
        scan_unit_id: ID of the scan unit to process
    """
    logger.info(f"Task started: process_scan_unit {scan_unit_id}")
    
    settings = get_settings()
    
    # Create DB session
    engine = create_async_engine(
        os.getenv("DATABASE_URL", "postgresql+psycopg://megadoc:megadoc@postgres:5432/megadoc"),
        echo=False,
    )
    
    async with async_session(engine) as session:
        try:
            # Initialize LLM provider
            if settings.use_mock_llm:
                llm_provider = MockDeterministicProvider(model=settings.llm_model)
            else:
                llm_provider = OpenAICompatibleProvider(
                    base_url=settings.llm_endpoint,
                    model=settings.llm_model,
                    api_key=settings.llm_api_key,
                    timeout=settings.llm_timeout,
                )
            
            # Create pipeline service
            pipeline = KnowledgePipelineService(llm_provider, session)
            
            # Process scan unit
            result = await pipeline.process_scan_unit(scan_unit_id)
            
            # Commit changes
            await session.commit()
            
            logger.info(f"Task completed: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Task failed: {e}")
            await session.rollback()
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        finally:
            await session.close()


@shared_task
async def process_scan_unit_sync(scan_unit_id: str):
    """Synchronous version for testing."""
    return await process_scan_unit_task(scan_unit_id)
