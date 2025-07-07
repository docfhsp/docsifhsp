import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl
import gradio as gr
import tempfile
import os

# --- FastAPI Setup ---

app = FastAPI(
    title="URL to Markdown Converter",
    description="Convert any webpage URL to Markdown with a single click.",
    version="2.0.0"
)

class URLRequest(BaseModel):
    url: HttpUrl

DOCSIFER_BACKEND = "http://localhost:7860/v1/convert"  # Change as needed

def url_to_markdown_backend(url: str) -> str:
    """Call backend to convert URL to Markdown."""
    try:
        resp = requests.post(
            DOCSIFER_BACKEND,
            data={"url": url, "settings": '{"cleanup": true}'},
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("markdown", "")
    except Exception as e:
        raise RuntimeError(f"Conversion failed: {e}")

@app.post("/convert", summary="Convert URL to Markdown")
def convert_url(request: URLRequest):
    """API endpoint to convert URL to Markdown."""
    markdown = url_to_markdown_backend(str(request.url))
    if not markdown.strip():
        raise HTTPException(status_code=422, detail="Failed to extract Markdown from URL.")
    # Optional: save to temp .md file for download
    with tempfile.NamedTemporaryFile(delete=False, suffix=".md", mode="w", encoding="utf-8") as tmp:
        tmp.write(markdown)
        md_path = tmp.name
    return {"markdown": markdown, "md_file": md_path}

# --- Gradio UI ---

def gradio_url_to_md(url):
    if not url:
        return "Please enter a valid URL.", None
    try:
        md = url_to_markdown_backend(url)
        if not md.strip():
            return "No content extracted. Try another URL.", None
        # Write to temp file for download
        with tempfile.NamedTemporaryFile(delete=False, suffix=".md", mode="w", encoding="utf-8") as tmp:
            tmp.write(md)
            file_path = tmp.name
        return md, file_path
    except Exception as e:
        return f"Error: {e}", None

with gr.Blocks(title="URL → Markdown") as demo:
    gr.Markdown("""
    # 🌐→📄 URL to Markdown  
    Paste any webpage URL. Instantly get clean Markdown for documentation, blogs, or notes!
    """)
    url_input = gr.Textbox(label="Webpage URL", placeholder="https://example.com/article")
    convert_btn = gr.Button("Convert")
    md_output = gr.Textbox(label="Markdown Output", lines=18, show_copy_button=True)
    file_output = gr.File(label="Download .md", interactive=False)
    convert_btn.click(gradio_url_to_md, inputs=[url_input], outputs=[md_output, file_output])

# Optional: Mount Gradio to FastAPI
from gradio.routes import mount_gradio_app
mount_gradio_app(app, demo, path="/")

# --- Optional: Clean up temp files (basic) ---
import atexit
import glob

def cleanup_temp_md():
    for f in glob.glob("/tmp/tmp*.md"):
        try:
            os.remove(f)
        except Exception:
            pass

atexit.register(cleanup_temp_md)