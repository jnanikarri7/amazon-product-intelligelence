"""Keepa API client wrapper with rate limiting and retry logic"""

import logging
import time
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

import keepa
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

logger = logging.getLogger(__name__)


class KeepaClientError(Exception):
    """Base exception for Keepa client errors"""
    pass


class KeepaRateLimitError(KeepaClientError):
    """Raised when Keepa API rate limit is exceeded"""
    pass


class KeepaClient:
    """Wrapper around Keepa API with rate limiting and retry logic"""

    def __init__(self, api_key: str):
        self.api = keepa.Keepa(api_key)
        self.tokens_left = None
        self.refill_in_minutes = None
        self._last_token_check = None

        self._check_token_status()
        logger.info(f"Keepa client initialized. Tokens available: {self.tokens_left}")

    def _check_token_status(self):
        """Check current token status"""
        try:
            self.tokens_left = self.api.tokens_left
            self.refill_in_minutes = self.api.refill_in
            self._last_token_check = datetime.now()

            if self.tokens_left < 10:
                logger.warning(
                    f"Low token count: {self.tokens_left} tokens left. "
                    f"Refills in {self.refill_in_minutes} minutes."
                )
        except Exception as e:
            logger.error(f"Failed to check token status: {e}")

    def _wait_for_tokens(self, tokens_needed: int = 1):
        """Wait if insufficient tokens available"""
        if self.tokens_left is not None and self.tokens_left < tokens_needed:
            wait_minutes = self.refill_in_minutes + 1
            logger.warning(
                f"Insufficient tokens ({self.tokens_left} < {tokens_needed}). "
                f"Waiting {wait_minutes} minutes for refill..."
            )
            time.sleep(wait_minutes * 60)
            self._check_token_status()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    )
    def product_finder(
        self,
        domain_id: int,
        filters: Dict[str, str],
        max_results: int = 100,
        exclude_categories: Optional[List[int]] = None,
        root_category: Optional[int] = None,
    ) -> List[str]:
        """
        Find products using Keepa Product Finder

        Args:
            domain_id: Amazon domain (1=US, 2=UK, etc.)
            filters: Dict of Keepa filter parameters
            max_results: Maximum ASINs to return (up to 10000)
            exclude_categories: List of category IDs to exclude
            root_category: Root category ID to search within

        Returns:
            List of ASINs matching filters
        """
        logger.info(f"Running Product Finder with filters: {filters}")

        self._wait_for_tokens(tokens_needed=10)

        try:
            finder_params = {
                "domain": domain_id,
                **filters,
            }

            if exclude_categories:
                finder_params["excludeCategories"] = exclude_categories

            if root_category:
                finder_params["rootCategory"] = root_category

            asins = self.api.product_finder(finder_params)

            self._check_token_status()

            if not asins:
                logger.warning("Product Finder returned no results")
                return []

            result_asins = asins[:max_results] if len(asins) > max_results else asins
            logger.info(f"Found {len(asins)} products, returning {len(result_asins)}")

            return result_asins

        except Exception as e:
            logger.error(f"Product Finder failed: {e}")
            raise KeepaClientError(f"Product Finder failed: {e}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    )
    def query_products(
        self,
        asins: List[str],
        domain_id: int = 1,
        stats: int = 90,
        history: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Query detailed product data from Keepa

        Args:
            asins: List of ASINs to query
            domain_id: Amazon domain
            stats: Days of statistical data (0, 30, 90, 180)
            history: Include price history

        Returns:
            List of product dictionaries
        """
        if not asins:
            return []

        logger.info(f"Querying {len(asins)} products from Keepa")

        tokens_needed = len(asins)
        self._wait_for_tokens(tokens_needed=tokens_needed)

        try:
            products = self.api.query(
                asins,
                domain=domain_id,
                stats=stats,
                history=history,
            )

            self._check_token_status()

            if products is None:
                logger.warning("Keepa query returned None")
                return []

            logger.info(f"Successfully retrieved {len(products)} product records")
            return products

        except Exception as e:
            logger.error(f"Product query failed: {e}")
            raise KeepaClientError(f"Product query failed: {e}")

    def batch_query_products(
        self,
        asins: List[str],
        domain_id: int = 1,
        batch_size: int = 100,
        stats: int = 90,
    ) -> List[Dict[str, Any]]:
        """
        Query products in batches to avoid token exhaustion

        Args:
            asins: List of ASINs to query
            domain_id: Amazon domain
            batch_size: ASINs per batch
            stats: Days of statistical data

        Returns:
            Combined list of product dictionaries
        """
        all_products = []

        for i in range(0, len(asins), batch_size):
            batch = asins[i:i + batch_size]
            logger.info(f"Processing batch {i//batch_size + 1} ({len(batch)} ASINs)")

            products = self.query_products(
                batch,
                domain_id=domain_id,
                stats=stats,
            )

            all_products.extend(products)

            if i + batch_size < len(asins):
                time.sleep(1)

        return all_products

    def get_token_status(self) -> Dict[str, Any]:
        """Get current token status"""
        self._check_token_status()
        return {
            "tokens_left": self.tokens_left,
            "refill_in_minutes": self.refill_in_minutes,
            "last_checked": self._last_token_check,
        }


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv()
    api_key = os.getenv("KEEPA_API_KEY")

    if api_key:
        client = KeepaClient(api_key)
        print(f"Token status: {client.get_token_status()}")
