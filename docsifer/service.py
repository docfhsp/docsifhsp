import logging
import httpx
from typing import Optional, Dict, Tuple, Any
from markitdown import MarkItDown

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class URLToMarkdownService:
    """
    Service for converting a URL's HTML content to Markdown.
    """

    def __init__(self, markitdown_kwargs: Optional[dict] = None):
        """
        Initialize with a MarkItDown instance.
        """
        self.converter = MarkItDown(**(markitdown_kwargs or {}))

    async def url_to_markdown(
        self,
        url: str,
        openai_config: Optional[Dict[str, Any]] = None,
        timeout: float = 15.0
    ) -> Dict[str, str]:
        """
        Fetch a URL and convert its main content to Markdown.

        Args:
            url: The URL to fetch.
            openai_config: Optional dict for OpenAI-powered conversion.
            timeout: Timeout in seconds for HTTP requests.

        Returns:
            Dict with 'url' and 'markdown' keys.

        Raises:
            RuntimeError if fetching or conversion fails.
        """
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                html = resp.text
        except Exception as e:
            logger.error(f"Failed to fetch URL {url}: {e}")
            raise RuntimeError(f"Could not fetch URL: {url}") from e

        try:
            if openai_config and openai_config.get("api_key"):
                converter = MarkItDown(llm_client=openai_config.get("llm_client"), llm_model=openai_config.get("model"))
            else:
                converter = self.converter
            result = converter.convert(html)
            markdown = result.text_content if hasattr(result, "text_content") else str(result)
        except Exception as e:
            logger.error(f"Markdown conversion failed for {url}: {e}")
            raise RuntimeError(f"Could not convert URL to markdown: {url}") from e

        return {
            "url": url,
            "markdown": markdown
        }