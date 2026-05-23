"""Product enrichment from Keepa API data"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, asdict
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ProductRecord:
    """Normalized product record"""
    asin: str
    title: str
    brand: Optional[str]
    category: Optional[str]

    current_price: Optional[float]
    avg_30_price: Optional[float]
    avg_90_price: Optional[float]

    current_sales_rank: Optional[int]
    avg_30_sales_rank: Optional[float]
    avg_90_sales_rank: Optional[float]

    review_count: int
    rating: Optional[float]

    new_offer_count: int
    amazon_in_stock: bool
    amazon_seller: bool

    buy_box_price: Optional[float]
    fba_available: Optional[bool]

    price_history: Optional[List[float]] = None
    sales_rank_history: Optional[List[int]] = None

    retrieved_at: str = None

    def __post_init__(self):
        if self.retrieved_at is None:
            self.retrieved_at = datetime.utcnow().isoformat()

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return asdict(self)


class ProductEnrichment:
    """Enrich ASINs with Keepa product data"""

    def __init__(self, keepa_client):
        self.keepa = keepa_client

    def enrich_asins(
        self,
        asins: List[str],
        domain_id: int = 1,
        batch_size: int = 100,
    ) -> List[ProductRecord]:
        """
        Enrich ASINs with detailed Keepa data

        Args:
            asins: List of ASINs to enrich
            domain_id: Amazon domain
            batch_size: ASINs per batch

        Returns:
            List of ProductRecord objects
        """
        logger.info(f"Enriching {len(asins)} ASINs")

        products = self.keepa.batch_query_products(
            asins=asins,
            domain_id=domain_id,
            batch_size=batch_size,
            stats=90,
        )

        records = []
        for product in products:
            try:
                record = self._parse_product(product)
                if record:
                    records.append(record)
            except Exception as e:
                logger.warning(f"Failed to parse product {product.get('asin', 'unknown')}: {e}")

        logger.info(f"Successfully enriched {len(records)}/{len(asins)} products")
        return records

    def _parse_product(self, product: Dict[str, Any]) -> Optional[ProductRecord]:
        """
        Parse Keepa product data into ProductRecord

        Keepa data structure:
        - csv[0]: Amazon price history (cents)
        - csv[1]: Marketplace new price
        - csv[3]: Sales rank
        - stats: Contains averages (30d, 90d, 180d)
        """
        if not product or "asin" not in product:
            return None

        asin = product.get("asin")

        title = product.get("title", "").strip()
        if not title:
            logger.warning(f"Product {asin} has no title, skipping")
            return None

        brand = product.get("brand", "").strip() or None
        category = self._get_category(product)

        current_price = self._get_current_amazon_price(product)
        avg_30_price = self._get_avg_price(product, 30)
        avg_90_price = self._get_avg_price(product, 90)

        current_sales_rank = self._get_current_sales_rank(product)
        avg_30_sales_rank = self._get_avg_sales_rank(product, 30)
        avg_90_sales_rank = self._get_avg_sales_rank(product, 90)

        review_count = product.get("reviewsCount", 0) or 0
        rating = self._parse_rating(product.get("rating"))

        new_offer_count = product.get("offersCount", 0) or 0

        amazon_in_stock = self._check_amazon_in_stock(product)
        amazon_seller = self._check_amazon_seller(product)

        buy_box_price = self._get_buy_box_price(product)
        fba_available = self._check_fba_available(product)

        price_history = self._extract_price_history(product)
        sales_rank_history = self._extract_sales_rank_history(product)

        return ProductRecord(
            asin=asin,
            title=title,
            brand=brand,
            category=category,
            current_price=current_price,
            avg_30_price=avg_30_price,
            avg_90_price=avg_90_price,
            current_sales_rank=current_sales_rank,
            avg_30_sales_rank=avg_30_sales_rank,
            avg_90_sales_rank=avg_90_sales_rank,
            review_count=review_count,
            rating=rating,
            new_offer_count=new_offer_count,
            amazon_in_stock=amazon_in_stock,
            amazon_seller=amazon_seller,
            buy_box_price=buy_box_price,
            fba_available=fba_available,
            price_history=price_history,
            sales_rank_history=sales_rank_history,
        )

    def _get_category(self, product: dict) -> Optional[str]:
        """Extract primary category"""
        categories = product.get("categoryTree", [])
        if categories and len(categories) > 0:
            return categories[0].get("name", None)
        return None

    def _get_current_amazon_price(self, product: dict) -> Optional[float]:
        """Get current Amazon price in dollars"""
        csv = product.get("csv")
        if csv and len(csv) > 0 and csv[0] is not None:
            prices = csv[0]
            if prices and len(prices) >= 2:
                return prices[-1] / 100.0 if prices[-1] > 0 else None
        return None

    def _get_avg_price(self, product: dict, days: int) -> Optional[float]:
        """Get average price over last N days"""
        stats = product.get("stats", {})

        if days == 30:
            avg = stats.get("avg30", [None])[0]
        elif days == 90:
            avg = stats.get("avg90", [None])[0]
        else:
            return None

        return avg / 100.0 if avg and avg > 0 else None

    def _get_current_sales_rank(self, product: dict) -> Optional[int]:
        """Get current sales rank"""
        csv = product.get("csv")
        if csv and len(csv) > 3 and csv[3] is not None:
            ranks = csv[3]
            if ranks and len(ranks) >= 2:
                return int(ranks[-1]) if ranks[-1] > 0 else None
        return None

    def _get_avg_sales_rank(self, product: dict, days: int) -> Optional[float]:
        """Get average sales rank over last N days"""
        stats = product.get("stats", {})

        if days == 30:
            avg = stats.get("avg30", [None, None, None, None])[3]
        elif days == 90:
            avg = stats.get("avg90", [None, None, None, None])[3]
        else:
            return None

        return float(avg) if avg and avg > 0 else None

    def _parse_rating(self, rating_value) -> Optional[float]:
        """Convert Keepa rating (10x scale) to standard 5.0 scale"""
        if rating_value is None:
            return None
        try:
            return float(rating_value) / 10.0
        except (ValueError, TypeError):
            return None

    def _check_amazon_in_stock(self, product: dict) -> bool:
        """Check if Amazon is currently in stock"""
        csv = product.get("csv")
        if csv and len(csv) > 0 and csv[0] is not None:
            prices = csv[0]
            if prices and len(prices) >= 2:
                return prices[-1] > 0
        return False

    def _check_amazon_seller(self, product: dict) -> bool:
        """Check if Amazon is a seller"""
        return product.get("isAdultProduct", False) is False and self._check_amazon_in_stock(product)

    def _get_buy_box_price(self, product: dict) -> Optional[float]:
        """Get current buy box price"""
        csv = product.get("csv")
        if csv and len(csv) > 18 and csv[18] is not None:
            prices = csv[18]
            if prices and len(prices) >= 2:
                return prices[-1] / 100.0 if prices[-1] > 0 else None

        return self._get_current_amazon_price(product)

    def _check_fba_available(self, product: dict) -> Optional[bool]:
        """Check if FBA offers are available"""
        fba_fees = product.get("fbaFees")
        return fba_fees is not None and fba_fees > 0

    def _extract_price_history(self, product: dict) -> Optional[List[float]]:
        """Extract price history for last 90 days"""
        csv = product.get("csv")
        if csv and len(csv) > 0 and csv[0] is not None:
            prices = csv[0]
            if prices and len(prices) > 0:
                return [p / 100.0 for p in prices[1::2] if p > 0]
        return None

    def _extract_sales_rank_history(self, product: dict) -> Optional[List[int]]:
        """Extract sales rank history"""
        csv = product.get("csv")
        if csv and len(csv) > 3 and csv[3] is not None:
            ranks = csv[3]
            if ranks and len(ranks) > 0:
                return [int(r) for r in ranks[1::2] if r > 0]
        return None


if __name__ == "__main__":
    from .config import Config
    from .keepa_client import KeepaClient

    logging.basicConfig(level=logging.INFO)

    config = Config()
    keepa_client = KeepaClient(config.keepa_api_key)
    enrichment = ProductEnrichment(keepa_client)

    test_asins = ["B0BSHF7WHW"]
    records = enrichment.enrich_asins(test_asins)

    for record in records:
        print(f"\n{record.asin}: {record.title}")
        print(f"Price: ${record.current_price} | Rank: {record.current_sales_rank}")
        print(f"Reviews: {record.review_count} ({record.rating}★)")
