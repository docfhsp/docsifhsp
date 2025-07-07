import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl
import gradio as gr
import tempfile
import os

# Backend endpoint for conversion (update as needed)
DOCSIFER_BACKEND = "http://localhost:7860/v1/convert"

app = FastAPI(
    title="URL to Markdown API",
    description="Paste any webpage URL and get clean Markdown instantly.",
    version="2.0.0"
)

class URLRequest(BaseModel):
    url: HttpUrl

def fetch_markdown_from_url(url: str) -> str:
    """Contact backend to convert URL to Markdown."""
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
    """API endpoint: URL -> Markdown (and downloadable file)."""
    markdown = fetch_markdown_from_url(str(request.url))
    if not markdown.strip():
        raise HTTPException(status_code=422, detail="No Markdown extracted from this URL.")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".md", mode="w", encoding="utf-8") as tmp:
        tmp.write(markdown)
        md_path = tmp.name
    return {"markdown": markdown, "md_file": md_path}

# Gradio Interface
def gradio_url_to_md(url):
    if not url:
        return "Please enter a valid URL.", None
    try:
        md = fetch_markdown_from_url(url)
        if not md.strip():
            return "No Markdown could be extracted. Try another URL.", None
        with tempfile.NamedTemporaryFile(delete=False, suffix=".md", mode="w", encoding="utf-8") as tmp:
            tmp.write(md)
            file_path = tmp.name
        return md, file_path
    except Exception as e:
        return f"Error: {e}", None

with gr.Blocks(title="URL → Markdown") as demo:
    gr.Markdown("""
    # 🌐→📄 URL → Markdown Converter  
    Paste a webpage URL below and get clean Markdown for documentation, blogs, or notes!
    """)
    url_input = gr.Textbox(label="Webpage URL", placeholder="https://example.com/article")
    convert_btn = gr.Button("Convert")
    md_output = gr.Textbox(label="Markdown Output", lines=18, show_copy_button=True)
    file_output = gr.File(label="Download .md", interactive=False)
    convert_btn.click(gradio_url_to_md, inputs=[url_input], outputs=[md_output, file_output])

# Optionally mount Gradio to FastAPI
from gradio.routes import mount_gradio_app
mount_gradio_app(app, demo, path="/")

# Clean up temp files on exit
import atexit, glob
def cleanup_temp_md():
    for f in glob.glob("/tmp/tmp*.md"):
        try:
            os.remove(f)
        except Exception:
            pass
atexit.register(cleanup_temp_md)