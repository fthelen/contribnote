"""
OpenAI API Client Module

Async client for OpenAI Responses API with web search, rate limiting,
structured outputs, and retry logic.
"""

import asyncio
import json
import os
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Callable
import httpx


# Response schema for structured outputs
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "commentary": {
            "type": "string",
            "description": "A single paragraph explaining the security's recent performance"
        },
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "title": {"type": "string"}
                },
                "required": ["url"]
            },
            "description": "List of source citations"
        }
    },
    "required": ["commentary"],
    "additionalProperties": False
}


@dataclass
class Citation:
    """A single citation from the API response."""
    url: str
    title: str = ""


@dataclass
class CommentaryResult:
    """Result of a commentary generation request."""
    ticker: str
    security_name: str
    commentary: str
    citations: list[Citation]
    success: bool = True
    error_message: str = ""
    request_key: str = ""


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    max_concurrent: int = 20
    initial_backoff: float = 1.0
    max_backoff: float = 60.0
    jitter_factor: float = 0.2


# Default developer prompt for the LLM
DEFAULT_DEVELOPER_PROMPT = (
    "Write a single, concise paragraph explaining the recent performance drivers "
    "for the requested security. Focus on material news, earnings, sector trends, "
    "or market events. Present only factual information and cite your sources."
)


