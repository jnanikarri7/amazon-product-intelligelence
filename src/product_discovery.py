"""Product discovery using Keepa Product Finder"""

import logging
from typing import List, Set
from datetime import datetime

from .keepa_client import KeepaClient
from .config import Config

logger = logging.getLogger(__name__)


class ProductDiscovery:
    """Discover products using Keepa Product Finder"""

    def __init__(self, config: Config, keepa_client: KeepaClient):
        self.config = config
        self.keepa = keepa_client
        self.discovered_asins: Set[str] = set()

    def discover_products(self) -> List[str]:
        """
        Run product discovery using configured filters

        Returns:
            List of unique ASINs
        """
        logger.info("Starting product discovery")

        discovery_config = self.config.app.discovery
        filters = self.config.get_discovery_filters()

        try:
            asins = self.keepa.product_finder(
                domain_id=discovery_config.domain_id,
                filters=filters,
                max_results=discovery_config.max_results,
                exclude_categories=discovery_config.exclude_categories,
                root_category=discovery_config.root_category,
            )

            new_asins = [asin for asin in asins if asin not in self.discovered_asins]
            self.discovered_asins.update(new_asins)

            logger.info(
                f"Discovery complete: {len(asins)} ASINs found, "
                f"{len(new_asins)} new, {len(self.discovered_asins)} total unique"
            )

            return asins

        except Exception as e:
            logger.error(f"Product discovery failed: {e}")
            raise

    def discover_with_custom_filters(
        self,
        custom_filters: dict,
        max_results: int = 100,
    ) -> List[str]:
        """
        Discover products with custom filter overrides

        Args:
            custom_filters: Dict of Keepa filter parameters
            max_results: Maximum ASINs to return

        Returns:
            List of ASINs
        """
        logger.info(f"Running custom discovery: {custom_filters}")

        try:
            asins = self.keepa.product_finder(
                domain_id=self.config.app.discovery.domain_id,
                filters=custom_filters,
                max_results=max_results,
            )

            new_asins = [asin for asin in asins if asin not in self.discovered_asins]
            self.discovered_asins.update(new_asins)

            logger.info(f"Custom discovery found {len(asins)} ASINs")
            return asins

        except Exception as e:
            logger.error(f"Custom discovery failed: {e}")
            raise

    def discover_by_category(
        self,
        category_id: int,
        max_results: int = 100,
    ) -> List[str]:
        """
        Discover products within a specific category

        Args:
            category_id: Keepa category ID
            max_results: Maximum ASINs to return

        Returns:
            List of ASINs
        """
        logger.info(f"Discovering products in category {category_id}")

        filters = self.config.get_discovery_filters()

        try:
            asins = self.keepa.product_finder(
                domain_id=self.config.app.discovery.domain_id,
                filters=filters,
                max_results=max_results,
                root_category=category_id,
            )

            new_asins = [asin for asin in asins if asin not in self.discovered_asins]
            self.discovered_asins.update(new_asins)

            logger.info(f"Category discovery found {len(asins)} ASINs")
            return asins

        except Exception as e:
            logger.error(f"Category discovery failed: {e}")
            raise

    def get_discovery_stats(self) -> dict:
        """Get discovery statistics"""
        return {
            "total_unique_asins": len(self.discovered_asins),
            "filters_used": self.config.get_discovery_filters(),
            "domain": self.config.app.discovery.domain_id,
        }


if __name__ == "__main__":
    from .config import Config
    from .keepa_client import KeepaClient

    logging.basicConfig(level=logging.INFO)

    config = Config()
    keepa_client = KeepaClient(config.keepa_api_key)
    discovery = ProductDiscovery(config, keepa_client)

    asins = discovery.discover_products()
    print(f"Discovered {len(asins)} products")
    print(f"Stats: {discovery.get_discovery_stats()}")
