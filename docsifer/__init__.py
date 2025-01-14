# filename: __init__.py

import json
import logging
import tempfile
from typing import Tuple, Optional

import gradio as gr
import pandas as pd
import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from gradio.routes import mount_gradio_app
from pathlib import Path

# If you want to generate unique filenames, e.g. scuid:
from scuid import scuid


# Filter out /v1 requests from the access log
class LogFilter(logging.Filter):
    def filter(self, record):
        # Only keep log records that contain "/v1" in the request path
        if record.args and len(record.args) >= 3:
            if "/v1" in str(record.args[2]):
                return True
        return False


logger = logging.getLogger("uvicorn.access")
logger.addFilter(LogFilter())

# Application metadata
__version__ = "1.0.0"
__author__ = "lamhieu"
__description__ = "Docsifer: Efficient Data Conversion to Markdown."
__metadata__ = {
    "project": "Docsifer",
    "version": __version__,
    "description": (
        "Effortlessly convert various files to Markdown, including PDF, PowerPoint, Word, Excel, "
        "images, audio, HTML, JSON, CSV, XML, ZIP, and more."
    ),
    "docs": "https://lamhieu-docsifer.hf.space/docs",
    "github": "https://github.com/lh0x00/docsifer",
    "spaces": "https://huggingface.co/spaces/lh0x00/docsifer",
}

# Update your Docsifer API endpoints (you can replace with your HF Space or other URL)
DOCSIFER_API_URL = "http://localhost:7860/v1/convert"
DOCSIFER_STATS_URL = "http://localhost:7860/v1/stats"

# Markdown description for the main interface
APP_DESCRIPTION = f"""
# 📝 **Docsifer: Convert Your Documents to Markdown**

Welcome to **Docsifer**, a specialized service that converts your files—like PDF, PPT, Word, Excel, images, audio, HTML, JSON, CSV, XML, ZIP, etc.—into **Markdown** using **MarkItDown** at the core. Optionally, you can leverage **LLMs** (OpenAI) for advanced text extraction.

### Features & Privacy

- **Open Source**: The entire Docsifer codebase is publicly available for review and contribution.
- **Efficient & Flexible**: Supports multiple file formats, ensuring quick and accurate Markdown conversion.
- **Privacy-Focused**: We never store user data; all processing is ephemeral. We only collect minimal anonymous usage stats for service improvement.
- **Production-Ready**: Easy Docker deployment, interactive Gradio playground, and comprehensive REST API documentation.
- **Community & Collaboration**: Contribute on [GitHub]({__metadata__["github"]}) or try it out on [Hugging Face Spaces]({__metadata__["spaces"]}).

### 🔗 Resources
- [Documentation]({__metadata__["docs"]}) | [GitHub]({__metadata__["github"]}) | [Live Demo]({__metadata__["spaces"]})
"""

