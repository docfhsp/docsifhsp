# filename: router.py

import logging
import json
import tempfile
import os
import aiohttp
import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, BackgroundTasks
from pydantic import BaseModel
from scuid import scuid

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
    file: UploadFile = File(None, description="File to convert"),
    url: str = Form(
        None, description="URL to convert (used only if no file is provided)"
    ),
    openai: str = Form("{}", description="OpenAI config as a JSON object"),
    settings: str = Form("{}", description="Settings as a JSON object"),
):
    """
    Convert a file or an HTML page from a URL into Markdown.
    If 'file' is provided, it has priority over 'url'.
    - 'openai' is a JSON string with keys: {"api_key": "...", "base_url": "..."}
    - 'settings' is a JSON string with keys: {"cleanup": bool}
    """
    try:
        # Parse configs
        try:
            openai_config = json.loads(openai) if openai else {}
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON in 'openai' parameter.")

        try:
            settings_config = json.loads(settings) if settings else {}
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON in 'settings' parameter.")

        cleanup = settings_config.get("cleanup", True)

        # If a file is provided, use the existing flow
        if file is not None:
            with tempfile.TemporaryDirectory() as tmpdir:
                contents = await file.read()
                guessed_ext = mimetypes.guess_extension(file.content_type) or ""
                new_name = f"{Path(file.filename).stem}{guessed_ext}"
                temp_path = Path(tmpdir) / new_name
                temp_path.write_bytes(contents)
                result, token_count = await docsifer_service.convert_file(
                    file_path=str(temp_path),
                    openai_config=openai_config,
                    cleanup=cleanup,
                )
        # Otherwise, fetch HTML from URL and convert
        elif url:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        raise ValueError(f"Failed to fetch URL: status {resp.status}")
                    data = await resp.read()
            with tempfile.TemporaryDirectory() as tmpdir:
                temp_path = Path(tmpdir) / f"{scuid()}.html"
                temp_path.write_bytes(data)
                result, token_count = await docsifer_service.convert_file(
                    file_path=str(temp_path),
                    openai_config=openai_config,
                    cleanup=cleanup,
                )
        else:
            raise HTTPException(
                status_code=400, detail="Provide either 'file' or 'url'."
            )

        # Track usage
        background_tasks.add_task(analytics.access, token_count)
        return ConvertResponse(**result)

    except Exception as e:
        msg = f"Failed to convert content. Error: {str(e)}"
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
