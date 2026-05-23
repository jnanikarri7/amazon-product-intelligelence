"""Export scored products to CSV and JSON"""

import logging
import json
from typing import List
from pathlib import Path
import pandas as pd

from .product_enrichment import ProductRecord
from .scoring import OpportunityScore

logger = logging.getLogger(__name__)


class ProductExporter:
    """Export product data to various formats"""

    def __init__(self, csv_path: Path, json_path: Path):
        self.csv_path = csv_path
        self.json_path = json_path

        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self.json_path.parent.mkdir(parents=True, exist_ok=True)

    def export(
        self,
        products: List[ProductRecord],
        scores: List[OpportunityScore],
        top_n: int = 50,
    ):
        """Export top N products to CSV and JSON"""
        if not products or not scores:
            logger.warning("No products to export")
            return

        score_map = {s.asin: s for s in scores}

        data = []
        for product in products:
            score = score_map.get(product.asin)
            if not score:
                continue

            data.append({
                "asin": product.asin,
                "title": product.title,
                "brand": product.brand,
                "category": product.category,
                "current_price": product.current_price,
                "avg_90_price": product.avg_90_price,
                "current_sales_rank": product.current_sales_rank,
                "avg_90_sales_rank": product.avg_90_sales_rank,
                "review_count": product.review_count,
                "rating": product.rating,
                "new_offer_count": product.new_offer_count,
                "amazon_in_stock": product.amazon_in_stock,
                "amazon_seller": product.amazon_seller,
                "buy_box_price": product.buy_box_price,
                "fba_available": product.fba_available,
                "total_score": score.total_score,
                "demand_score": score.demand_score,
                "competition_score": score.competition_score,
                "margin_score": score.margin_score,
                "simplicity_score": score.simplicity_score,
                "price_stability_score": score.price_stability_score,
                "flags": ",".join(score.flags) if score.flags else "",
                "amazon_url": f"https://www.amazon.com/dp/{product.asin}",
            })

        df = pd.DataFrame(data)
        df = df.sort_values("total_score", ascending=False)

        if top_n:
            df = df.head(top_n)

        self._export_csv(df)
        self._export_json(df)

        logger.info(f"Exported {len(df)} products")

    def _export_csv(self, df: pd.DataFrame):
        """Export to CSV"""
        df.to_csv(self.csv_path, index=False)
        logger.info(f"CSV exported: {self.csv_path}")

    def _export_json(self, df: pd.DataFrame):
        """Export to JSON"""
        data = df.to_dict(orient="records")

        with open(self.json_path, "w") as f:
            json.dump(data, f, indent=2)

        logger.info(f"JSON exported: {self.json_path}")

    def export_top_opportunities_from_db(
        self,
        storage,
        top_n: int = 50,
        min_score: float = 0.0,
    ):
        """Export top opportunities directly from database"""
        opportunities = storage.get_top_opportunities(limit=top_n, min_score=min_score)

        if not opportunities:
            logger.warning("No opportunities found in database")
            return

        df = pd.DataFrame(opportunities)
        df["amazon_url"] = df["asin"].apply(lambda x: f"https://www.amazon.com/dp/{x}")

        self._export_csv(df)
        self._export_json(df)

        logger.info(f"Exported {len(df)} opportunities from database")


if __name__ == "__main__":
    from .config import Config
    from .storage import ProductStorage

    logging.basicConfig(level=logging.INFO)

    config = Config()
    storage = ProductStorage(config.database_path)

    exporter = ProductExporter(config.csv_path, config.json_path)
    exporter.export_top_opportunities_from_db(storage, top_n=20)

    storage.close()
    print(f"Exported to:")
    print(f"  CSV: {config.csv_path}")
    print(f"  JSON: {config.json_path}")
