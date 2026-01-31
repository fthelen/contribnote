"""
OpenAI API Client Module

Async client for OpenAI Responses API with web search, rate limiting,
structured outputs, and retry logic.
"""

import asyncio
import json
import os
import random
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


class OpenAIClient:
    """Async client for OpenAI Responses API."""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-5.2",
        rate_limit_config: Optional[RateLimitConfig] = None,
        progress_callback: Optional[Callable[[str, int, int], None]] = None
    ):
        """
        Initialize the OpenAI client.
        
        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: Model to use for completions
            rate_limit_config: Rate limiting configuration
            progress_callback: Callback function(ticker, completed, total) for progress updates
        """
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key not provided. Set OPENAI_API_KEY environment variable.")
        
        self.model = model
        self.rate_limit = rate_limit_config or RateLimitConfig()
        self.progress_callback = progress_callback
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
    
    async def _make_request(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        use_web_search: bool = True,
        max_tokens: int = 350
    ) -> dict:
        """
        Make a single API request with retry logic using the Responses API.
        
        Args:
            client: httpx async client
            prompt: The prompt to send
            use_web_search: Whether to enable web search tool
            max_tokens: Maximum output tokens
            
        Returns:
            API response as dict
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Build request payload for Responses API
        # Note: When using response_format json_object, the prompt MUST mention "JSON"
        system_prompt = "You are a financial analyst assistant. Always respond with valid JSON in this exact format: {\"commentary\": \"your paragraph here\", \"citations\": [{\"url\": \"source_url\", \"title\": \"source_title\"}]}"
        
        payload = {
            "model": self.model,
            "input": [
                {"role": "developer", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "max_output_tokens": max_tokens,
            "text": {
                "format": {"type": "json_object"}
            },
            "reasoning": {"effort": "medium"},  # Standard thinking level for GPT-5.2
        }
        
        # Add web search tool if enabled
        if use_web_search:
            payload["tools"] = [{"type": "web_search"}]
        
        max_retries = 5
        for attempt in range(max_retries):
            try:
                response = await client.post(
                    f"{self.base_url}/responses",
                    headers=headers,
                    json=payload,
                    timeout=90.0
                )
                
                if response.status_code == 429:
                    # Rate limited - check for Retry-After header
                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        wait_time = float(retry_after)
                    else:
                        wait_time = self._calculate_backoff(attempt)
                    await asyncio.sleep(wait_time)
                    continue
                
                # Log error details for debugging
                if response.status_code >= 400:
                    error_body = response.text
                    print(f"API Error {response.status_code}: {error_body}")
                
                response.raise_for_status()
                return response.json()
                
            except httpx.HTTPStatusError as e:
                if attempt < max_retries - 1:
                    wait_time = self._calculate_backoff(attempt)
                    await asyncio.sleep(wait_time)
                else:
                    raise
            except httpx.RequestError as e:
                if attempt < max_retries - 1:
                    wait_time = self._calculate_backoff(attempt)
                    await asyncio.sleep(wait_time)
                else:
                    raise
        
        raise Exception("Max retries exceeded")
    
    def _parse_response(self, response: dict, ticker: str, security_name: str) -> CommentaryResult:
        """Parse the Responses API response into a CommentaryResult."""
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
            
            if not content:
                # Fallback: check for direct text in output
                for item in output:
                    if item.get("type") == "message":
                        for content_item in item.get("content", []):
                            if content_item.get("type") == "text":
                                content = content_item.get("text", "")
                                annotations = content_item.get("annotations", [])
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
            
            # Parse JSON response
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                # If not valid JSON, use raw content as commentary
                return CommentaryResult(
                    ticker=ticker,
                    security_name=security_name,
                    commentary=content,
                    citations=[],
                    success=True
                )
            
            commentary = data.get("commentary", "")
            citations_data = data.get("citations", [])
            
            # Also extract citations from annotations (url_citation type)
            for ann in annotations:
                if ann.get("type") == "url_citation":
                    citations_data.append({
                        "url": ann.get("url", ""),
                        "title": ann.get("title", "")
                    })
            
            citations = [
                Citation(
                    url=c.get("url", ""),
                    title=c.get("title", "")
                )
                for c in citations_data
                if c.get("url")
            ]
            
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
        require_citations: bool = True
    ) -> CommentaryResult:
        """
        Generate commentary for a single security.
        
        Args:
            ticker: Security ticker
            security_name: Security name
            prompt: Formatted prompt
            portcode: Portfolio code (for internal tracking)
            use_web_search: Whether to enable web search
            require_citations: Whether citations are required
            
        Returns:
            CommentaryResult with commentary and citations
        """
        request_key = self._generate_request_key(portcode, ticker) if portcode else ""
        
        async with httpx.AsyncClient() as client:
            try:
                response = await self._make_request(
                    client,
                    prompt,
                    use_web_search=use_web_search
                )
                result = self._parse_response(response, ticker, security_name)
                result.request_key = request_key
                
                # Validate citations requirement
                if require_citations and result.success and not result.citations:
                    # Don't fail, just note it
                    pass
                
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
        require_citations: bool = True
    ) -> list[CommentaryResult]:
        """
        Generate commentary for multiple securities with bounded concurrency.
        
        Args:
            requests: List of dicts with keys: ticker, security_name, prompt, portcode
            use_web_search: Whether to enable web search
            require_citations: Whether citations are required
            
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
                    require_citations=require_citations
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