# Initialize FastAPI application
app = FastAPI(
    title="Docsifer Service API",
    description=__description__,
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust if needed for specific domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import and include your existing router (which has /v1/convert, /v1/stats, etc.)
from .router import router

app.include_router(router, prefix="/v1")


def call_convert_api(
    file_obj: bytes,
    filename: str,
    cleanup: bool = True,
    openai_base_url: Optional[str] = None,
    openai_api_key: Optional[str] = None,
    openai_model: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Calls the /v1/convert endpoint, returning (markdown_content, md_file_path).
    If there's an error, the first return value is an error message (str),
    the second is an empty string.

    The updated /v1/convert expects:
      - file (UploadFile)
      - openai (object, e.g. {"api_key":"...","base_url":"..."})
      - settings (object, e.g. {"cleanup": true})
    """

    if file_obj is None:
        return ("❌ No file was uploaded.", "")

    # Build the "openai" object
    openai_dict = {}
    if openai_api_key and openai_api_key.strip():
        openai_dict["api_key"] = openai_api_key
    if openai_base_url and openai_base_url.strip():
        openai_dict["base_url"] = openai_base_url
    if openai_model and openai_model.strip():
        openai_dict["model"] = openai_model

    # Build the "settings" object
    settings_dict = {"cleanup": cleanup}

    data = {
        # These must match the `Form(...)` fields named "openai" and "settings"
        "openai": json.dumps(openai_dict),
        "settings": json.dumps(settings_dict),
    }

    if len(openai_dict) <= 3:
        data.pop("openai")

    # Prepare files for multipart/form-data
    files = {"file": (filename, file_obj)}

    try:
        response = requests.post(DOCSIFER_API_URL, files=files, data=data, timeout=30)
    except requests.exceptions.RequestException as e:
        return (f"❌ Network Error: {str(e)}", "")

    if response.status_code != 200:
        return (f"❌ API Error {response.status_code}: {response.text}", "")

    try:
        converted = response.json()
        # Expecting { "filename": "...", "markdown": "..." }
        markdown_content = converted["markdown"]
    except Exception as e:
        return (f"❌ Error parsing JSON: {str(e)}", "")

    # Write the returned Markdown to a temporary .md file so Gradio can serve it
    with tempfile.NamedTemporaryFile(
        mode="w+", suffix=".md", dir="/tmp", delete=False
    ) as tmp_file:
        tmp_file.write(markdown_content)
        tmp_md_path = tmp_file.name

    return (markdown_content, tmp_md_path)


def call_stats_api_df() -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Calls /v1/stats endpoint to retrieve analytics data.
    Returns two DataFrames: (access_df, tokens_df).
    """
    try:
        response = requests.get(DOCSIFER_STATS_URL, timeout=10)
    except requests.exceptions.RequestException as e:
        raise ValueError(f"Failed to fetch stats: {str(e)}")

    if response.status_code != 200:
        raise ValueError(f"Failed to fetch stats: {response.text}")

    data = response.json()
    # Expected structure:
    # {
    #   "access": { <period>: {"docsifer": count, ...}, ... },
    #   "tokens": { <period>: {"docsifer": count, ...}, ... }
    # }
    access_data = data.get("access", {})
    tokens_data = data.get("tokens", {})

    def build_stats_df(bucket: dict) -> pd.DataFrame:
        # We want columns for periods: total, daily, weekly, monthly, yearly
        # Each row => "docsifer" (just 1 row if everything is aggregated)
        all_models = set()
        for period_key in ["total", "daily", "weekly", "monthly", "yearly"]:
            period_dict = bucket.get(period_key, {})
            all_models.update(period_dict.keys())  # typically just "docsifer"

        result_dict = {
            "Model": [],
            "Total": [],
            "Daily": [],
            "Weekly": [],
            "Monthly": [],
            "Yearly": [],
        }

        for model in sorted(all_models):
            result_dict["Model"].append(model)
            result_dict["Total"].append(bucket.get("total", {}).get(model, 0))
            result_dict["Daily"].append(bucket.get("daily", {}).get(model, 0))
            result_dict["Weekly"].append(bucket.get("weekly", {}).get(model, 0))
            result_dict["Monthly"].append(bucket.get("monthly", {}).get(model, 0))
            result_dict["Yearly"].append(bucket.get("yearly", {}).get(model, 0))

        return pd.DataFrame(result_dict)

    access_df = build_stats_df(access_data)
    tokens_df = build_stats_df(tokens_data)
    return access_df, tokens_df


def create_main_interface():
    """
    Creates a Gradio Blocks interface:
    - A 'Conversion Playground' tab for uploading a file and converting to Markdown
    - An 'Analytics Stats' section to display usage statistics
    - cURL examples for reference
    """
    with gr.Blocks(title="Docsifer: Convert to Markdown", theme="default") as demo:
        gr.Markdown(APP_DESCRIPTION)

        with gr.Tab("Conversion Playground"):
            gr.Markdown("### Convert your files to Markdown with Docsifer.")

            with gr.Row():
                with gr.Column():
                    file_input = gr.File(
                        label="Upload File",
                        file_types=[
                            ".pdf",
                            ".docx",
                            ".pptx",
                            ".xlsx",
                            ".html",
                            ".htm",
                            ".jpg",
                            ".jpeg",
                            ".png",
                            ".mp3",
                            ".wav",
                            ".zip",
                        ],
                        type="binary",
                    )

                    with gr.Accordion("OpenAI Configuration (Optional)", open=False):
                        gr.Markdown(
                            "Provide these if you'd like **LLM-assisted** extraction. "
                            "Supports both OpenAI and OpenAI-compatible APIs. "
                            "If left blank, basic conversion (no LLM) will be used."
                        )
                        openai_base_url = gr.Textbox(
                            label="Base URL",
                            placeholder="https://api.openai.com/v1",
                            value="https://api.openai.com/v1",
                        )
                        openai_api_key = gr.Textbox(
                            label="API Key",
                            placeholder="sk-...",
                            type="password",
                        )
                        openai_model = gr.Textbox(
                            label="Model ID",
                            placeholder="e.g. gpt-4o-mini",
                            value="gpt-4o-mini",
                        )

                    with gr.Accordion("Conversion Settings", open=True):
                        gr.Markdown(
                            "Enable to remove <style> tags or hidden elements from `.html` files before conversion."
                        )
                        cleanup_toggle = gr.Checkbox(
                            label="Enable Cleanup",
                            value=True,
                        )

                    convert_btn = gr.Button("Convert")

                with gr.Column():
                    output_md = gr.Textbox(
                        label="Conversion Result (Markdown)",
                        lines=20,
                        interactive=False,
                    )
                    # Set visible=True so the user always sees a small download button
                    download_file = gr.File(
                        label="Download",
                        interactive=False,
                        visible=True,
                    )

                    gr.Markdown(
                        """
                        ### cURL Examples

                        **Convert via File Upload (multipart/form-data)**:
                        ```bash
                        curl -X POST \\
                            "https://lamhieu-docsifer.hf.space/v1/convert" \\
                            -F "file=@/path/to/local/document.pdf" \\
                            -F "openai={\\"api_key\\":\\"sk-xxxxx\\",\\"model\\":\\"gpt-4o-mini\\",\\"base_url\\":\\"https://api.openai.com/v1\\"}" \\
                            -F "settings={\\"cleanup\\":true}"
                        ```
                        """
                    )

            def on_convert(file_bytes, base_url, api_key, model_id, cleanup):
                """
                Callback for the 'Convert' button.
                We generate a unique name if the user uploads a file.
                """
                if not file_bytes:
                    return "❌ Please upload a file first.", None

                unique_name = f"{scuid()}.tmp"
                markdown, temp_md_path = call_convert_api(
                    file_obj=file_bytes,
                    filename=unique_name,
                    openai_base_url=base_url,
                    openai_api_key=api_key,
                    openai_model=model_id,
                    cleanup=cleanup,
                )
                return markdown, temp_md_path

            convert_btn.click(
                fn=on_convert,
                inputs=[
                    file_input,
                    openai_base_url,
                    openai_api_key,
                    openai_model,
                    cleanup_toggle,
                ],
                outputs=[output_md, download_file],
            )

        with gr.Tab("Analytics Stats"):
            gr.Markdown(
                "View Docsifer usage statistics (access count, token usage, etc.)"
            )
            stats_btn = gr.Button("Get Stats")
            access_df = gr.DataFrame(
                label="Access Stats",
                headers=["Model", "Total", "Daily", "Weekly", "Monthly", "Yearly"],
                interactive=False,
            )
            tokens_df = gr.DataFrame(
                label="Token Stats",
                headers=["Model", "Total", "Daily", "Weekly", "Monthly", "Yearly"],
                interactive=False,
            )

            stats_btn.click(
                fn=call_stats_api_df,
                inputs=[],
                outputs=[access_df, tokens_df],
            )

    return demo


# Build our Gradio interface and mount it at the root path
main_interface = create_main_interface()
mount_gradio_app(app, main_interface, path="/")


# Startup / Shutdown events
@app.on_event("startup")
async def startup_event():
    logger.info("Docsifer Service is starting up...")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Docsifer Service is shutting down.")
