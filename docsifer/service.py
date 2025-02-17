from __future__ import annotations

import asyncio
import logging
import tempfile
import magic
import mimetypes
from pathlib import Path
from typing import Optional, Dict, Tuple, Any
from scuid import scuid

import tiktoken
from pyquery import PyQuery as pq
from markitdown import MarkItDown
from openai import OpenAI

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class DocsiferService:
    """
    A service that converts local files to Markdown using MarkItDown,
    optionally with an OpenAI LLM for advanced extraction.
    Token counting uses a tiktoken encoder (heuristically with the provided model).
    """

    def __init__(self, model_name: str = "gpt-4o"):
        """
        Initialize the DocsiferService with a basic MarkItDown instance
        and a tiktoken encoder for counting tokens using the provided model.
        """
        self._basic_markitdown = MarkItDown()  # MarkItDown without LLM

        # Use the given model for token counting
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
        Initialize a MarkItDown instance configured with an OpenAI LLM if an API key is provided.

        Args:
            openai_config: A dictionary containing OpenAI configuration (e.g., api_key, model, base_url).

        Returns:
            A MarkItDown instance configured with the OpenAI client, or the basic instance if no key is provided.
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
        If the file is HTML, remove <style> tags and hidden elements to clean up the content.

        Args:
            html_file: Path to the HTML file.
        """
        try:
            content = html_file.read_text(encoding="utf-8", errors="ignore")
            d = pq(content)
            # Remove hidden elements and inline styles that hide content.
            d(":hidden").remove()
            d("[style='display:none']").remove()
            d('*[style*="display:none"]').remove()
            d("style").remove()
            cleaned_html = str(d).strip()
            html_file.write_text(cleaned_html, encoding="utf-8")
        except Exception as e:
            logger.error("HTML cleanup failed for %s: %s", html_file, e)

    def _count_tokens(self, text: str) -> int:
        """
        Count tokens in the given text using the configured tiktoken encoder.
        Falls back to a whitespace-based count if an error occurs.

        Args:
            text: The text to count tokens in.

        Returns:
            The number of tokens.
        """
        try:
            return len(self._encoder.encode(text))
        except Exception as e:
            logger.warning(
                "Token counting failed, fallback to whitespace. Error: %s", e
            )
            return len(text.split())

    def _convert_sync(
        self, source: str, openai_config: Optional[dict] = None, cleanup: bool = True
    ) -> Tuple[Dict[str, str], int]:
        """
        Synchronously convert a file at `file_path` to Markdown.
        This helper method performs blocking file I/O, MIME detection, temporary file handling,
        optional HTML cleanup, and MarkItDown conversion.

        Args:
            source: Path to the source file or URL to fetch content from.
            openai_config: Optional dictionary with OpenAI configuration.
            cleanup: Whether to perform HTML cleanup if the file is an HTML file.

        Returns:
            A tuple containing a dictionary with keys "filename" and "markdown", and the token count.
        """
        if source.startswith("http"):
            filename = f"{scuid()}.html"
        else:
            src = Path(source)
            if not src.exists():
                raise FileNotFoundError(f"File not found: {source}")

            logger.info("Converting file: %s (cleanup=%s)", source, cleanup)

            # Create a temporary directory so that MarkItDown sees the proper file extension.
            with tempfile.TemporaryDirectory() as tmpdir:
                mime_type = magic.from_file(str(src), mime=True)
                guessed_ext = mimetypes.guess_extension(mime_type) or ".tmp"
                if not mime_type:
                    logger.warning(f"Could not detect file type for: {src}")
                    new_filename = src.name
                else:
                    logger.debug(f"Detected MIME type '{mime_type}' for: {src}")
                    new_filename = f"{src.stem}{guessed_ext}"
                tmp_path = Path(tmpdir) / new_filename
                tmp_path.write_bytes(src.read_bytes())

                logger.info(
                    "Using temp file: %s, MIME type: %s, Guessed ext: %s",
                    tmp_path,
                    mime_type,
                    guessed_ext,
                )

                # Perform HTML cleanup if requested.
                if cleanup and guessed_ext.lower() in (".html", ".htm"):
                    self._maybe_cleanup_html(tmp_path)

            filename = src.name
            source = str(tmp_path)

        # Decide whether to use LLM-enhanced conversion or the basic converter.
        if openai_config and openai_config.get("api_key"):
            md_converter = self._init_markitdown_with_llm(openai_config)
        else:
            md_converter = self._basic_markitdown

        try:
            result_obj = md_converter.convert(source)
        except Exception as e:
            logger.error("MarkItDown conversion failed: %s", e)
            raise RuntimeError(f"Conversion failed for '{source}': {e}")

        # Count tokens in the resulting markdown text.
        token_count = self._count_tokens(result_obj.text_content)

        result_dict = {
            "filename": filename,
            "markdown": result_obj.text_content,
        }
        return result_dict, token_count

    async def convert_file(
        self, source: str, openai_config: Optional[dict] = None, cleanup: bool = True
    ) -> Tuple[Dict[str, str], int]:
        """
        Asynchronously convert a file at `source` to Markdown.
        This method offloads the blocking conversion process to a separate thread.

        Args:
            source: Path to the file to convert or a URL to fetch content from.
            openai_config: Optional OpenAI configuration dictionary.
            cleanup: Whether to perform HTML cleanup if applicable.

        Returns:
            A tuple containing the result dictionary (with keys "filename" and "markdown")
            and the token count.
        """
        return await asyncio.to_thread(
            self._convert_sync, source, openai_config, cleanup
        )
