import logging
import json
import tempfile
import os
# import aiohttp
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, BackgroundTasks
from pydantic import BaseModel
# from scuid import scuid

from .service import DocsiferService
from .analytics import Analytics

logger = logging.getLogger(__name__)
router = APIRouter(tags=["v1"], responses={404: {"description": "Not found"}})

# Initialize analytics (aggregated under "docsifer")
analytics = Analytics(
    url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    token=os.environ.get("REDIS_TOKEN", "***"),
    sync_interval=30 * 60,  # e.g. 30 minutes
)

# Initialize the Docsifer service (using "gpt-4o" for token counting)
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
    http: str = Form("{}", description="HTTP config as a JSON object"),
    settings: str = Form("{}", description="Settings as a JSON object"),
):
    """
    Convert a file or an HTML page from a URL into Markdown.
    If 'file' is provided, it takes priority over 'url'.

    - 'openai' is a JSON string with keys such as {"api_key": "...", "base_url": "..."}.
    - 'settings' is a JSON string with keys such as {"cleanup": bool}.
    """
    try:
        # Parse the JSON configuration parameters.
        try:
            openai_config = json.loads(openai) if openai else {}
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON in 'openai' parameter.")

        try:
            http_config = json.loads(http) if http else {}
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON in 'http' parameter.")

        try:
            settings_config = json.loads(settings) if settings else {}
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON in 'settings' parameter.")

        cleanup = settings_config.get("cleanup", True)
        print("> convert_document, file", [file, file is not None])

        # If a file is provided, use it; otherwise, fetch the content from the URL.
        if file is not None:
            with tempfile.TemporaryDirectory() as tmpdir:
                temp_path = Path(tmpdir) / file.filename
                contents = await file.read()
                temp_path.write_bytes(contents)
                print("> convert_document, temp_path", [temp_path, temp_path.exists()])
                result, token_count = await docsifer_service.convert_file(
                    source=str(temp_path),
                    openai_config=openai_config,
                    http_config=http_config,
                    cleanup=cleanup,
                )
        elif url:
            # async with aiohttp.ClientSession() as session:
            #     async with session.get(url) as resp:
            #         if resp.status != 200:
            #             raise ValueError(f"Failed to fetch URL: status {resp.status}")
            #         data = await resp.read()
            # with tempfile.TemporaryDirectory() as tmpdir:
            #     temp_path = Path(tmpdir) / f"{scuid()}.html"
            #     temp_path.write_bytes(data)
            #     result, token_count = await docsifer_service.convert_file(
            #         source=str(temp_path),
            #         openai_config=openai_config,
            #         cleanup=cleanup,
            #     )
            result, token_count = await docsifer_service.convert_file(
                source=str(url),
                openai_config=openai_config,
                http_config=http_config,
                cleanup=cleanup,
            )
        else:
            raise HTTPException(
                status_code=400, detail="Provide either 'file' or 'url'."
            )

        # Record token usage in the background.
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
    """
    try:
        data = await analytics.stats()
        return data
    except Exception as e:
        msg = f"Failed to fetch analytics stats: {str(e)}"
        logger.error(msg)
        raise HTTPException(status_code=500, detail=msg)
