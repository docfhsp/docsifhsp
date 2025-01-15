# filename: service.py

from __future__ import annotations

import logging
import tempfile
import filetype
from pathlib import Path
from typing import Optional, Dict, Tuple, Any

import tiktoken
from pyquery import PyQuery as pq
from markitdown import MarkItDown
from openai import OpenAI


logger = logging.getLogger(__name__)


class DocsiferService:
    """
    A service that converts local files to Markdown using MarkItDown,
    optionally with an OpenAI LLM for advanced extraction.
    Token counting uses "gpt-4o" as a heuristic via tiktoken.
    """

    def __init__(self, model_name: str = "gpt-4o"):
        """
        Initialize the DocsiferService with a basic MarkItDown instance
        and a tiktoken encoder for counting tokens using "gpt-4o".
        """
        self._basic_markitdown = MarkItDown()  # MarkItDown without LLM
        # Use "gpt-4o" for token counting
        try:
            self._encoder = tiktoken.encoding_for_model(model_name)
        except Exception as e:
            logger.warning(
                "Error loading tiktoken model '%s': %s. Falling back to 'gpt-3.5-turbo-0301'.",
                model_name,
                e,
            )
            self._encoder = tiktoken.encoding_for_model("gpt-3.5-turbo-0301")

        logger.info("DocsiferService initialized with token model '%s'.", model_name)

    def _init_markitdown_with_llm(self, openai_config: Dict[str, Any]) -> MarkItDown:
        """
        If openai_config has an 'api_key', configure openai and return
        a MarkItDown instance with that OpenAI client.
        """
        api_key = openai_config.get("api_key", "")
        if not api_key:
            logger.info("No OpenAI API key provided. Using basic MarkItDown.")
            return self._basic_markitdown

        model = openai_config.get("model", "gpt-4o-mini")
        base_url = openai_config.get("base_url", "https://api.openai.com/v1")
        client = OpenAI(api_key=api_key, base_url=base_url)

        logger.info("Initialized OpenAI with base_url=%s", base_url)
        return MarkItDown(llm_client=client, llm_model=model)

    def _maybe_cleanup_html(self, html_file: Path) -> None:
        """
        If the file is HTML, remove <style> tags, optionally hidden elements, etc.
        """
        try:
            content = html_file.read_text(encoding="utf-8", errors="ignore")
            d = pq(content)
            # Remove hidden elements and styles
            d(":hidden").remove()
            d("[style='display:none']").remove()
            d('*[style*="display:none"]').remove()
            d("style").remove()
            cleaned_html = str(d)
            cleaned_html = cleaned_html.strip()
            html_file.write_text(cleaned_html, encoding="utf-8")
        except Exception as e:
            logger.error("HTML cleanup failed for %s: %s", html_file, e)

    def _count_tokens(self, text: str) -> int:
        """
        Count tokens using the configured tiktoken encoder.
        Fallback to whitespace-based counting if an error occurs.
        """
        try:
            return len(self._encoder.encode(text))
        except Exception as e:
            logger.warning(
                "Token counting failed, fallback to whitespace. Error: %s", e
            )
            return len(text.split())

    async def convert_file(
        self, file_path: str, openai_config: Optional[dict] = None, cleanup: bool = True
    ) -> Tuple[Dict[str, str], int]:
        """
        Converts a file at `file_path` to Markdown.
        - If `cleanup` is True and file is .html/.htm, does HTML cleanup.
        - If `openai_config` has a valid API key, use LLM-based MarkItDown.
        Returns ({"filename": filename, "markdown": md_string}, token_count).
        """
        src = Path(file_path)
        if not src.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        logger.info("Converting file: %s (cleanup=%s)", file_path, cleanup)

        # Use a temp directory so MarkItDown sees the real file extension
        with tempfile.TemporaryDirectory() as tmpdir:
            kind = filetype.guess(str(src))
            if kind is None:
                new_filename = src.name
            else:
                new_filename = f"{src.stem}.{kind.extension}"
            tmp_path = Path(tmpdir) / new_filename
            tmp_path.write_bytes(src.read_bytes())

            # If it's HTML and cleanup is requested
            if cleanup and tmp_path.suffix.lower() in (".html", ".htm"):
                self._maybe_cleanup_html(tmp_path)

            # Decide whether to use LLM or basic
            if openai_config and openai_config.get("api_key"):
                md_converter = self._init_markitdown_with_llm(openai_config)
            else:
                md_converter = self._basic_markitdown

            try:
                result_obj = md_converter.convert(str(tmp_path))
            except Exception as e:
                logger.error("MarkItDown conversion failed: %s", e)
                raise RuntimeError(f"Conversion failed for '{file_path}': {e}")

            # Count tokens
            token_count = self._count_tokens(result_obj.text_content)

            result_dict = {
                "filename": src.name,
                "markdown": result_obj.text_content,
            }
            return result_dict, token_count
