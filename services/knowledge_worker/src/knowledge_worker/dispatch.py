"""Helper for dispatching knowledge worker tasks from API."""

import os
from celery import Celery

# Create a minimal Celery app for task dispatching
broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")

dispatch_app = Celery(
    "knowledge_dispatcher",
    broker=broker_url,
)

dispatch_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_routes={
        "knowledge_worker.tasks.*": {"queue": "knowledge"},
    },
)


def dispatch_scan_unit_processing(scan_unit_id: str) -> str:
    """Dispatch a scan unit processing task to the knowledge worker.
    
    Args:
        scan_unit_id: ID of the scan unit to process
        
    Returns:
        Celery task ID
    """
    # Use the dispatch app to send the task
    result = dispatch_app.send_task(
        "knowledge_worker.tasks.process_scan_unit_task",
        args=[scan_unit_id],
        queue="knowledge",
    )
    return result.id
