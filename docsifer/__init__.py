# filename: __init__.py

import json
import logging
import tempfile
import requests

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, HttpUrl

from gradio.routes import mount_gradio_app
import gradio as gr

# Constants
DOCSIFER_API_URL = "http://localhost:7860/v1/convert"

# FastAPI app instance
app = FastAPI(
    title="URL-to-Markdown API",
    description="Convert a URL's content directly to Markdown.",
    version="2.0.0"
)

# Logging setup
logger = logging.getLogger("uvicorn.access")

class URLRequest(BaseModel):
    url: HttpUrl

@app.post("/convert_url", summary="Convert a URL to Markdown")
def convert_url(request: URLRequest):
    """Convert the content at a URL to Markdown."""
    url = str(request.url)
    logger.info(f"Converting URL: {url}")

    # POST to Docsifer backend
    try:
        response = requests.post(
            DOCSIFER_API_URL,
            data={"url": url, "settings": json.dumps({"cleanup": True})},
            timeout=30,
        )
    except requests.RequestException as e:
        logger.error(f"Network error: {e}")
        raise HTTPException(status_code=502, detail="Network error: " + str(e))

    if response.status_code != 200:
        logger.error(f"Docsifer API error: {response.text}")
        raise HTTPException(status_code=500, detail=f"Docsifer API error: {response.text}")

    try:
        data = response.json()
        markdown = data["markdown"]
    except Exception as e:
        logger.error(f"Failed to parse Docsifer response: {e}")
        raise HTTPException(status_code=500, detail="Failed to parse Docsifer response.")

    # Optionally, write Markdown to file for download
    with tempfile.NamedTemporaryFile(
        mode="w+", suffix=".md", dir="/tmp", delete=False
    ) as tmp_file:
        tmp_file.write(markdown)
        tmp_md_path = tmp_file.name

    return {"markdown": markdown, "md_file_path": tmp_md_path}

# Minimal Gradio interface: URL to Markdown only
def gradio_url_to_md(url):
    if not url or not url.strip():
        return "❌ Please provide a valid URL.", None
    result = convert_url(URLRequest(url=url))
    return result["markdown"], result["md_file_path"]

with gr.Blocks(title="URL to Markdown") as demo:
    gr.Markdown("# URL → Markdown Converter\nPaste a URL below to convert its content to Markdown.")
    url_input = gr.Textbox(label="URL", placeholder="https://example.com/article")
    convert_btn = gr.Button("Convert")
    output_md = gr.Textbox(label="Markdown Output", lines=30, show_copy_button=True)
    download_file = gr.File(label="Download .md", interactive=False)

    convert_btn.click(
        fn=gradio_url_to_md,
        inputs=[url_input],
        outputs=[output_md, download_file]
    )

mount_gradio_app(app, demo, path="/")

@app.on_event("startup")
async def startup_event():
    logger.info("URL-to-Markdown Service starting up...")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("URL-to-Markdown Service shutting down.")