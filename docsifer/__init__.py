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


class LogFilter(logging.Filter):
    """
    A custom logging filter that only keeps log records containing '/v1'
    in the request path. This helps to filter out other logs and reduce noise.
    """

    def filter(self, record):
        # Only keep log records that contain "/v1" in the request path
        if record.args and len(record.args) >= 3:
            if "/v1" in str(record.args[2]):
                return True
        return False


logger = logging.getLogger("uvicorn.access")
logger.addFilter(LogFilter())

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

# Docsifer API Endpoints (can be replaced with your live URLs if desired)
DOCSIFER_API_URL = "http://localhost:7860/v1/convert"
DOCSIFER_STATS_URL = "http://localhost:7860/v1/stats"

APP_DESCRIPTION = f"""
# 📝 **Docsifer: Convert Your Documents to Markdown**

Welcome to **Docsifer**, a specialized service that converts your files—like PDF, PPT, Word, Excel, images, audio, HTML, JSON, CSV, XML, ZIP, etc.—into **Markdown** using **MarkItDown** at the core. Optionally, you can leverage **LLMs** (OpenAI) for advanced text extraction.

### Features & Privacy

- **Open Source**: The entire Docsifer codebase is publicly available for review and contribution.
- **Efficient & Flexible**: Supports multiple file formats, ensuring quick and accurate Markdown conversion.
- **Privacy-Focused**: We never store user data; all processing is temporary. We only collect minimal anonymous usage statistics to count the number of calls and the number of tokens, nothing else.
- **Production-Ready**: Easy Docker deployment, interactive Gradio playground, and comprehensive REST API documentation.
- **Community & Collaboration**: Contribute on [GitHub]({__metadata__["github"]}) or try it out on [Hugging Face Spaces]({__metadata__["spaces"]}).

### 🔗 Resources
- [Documentation]({__metadata__["docs"]}) | [GitHub]({__metadata__["github"]}) | [Live Demo]({__metadata__["spaces"]})
"""

