"""SQLite storage for product data and scoring history"""

import logging
import sqlite3
from typing import List, Optional
from datetime import datetime
from pathlib import Path

from .product_enrichment import ProductRecord
from .scoring import OpportunityScore

logger = logging.getLogger(__name__)


class ProductStorage:
    """SQLite storage manager for product data"""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row

        self._create_tables()
        logger.info(f"Database initialized: {self.db_path}")

    def _create_tables(self):
        """Create database schema"""
        cursor = self.conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS discovery_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date TEXT NOT NULL,
                asins_discovered INTEGER NOT NULL,
                asins_enriched INTEGER NOT NULL,
                filters_used TEXT,
                notes TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS products (
                asin TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                brand TEXT,
                category TEXT,
                first_discovered TEXT NOT NULL,
                last_updated TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS product_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asin TEXT NOT NULL,
                snapshot_date TEXT NOT NULL,

                current_price REAL,
                avg_30_price REAL,
                avg_90_price REAL,

                current_sales_rank INTEGER,
                avg_30_sales_rank REAL,
                avg_90_sales_rank REAL,

                review_count INTEGER,
                rating REAL,

                new_offer_count INTEGER,
                amazon_in_stock BOOLEAN,
                amazon_seller BOOLEAN,

                buy_box_price REAL,
                fba_available BOOLEAN,

                demand_score REAL,
                competition_score REAL,
                margin_score REAL,
                simplicity_score REAL,
                price_stability_score REAL,
                total_score REAL,

                flags TEXT,

                FOREIGN KEY (asin) REFERENCES products (asin)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_metrics_asin
            ON product_metrics(asin)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_metrics_date
            ON product_metrics(snapshot_date)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_metrics_score
            ON product_metrics(total_score DESC)
        """)

        self.conn.commit()

    def save_discovery_run(
        self,
        asins_discovered: int,
        asins_enriched: int,
        filters_used: str,
        notes: Optional[str] = None,
    ) -> int:
        """Save discovery run metadata"""
        cursor = self.conn.cursor()

        cursor.execute("""
            INSERT INTO discovery_runs
            (run_date, asins_discovered, asins_enriched, filters_used, notes)
            VALUES (?, ?, ?, ?, ?)
        """, (
            datetime.utcnow().isoformat(),
            asins_discovered,
            asins_enriched,
            filters_used,
            notes,
        ))

        self.conn.commit()
        run_id = cursor.lastrowid

        logger.info(f"Saved discovery run {run_id}")
        return run_id

    def save_products(
        self,
        products: List[ProductRecord],
        scores: List[OpportunityScore],
    ):
        """Save enriched products and scores"""
        cursor = self.conn.cursor()
        now = datetime.utcnow().isoformat()

        score_map = {s.asin: s for s in scores}

        for product in products:
            cursor.execute("""
                INSERT INTO products (asin, title, brand, category, first_discovered, last_updated)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(asin) DO UPDATE SET
                    title = excluded.title,
                    brand = excluded.brand,
                    category = excluded.category,
                    last_updated = excluded.last_updated
            """, (
                product.asin,
                product.title,
                product.brand,
                product.category,
                now,
                now,
            ))

            score = score_map.get(product.asin)
            flags_str = ",".join(score.flags) if score and score.flags else None

            cursor.execute("""
                INSERT INTO product_metrics (
                    asin, snapshot_date,
                    current_price, avg_30_price, avg_90_price,
                    current_sales_rank, avg_30_sales_rank, avg_90_sales_rank,
                    review_count, rating,
                    new_offer_count, amazon_in_stock, amazon_seller,
                    buy_box_price, fba_available,
                    demand_score, competition_score, margin_score,
                    simplicity_score, price_stability_score, total_score,
                    flags
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                product.asin,
                now,
                product.current_price,
                product.avg_30_price,
                product.avg_90_price,
                product.current_sales_rank,
                product.avg_30_sales_rank,
                product.avg_90_sales_rank,
                product.review_count,
                product.rating,
                product.new_offer_count,
                product.amazon_in_stock,
                product.amazon_seller,
                product.buy_box_price,
                product.fba_available,
                score.demand_score if score else None,
                score.competition_score if score else None,
                score.margin_score if score else None,
                score.simplicity_score if score else None,
                score.price_stability_score if score else None,
                score.total_score if score else None,
                flags_str,
            ))

        self.conn.commit()
        logger.info(f"Saved {len(products)} products to database")

    def get_top_opportunities(
        self,
        limit: int = 50,
        min_score: float = 0.0,
    ) -> List[dict]:
        """Get top-scored products from latest snapshot"""
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT
                p.asin,
                p.title,
                p.brand,
                p.category,
                m.current_price,
                m.avg_90_price,
                m.current_sales_rank,
                m.avg_90_sales_rank,
                m.review_count,
                m.rating,
                m.new_offer_count,
                m.amazon_in_stock,
                m.total_score,
                m.demand_score,
                m.competition_score,
                m.margin_score,
                m.simplicity_score,
                m.price_stability_score,
                m.flags,
                m.snapshot_date
            FROM products p
            JOIN product_metrics m ON p.asin = m.asin
            WHERE m.snapshot_date = (
                SELECT MAX(snapshot_date) FROM product_metrics WHERE asin = p.asin
            )
            AND m.total_score >= ?
            ORDER BY m.total_score DESC
            LIMIT ?
        """, (min_score, limit))

        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_product_history(self, asin: str) -> List[dict]:
        """Get historical metrics for a product"""
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT *
            FROM product_metrics
            WHERE asin = ?
            ORDER BY snapshot_date DESC
        """, (asin,))

        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")


if __name__ == "__main__":
    from .config import Config

    logging.basicConfig(level=logging.INFO)

    config = Config()
    storage = ProductStorage(config.database_path)

    print(f"Database: {config.database_path}")
    print(f"Tables created successfully")

    storage.close()
