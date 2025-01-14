# filename: router.py

import logging
import json
import tempfile
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, BackgroundTasks
from pydantic import BaseModel

from .service import DocsiferService
from .analytics import Analytics

logger = logging.getLogger(__name__)
router = APIRouter(tags=["v1"], responses={404: {"description": "Not found"}})

# Initialize analytics (single aggregator = "docsifer")
analytics = Analytics(
    url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    token=os.environ.get("REDIS_TOKEN", "***"),
    sync_interval=30 * 60,  # e.g. 30 minutes
)

# Initialize the Docsifer service (token counting with gpt-4o)
docsifer_service = DocsiferService(model_name="gpt-4o")


class ConvertResponse(BaseModel):
    filename: str
    markdown: str


@router.post("/convert", response_model=ConvertResponse)
async def convert_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="File to convert (1 file per request)"),
    openai: str = Form("{}", description="OpenAI config as a JSON object"),
    settings: str = Form("{}", description="Settings as a JSON object"),
):
    """
    Convert a single uploaded file to Markdown, optionally using OpenAI for advanced text extraction.
    - `openai` is a JSON string with keys: {"api_key": "...", "base_url": "..."}
    - `settings` is a JSON string with keys: {"cleanup": bool}
    - We do not store or track model_id in analytics; everything is aggregated as "docsifer".
    """
    try:
        try:
            openai_config = json.loads(openai) if openai else {}
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON in 'openai' parameter.")

        try:
            settings_config = json.loads(settings) if settings else {}
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON in 'settings' parameter.")

        cleanup = settings_config.get("cleanup", True)

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir) / file.filename
            contents = await file.read()
            temp_path.write_bytes(contents)

            result, token_count = await docsifer_service.convert_file(
                file_path=str(temp_path), openai_config=openai_config, cleanup=cleanup
            )

        # Track usage in analytics (single aggregator => "docsifer")
        background_tasks.add_task(analytics.access, token_count)

        return ConvertResponse(**result)

    except Exception as e:
        msg = f"Failed to convert document. Error: {str(e)}"
        logger.error(msg)
        raise HTTPException(status_code=500, detail=msg)


@router.get("/stats")
async def get_stats():
    """
    Return usage statistics (access, tokens) from the Analytics system.
    All data is stored under "docsifer".
    """
    try:
        data = await analytics.stats()
        return data
    except Exception as e:
        msg = f"Failed to fetch analytics stats: {str(e)}"
        logger.error(msg)
        raise HTTPException(status_code=500, detail=msg)