app = FastAPI(
    title="Docsifer Service API",
    description=__description__,
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS (Cross-Origin Resource Sharing)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust if needed for specific domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import and include your existing router (with /v1 endpoints)
from .router import router

app.include_router(router, prefix="/v1")


def call_convert_api(
    file_obj: Optional[bytes],
    filename: str = "",
    url: Optional[str] = None,
    cleanup: bool = True,
    openai_base_url: Optional[str] = None,
    openai_api_key: Optional[str] = None,
    openai_model: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Call the /v1/convert endpoint, returning (markdown_content, md_file_path).
    - If there's an error, the first return value is an error message (str),
      the second is an empty string.

    Args:
        file_obj (Optional[bytes]): The raw file bytes to be sent. If None, 'url' is used.
        filename (str): Name of the file (will be posted to the endpoint).
        url (str, optional): URL to be converted (used only if file_obj is None).
        cleanup (bool): Whether to enable cleanup mode for HTML files.
        openai_base_url (str, optional): Base URL for OpenAI or compatible LLM.
        openai_api_key (str, optional): API key for the LLM.
        openai_model (str, optional): Model name to use for LLM-based extraction.

    Returns:
        (str, str):
            - markdown_content (str): The conversion result in Markdown form or an error message.
            - tmp_md_path (str): The path to the temporary .md file for download.
    """
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
        # Must match the `Form(...)` fields named "openai" and "settings"
        "openai": json.dumps(openai_dict),
        "settings": json.dumps(settings_dict),
    }

    # If the user left the OpenAI fields blank, remove the `openai` key from data
    if len(openai_dict) <= 3:
        data.pop("openai")

    # Decide if we're sending a file or a URL
    files = {}
    if file_obj:
        # If file is provided, it takes priority
        files = {"file": (filename, file_obj)}
        data["url"] = ""  # ensure 'url' is empty on the form
    elif url and url.strip():
        data["url"] = url.strip()
    else:
        return ("❌ Please upload a file or provide a URL.", "")

    # Perform the POST request
    try:
        response = requests.post(DOCSIFER_API_URL, files=files, data=data, timeout=30)
    except requests.exceptions.RequestException as e:
        return (f"❌ Network Error: {str(e)}", "")

    if response.status_code != 200:
        return (f"❌ API Error {response.status_code}: {response.text}", "")

    # Parse the API response
    try:
        converted = response.json()
        # Expected structure: { "filename": "...", "markdown": "..." }
        markdown_content = converted["markdown"]
    except Exception as e:
        return (f"❌ Error parsing JSON: {str(e)}", "")

    # Write the returned Markdown to a temp .md file
    with tempfile.NamedTemporaryFile(
        mode="w+", suffix=".md", dir="/tmp", delete=False
    ) as tmp_file:
        tmp_file.write(markdown_content)
        tmp_md_path = tmp_file.name

    return (markdown_content, tmp_md_path)


def call_stats_api_df() -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Call /v1/stats endpoint to retrieve analytics data and return two DataFrames:
    - access_df: Access statistics
    - tokens_df: Token usage statistics

    Raises:
        ValueError: If the stats endpoint fails or returns invalid data.

    Returns:
        Tuple[pd.DataFrame, pd.DataFrame]:
            (access_df, tokens_df) with columns ["Model", "Total", "Daily",
            "Weekly", "Monthly", "Yearly"].
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
        """
        Helper function to transform a nested dictionary (by period, by model)
        into a tabular pandas DataFrame.
        """
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
    Create a Gradio Blocks interface that includes:
      1) 'Conversion Playground' Tab:
         - File upload OR URL-based conversion
         - Optional OpenAI configuration
         - Convert button
         - Display of conversion result as Markdown
         - Downloadable .md file
      2) 'Analytics Stats' Tab:
         - Button to fetch usage statistics
         - DataFrames for Access Stats and Token Stats

    Returns:
        Gradio Blocks instance that can be mounted into the FastAPI app.
    """
    with gr.Blocks(title="Docsifer: Convert to Markdown", theme="default") as demo:
        gr.Markdown(APP_DESCRIPTION)

        with gr.Tab("Conversion Playground"):
            gr.Markdown("### Convert your files or a URL to Markdown with Docsifer.")

            with gr.Row():
                # Left Column: File Upload, URL Input, Settings, Button
                with gr.Column():
                    file_input = gr.File(
                        label="Upload File (optional)",
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

                    url_input = gr.Textbox(
                        label="URL (optional)",
                        placeholder="Enter a URL if no file is uploaded",
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
                            "Enable to remove <style> tags or hidden elements "
                            "from `.html` files before conversion."
                        )
                        cleanup_toggle = gr.Checkbox(
                            label="Enable Cleanup",
                            value=True,
                        )

                    convert_btn = gr.Button("Convert")

                # Right Column: Conversion Result Display & Download
                with gr.Column():
                    # Display the result as Markdown
                    output_md = gr.Textbox(
                        label="Markdown Preview",
                        lines=30,
                        max_lines=50,
                        interactive=True,
                        show_copy_button=True,
                    )

                    # The user can still download the .md file
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

                        **Convert from a URL (no file)**:
                        ```bash
                        curl -X POST \\
                            "https://lamhieu-docsifer.hf.space/v1/convert" \\
                            -F "url=https://example.com/page.html" \\
                            -F "openai={\\"api_key\\":\\"sk-xxxxx\\",\\"model\\":\\"gpt-4o-mini\\",\\"base_url\\":\\"https://api.openai.com/v1\\"}" \\
                            -F "settings={\\"cleanup\\":true}"
                        ```
                        """
                    )

            # Callback function triggered by convert_btn.click
            def on_convert(file_bytes, url_str, base_url, api_key, model_id, cleanup):
                """
                Converts the uploaded file or a URL to Markdown by calling the Docsifer
                API. Returns the resulting Markdown content and path to the
                temporary .md file for download.

                Args:
                    file_bytes (bytes): The raw file content (None if not uploaded).
                    url_str (str): The URL to convert (only used if file_bytes is None).
                    base_url (str): The base URL for OpenAI or compatible LLM.
                    api_key (str): The API key for the LLM.
                    model_id (str): The model to use for the LLM.
                    cleanup (bool): Whether to enable cleanup on HTML files.

                Returns:
                    (str, str):
                        - The Markdown content or error message.
                        - The path to the temp .md file for download.
                """
                # If file is not provided, we attempt the URL approach
                if not file_bytes and not url_str:
                    return "❌ Please upload a file or provide a URL.", None

                # Create a unique temporary filename if file is present
                unique_name = f"{scuid()}.tmp" if file_bytes else ""

                # Call the convert API
                markdown, temp_md_path = call_convert_api(
                    file_obj=file_bytes,
                    filename=unique_name,
                    url=url_str,
                    openai_base_url=base_url,
                    openai_api_key=api_key,
                    openai_model=model_id,
                    cleanup=cleanup,
                )

                return markdown, temp_md_path

            # Link the on_convert function to the convert_btn
            convert_btn.click(
                fn=on_convert,
                inputs=[
                    file_input,
                    url_input,
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

            # When the button is clicked, call_stats_api_df returns two dataframes
            stats_btn.click(
                fn=call_stats_api_df,
                inputs=[],
                outputs=[access_df, tokens_df],
            )

    return demo


main_interface = create_main_interface()
mount_gradio_app(app, main_interface, path="/")


@app.on_event("startup")
async def startup_event():
    """
    Logs a startup message when the Docsifer Service is starting.
    """
    logger.info("Docsifer Service is starting up...")


@app.on_event("shutdown")
async def shutdown_event():
    """
    Logs a shutdown message when the Docsifer Service is shutting down.
    """
    logger.info("Docsifer Service is shutting down.")
