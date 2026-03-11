"""
HTTP utilities for making resilient API requests.

Provides retry logic with exponential backoff, timeout handling, and
proper error categorization for different HTTP status codes.
"""

import time
import logging
from typing import Optional, Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class HTTPClient:
    """
    Resilient HTTP client with retry logic and backoff strategies.
    
    Features:
    - Exponential backoff on retries
    - Timeout enforcement
    - Proper error handling for different status codes
    - Request/response logging
    
    Attributes:
        timeout_seconds (int): Request timeout in seconds
        max_retries (int): Maximum number of retry attempts
        backoff_factors (list[float]): Backoff delays in seconds after each retry
    """
    
    def __init__(
        self, 
        timeout_seconds: int = 20, 
        max_retries: int = 2,
        backoff_factors: Optional[list[float]] = None
    ):
        """
        Initialize HTTP client.
        
        Args:
            timeout_seconds: Request timeout in seconds. Applies to connection and read.
            max_retries: Number of retry attempts on transient failures.
            backoff_factors: List of delays (seconds) between retries.
                           If not provided, defaults to [1.0, 2.0].
                           Length should be >= max_retries for optimal coverage.
        
        Example:
            client = HTTPClient(timeout_seconds=20, max_retries=2, backoff_factors=[1, 2])
        """
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_factors = backoff_factors or [1.0, 2.0]
        self.session = self._create_session()
    
    def _create_session(self) -> requests.Session:
        """
        Create a requests Session with retry strategy.
        
        Returns:
            Configured requests.Session object.
        
        Note:
            The session uses urllib3.Retry for HTTP-level retry logic,
            but we handle additional retry logic in get() method for
            better control over backoff and logging.
        """
        session = requests.Session()
        
        # Create retry strategy for failed connections
        retry_strategy = Retry(
            total=self.max_retries,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"],
            backoff_factor=0.5
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session
    
    def get(
        self, 
        url: str, 
        headers: Optional[dict[str, str]] = None,
        params: Optional[dict[str, Any]] = None,
        allow_retries: bool = True
    ) -> tuple[Optional[dict | list], int, str]:
        """
        Make HTTP GET request with retry and backoff logic.
        
        Args:
            url: Full URL to request
            headers: Optional HTTP headers dict
            params: Optional query parameters dict
            allow_retries: If False, don't retry on transient errors (default: True)
        
        Returns:
            Tuple of (data, status_code, error_message):
            - data: Parsed JSON response if successful, None on error
            - status_code: HTTP status code (0 if no response)
            - error_message: Human-readable error description
        
        Retries on:
            - Connection errors (network issues)
            - Timeout errors
            - HTTP 429 (rate limit), 500-504 (server errors)
        
        Does NOT retry on:
            - 400-404, 403 (client errors - retrying won't help)
            - 401 (auth errors - credentials won't magically fix)
        
        Example:
            data, status, error = client.get(
                "https://api.example.com/matches",
                headers={"X-Auth-Token": "key"},
                params={"status": "SCHEDULED"}
            )
            if data:
                print(f"Got {len(data)} items")
            else:
                print(f"Error {status}: {error}")
        """
        attempt = 0
        last_error = None
        
        while attempt <= self.max_retries:
            try:
                logger.debug(f"GET {url} (attempt {attempt + 1}/{self.max_retries + 1})")
                
                response = self.session.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=(10, self.timeout_seconds)  # (connect, read)
                )
                
                # Success cases
                if response.status_code == 200:
                    try:
                        data = response.json()
                        logger.info(f"✓ GET {url} => 200 OK")
                        return data, 200, ""
                    except ValueError as e:
                        error_msg = f"Invalid JSON response: {str(e)[:100]}"
                        logger.error(f"✗ GET {url} => 200 (JSON error): {error_msg}")
                        return None, 200, error_msg
                
                # Client errors - don't retry
                if 400 <= response.status_code < 500:
                    if response.status_code == 404:
                        error_msg = "Not Found (404)"
                    elif response.status_code == 403:
                        error_msg = "Forbidden (403) - Check API key or permissions"
                    elif response.status_code == 401:
                        error_msg = "Unauthorized (401) - Invalid API key"
                    else:
                        error_msg = f"Client error ({response.status_code})"
                    
                    logger.warning(f"✗ GET {url} => {response.status_code}: {error_msg}")
                    return None, response.status_code, error_msg
                
                # Rate limit - retry if allowed
                if response.status_code == 429:
                    if allow_retries and attempt < self.max_retries:
                        retry_delay = self.backoff_factors[min(attempt, len(self.backoff_factors) - 1)]
                        logger.warning(
                            f"✗ GET {url} => 429 Rate Limited. "
                            f"Retry {attempt + 1}/{self.max_retries} in {retry_delay}s"
                        )
                        time.sleep(retry_delay)
                        attempt += 1
                        continue
                    else:
                        error_msg = "Rate Limited (429) - exceeded retries"
                        logger.error(f"✗ GET {url} => 429: {error_msg}")
                        return None, 429, error_msg
                
                # Server errors - retry if allowed
                if response.status_code >= 500:
                    if allow_retries and attempt < self.max_retries:
                        retry_delay = self.backoff_factors[min(attempt, len(self.backoff_factors) - 1)]
                        logger.warning(
                            f"✗ GET {url} => {response.status_code} Server Error. "
                            f"Retry {attempt + 1}/{self.max_retries} in {retry_delay}s"
                        )
                        time.sleep(retry_delay)
                        attempt += 1
                        continue
                    else:
                        error_msg = f"Server error ({response.status_code}) - max retries exceeded"
                        logger.error(f"✗ GET {url} => {response.status_code}: {error_msg}")
                        return None, response.status_code, error_msg
                
                # Other status codes
                error_msg = f"Unexpected status code {response.status_code}"
                logger.error(f"✗ GET {url} => {response.status_code}: {error_msg}")
                return None, response.status_code, error_msg
            
            except requests.exceptions.Timeout as e:
                last_error = f"Timeout after {self.timeout_seconds}s"
                if allow_retries and attempt < self.max_retries:
                    retry_delay = self.backoff_factors[min(attempt, len(self.backoff_factors) - 1)]
                    logger.warning(
                        f"✗ GET {url} => Timeout. "
                        f"Retry {attempt + 1}/{self.max_retries} in {retry_delay}s"
                    )
                    time.sleep(retry_delay)
                    attempt += 1
                    continue
                else:
                    logger.error(f"✗ GET {url} => Timeout (max retries exceeded)")
                    return None, 0, last_error
            
            except requests.exceptions.ConnectionError as e:
                last_error = f"Connection error: {str(e)[:80]}"
                if allow_retries and attempt < self.max_retries:
                    retry_delay = self.backoff_factors[min(attempt, len(self.backoff_factors) - 1)]
                    logger.warning(
                        f"✗ GET {url} => Connection Error. "
                        f"Retry {attempt + 1}/{self.max_retries} in {retry_delay}s"
                    )
                    time.sleep(retry_delay)
                    attempt += 1
                    continue
                else:
                    logger.error(f"✗ GET {url} => Connection error (max retries exceeded)")
                    return None, 0, last_error
            
            except Exception as e:
                error_msg = f"Unexpected error: {str(e)[:100]}"
                logger.error(f"✗ GET {url} => {error_msg}")
                return None, 0, error_msg
        
        # This shouldn't be reached, but just in case
        error_msg = last_error or "Unknown error"
        return None, 0, error_msg
    
    def close(self):
        """Close the session and release resources."""
        self.session.close()
        logger.debug("HTTP session closed")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