class OpenAIClient:
    """Async client for OpenAI Responses API."""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-5.2",
        rate_limit_config: Optional[RateLimitConfig] = None,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
        developer_prompt: Optional[str] = None
    ):
        """
        Initialize the OpenAI client.
        
        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: Model to use for completions
            rate_limit_config: Rate limiting configuration
            progress_callback: Callback function(ticker, completed, total) for progress updates
            developer_prompt: System prompt for the LLM (defaults to DEFAULT_DEVELOPER_PROMPT)
        """
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key not provided. Set OPENAI_API_KEY environment variable.")
        
        self.model = model
        self.rate_limit = rate_limit_config or RateLimitConfig()
        self.progress_callback = progress_callback
        self.developer_prompt = developer_prompt or DEFAULT_DEVELOPER_PROMPT
        self.base_url = "https://api.openai.com/v1"
        
        # Request tracking (for PII protection)
        self._key_mapping: dict[str, str] = {}  # API key -> internal key (PORTCODE|TICKER)
    
    def _generate_request_key(self, portcode: str, ticker: str) -> str:
        """Generate an obfuscated API key for a request."""
        internal_key = f"{portcode}|{ticker}"
        api_key = str(uuid.uuid4())
        self._key_mapping[api_key] = internal_key
        return api_key
    
    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate backoff time with jitter."""
        backoff = min(
            self.rate_limit.initial_backoff * (2 ** attempt),
            self.rate_limit.max_backoff
        )
        jitter = backoff * self.rate_limit.jitter_factor
        return backoff + random.uniform(-jitter, jitter)
    
    def _clean_inline_citations(self, text: str, url_to_footnote: dict[str, int]) -> str:
        """
        Clean inline citation URLs from text and replace with footnote markers.
        
        Handles patterns like:
        - (([1](https://...)))  -> [1]
        - ([1](https://...))    -> [1]
        - ((domain](https://...))
        - ([domain](https://...))
        - [text](https://...)
        - ((https://...))
        """
        import re
        
        # Replace markdown-style links [text](url) with [N] footnote
        def replace_markdown_link(match):
            url = match.group(2)
            # Find the footnote number for this URL
            for stored_url, num in url_to_footnote.items():
                if stored_url in url or url in stored_url:
                    return f"[{num}]"
            # URL not in our list, just remove the link formatting
            return match.group(1)
        
        # Pattern for markdown links: [text](url)
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', replace_markdown_link, text)
        
        # Remove parentheses around footnote citations: ([N]) -> [N] or (([N])) -> [N]
        text = re.sub(r'\(\s*(\[[0-9]+\])\s*\)', r'\1', text)
        
        # Remove double parentheses around remaining URLs: ((url))
        text = re.sub(r'\(\(https?://[^)]+\)\)', '', text)
        
        # Remove any remaining bare URLs in parentheses: (https://...)
        text = re.sub(r'\(https?://[^)]+\)', '', text)
        
        # Clean up any double spaces left behind
        text = re.sub(r'  +', ' ', text)
        
        # Clean up space before punctuation
        text = re.sub(r' ([.,;:!?])', r'\1', text)
        
        return text.strip()

    async def _poll_response_status(
        self,
        client: httpx.AsyncClient,
        response_id: str,
        headers: dict,
        max_wait: float,
        poll_interval: float = 2.0
    ) -> dict:
        """
        Poll the Responses API for completion status.

        Args:
            client: httpx async client
            response_id: Response ID returned by the API
            headers: Request headers
            max_wait: Maximum total wait time in seconds
            poll_interval: Seconds between status checks

        Returns:
            Final API response as dict
        """
        start = time.monotonic()
        while True:
            elapsed = time.monotonic() - start
            if elapsed > max_wait:
                raise httpx.TimeoutException(
                    f"Polling timeout after {max_wait:.1f}s for response {response_id}"
                )

            status_response = await client.get(
                f"{self.base_url}/responses/{response_id}",
                headers=headers,
                timeout=30.0
            )
            status_response.raise_for_status()
            data = status_response.json()
            status = data.get("status", "")

            if status in {"completed", "succeeded"}:
                return data
            if status in {"failed", "cancelled", "expired"}:
                return data

            await asyncio.sleep(poll_interval)
    
    async def _make_request(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        use_web_search: bool = True,
        preferred_domains: list[str] | None = None,
        thinking_level: str = "medium"
    ) -> dict:
        """
        Make a single API request with retry logic using the Responses API.
        
        Args:
            client: httpx async client
            prompt: The prompt to send
            use_web_search: Whether to enable web search tool
            preferred_domains: Optional list of domains to prioritize for web search
            thinking_level: Reasoning effort level ("low", "medium", "high")
            
        Returns:
            API response as dict
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Build request payload for Responses API
        # Note: Web search cannot be used with JSON mode, so we use plain text
        # and extract citations from url_citation annotations
        payload = {
            "model": self.model,
            "input": [
                {"role": "developer", "content": self.developer_prompt},
                {"role": "user", "content": prompt}
            ],
            "reasoning": {"effort": thinking_level},  # Configurable thinking level
        }
        
        # Add web search tool if enabled
        # Note: Web search CANNOT be combined with JSON mode (documented limitation)
        if use_web_search:
            web_search_config = {"type": "web_search"}
            # Add domain filtering if preferred domains are specified
            if preferred_domains:
                web_search_config["search_context_size"] = "medium"
            payload["tools"] = [web_search_config]
        
        # Determine timeout based on thinking level
        # High reasoning can take 2-5 minutes, medium 1-2 minutes, low <1 minute
        timeout_map = {
            "low": 120.0,      # 2 minutes
            "medium": 300.0,   # 5 minutes
            "high": 600.0      # 10 minutes
        }
        timeout = timeout_map.get(thinking_level, 300.0)
        
        max_retries = 5
        for attempt in range(max_retries):
            try:
                response = await client.post(
                    f"{self.base_url}/responses",
                    headers=headers,
                    json=payload,
                    timeout=timeout
                )
                
                if response.status_code == 429:
                    # Rate limited - check for Retry-After header
                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        wait_time = float(retry_after)
                    else:
                        wait_time = self._calculate_backoff(attempt)
                    print(f"Rate limited (429). Waiting {wait_time:.1f}s before retry...")
                    await asyncio.sleep(wait_time)
                    continue
                
                # Log error details for debugging
                if response.status_code >= 400:
                    error_body = response.text
                    print(f"API Error {response.status_code}: {error_body}")
                
                response.raise_for_status()
                data = response.json()
                status = data.get("status", "")
                response_id = data.get("id", "")

                # If the response is not yet completed but includes an id, poll for completion
                if response_id and status in {"queued", "in_progress", "running"}:
                    return await self._poll_response_status(
                        client=client,
                        response_id=response_id,
                        headers=headers,
                        max_wait=timeout
                    )

                return data
                
            except httpx.TimeoutException as e:
                # For timeout errors, don't retry - the request is likely still processing
                print(f"Request timeout after {timeout}s. The request may still be processing on the server.")
                raise
            except httpx.HTTPStatusError as e:
                if attempt < max_retries - 1:
                    wait_time = self._calculate_backoff(attempt)
                    print(f"HTTP error {e.response.status_code}. Retrying in {wait_time:.1f}s...")
                    await asyncio.sleep(wait_time)
                else:
                    raise
            except httpx.RequestError as e:
                # Network errors (connection failures, etc.)
                if attempt < max_retries - 1:
                    wait_time = self._calculate_backoff(attempt)
                    print(f"Network error: {e}. Retrying in {wait_time:.1f}s...")
                    await asyncio.sleep(wait_time)
                else:
                    raise
        
        raise Exception("Max retries exceeded")
    
    def _parse_response(self, response: dict, ticker: str, security_name: str) -> CommentaryResult:
        """
        Parse the Responses API response into a CommentaryResult.
        
        Since web search cannot be combined with JSON mode, we expect plain text
        commentary and extract citations from url_citation annotations.
        """
        try:
            # Responses API returns output array with message objects
            output = response.get("output", [])
            
            # Find the message with text content
            content = ""
            annotations = []
            
            for item in output:
                if item.get("type") == "message":
                    for content_item in item.get("content", []):
                        if content_item.get("type") == "output_text":
                            content = content_item.get("text", "")
                            annotations = content_item.get("annotations", [])
                            break
                    if content:
                        break
            
            if not content:
                # Fallback: check for direct text in output
                for item in output:
                    if item.get("type") == "message":
                        for content_item in item.get("content", []):
                            if content_item.get("type") == "text":
                                content = content_item.get("text", "")
                                annotations = content_item.get("annotations", [])
                                break
                        if content:
                            break
            
            if not content:
                return CommentaryResult(
                    ticker=ticker,
                    security_name=security_name,
                    commentary="",
                    citations=[],
                    success=False,
                    error_message=f"No content in response: {response}"
                )
            
            # Extract citations from url_citation annotations
            # These are provided by the web search tool
            # Sort by start_index to maintain order of appearance
            url_annotations = [
                ann for ann in annotations 
                if ann.get("type") == "url_citation"
            ]
            url_annotations.sort(key=lambda x: x.get("start_index", 0))
            
            citations = []
            seen_urls = set()
            url_to_footnote = {}  # Map URL to footnote number
            
            for ann in url_annotations:
                url = ann.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    footnote_num = len(citations) + 1
                    url_to_footnote[url] = footnote_num
                    citations.append(Citation(
                        url=url,
                        title=ann.get("title", "")
                    ))
            
            # Clean up inline citation URLs from commentary text
            # Replace patterns like ((domain](url)) or ([domain](url)) with footnote [N]
            commentary = content.strip()
            commentary = self._clean_inline_citations(commentary, url_to_footnote)
            
            if not commentary:
                return CommentaryResult(
                    ticker=ticker,
                    security_name=security_name,
                    commentary="",
                    citations=[],
                    success=False,
                    error_message="Empty commentary in response"
                )
            
            return CommentaryResult(
                ticker=ticker,
                security_name=security_name,
                commentary=commentary,
                citations=citations,
                success=True
            )
            
        except Exception as e:
            return CommentaryResult(
                ticker=ticker,
                security_name=security_name,
                commentary="",
                citations=[],
                success=False,
                error_message=f"Failed to parse response: {str(e)}"
            )
    
    async def generate_commentary(
        self,
        ticker: str,
        security_name: str,
        prompt: str,
        portcode: str = "",
        use_web_search: bool = True,
        thinking_level: str = "medium"
    ) -> CommentaryResult:
        """
        Generate commentary for a single security.
        
        Args:
            ticker: Security ticker
            security_name: Security name
            prompt: Formatted prompt
            portcode: Portfolio code (for internal tracking)
            use_web_search: Whether to enable web search
            thinking_level: Reasoning effort level ("low", "medium", "high")
            
        Returns:
            CommentaryResult with commentary and citations
        """
        request_key = self._generate_request_key(portcode, ticker) if portcode else ""
        
        async with httpx.AsyncClient() as client:
            try:
                response = await self._make_request(
                    client,
                    prompt,
                    use_web_search=use_web_search,
                    thinking_level=thinking_level
                )
                result = self._parse_response(response, ticker, security_name)
                result.request_key = request_key
                
                # Validate citations are present
                if result.success and not result.citations:
                    result.success = False
                    result.error_message = "No citations found in response (citations are required)"
                
                return result
                
            except Exception as e:
                return CommentaryResult(
                    ticker=ticker,
                    security_name=security_name,
                    commentary="",
                    citations=[],
                    success=False,
                    error_message=f"API request failed: {str(e)}",
                    request_key=request_key
                )
    
    async def generate_commentary_batch(
        self,
        requests: list[dict],
        use_web_search: bool = True,
        thinking_level: str = "medium"
    ) -> list[CommentaryResult]:
        """
        Generate commentary for multiple securities with bounded concurrency.
        
        Args:
            requests: List of dicts with keys: ticker, security_name, prompt, portcode
            use_web_search: Whether to enable web search
            thinking_level: Reasoning effort level ("low", "medium", "high")
            
        Returns:
            List of CommentaryResult objects
        """
        semaphore = asyncio.Semaphore(self.rate_limit.max_concurrent)
        results = []
        completed = 0
        total = len(requests)
        
        async def process_with_semaphore(req: dict, index: int) -> CommentaryResult:
            nonlocal completed
            async with semaphore:
                result = await self.generate_commentary(
                    ticker=req["ticker"],
                    security_name=req["security_name"],
                    prompt=req["prompt"],
                    portcode=req.get("portcode", ""),
                    use_web_search=use_web_search,
                    thinking_level=thinking_level
                )
                completed += 1
                if self.progress_callback:
                    self.progress_callback(req["ticker"], completed, total)
                return result
        
        async with httpx.AsyncClient() as client:
            tasks = [
                process_with_semaphore(req, i)
                for i, req in enumerate(requests)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Convert any exceptions to error results
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                req = requests[i]
                final_results.append(CommentaryResult(
                    ticker=req["ticker"],
                    security_name=req["security_name"],
                    commentary="",
                    citations=[],
                    success=False,
                    error_message=str(result)
                ))
            else:
                final_results.append(result)
        
        return final_results
