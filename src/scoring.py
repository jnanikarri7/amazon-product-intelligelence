"""Product opportunity scoring engine"""

import logging
from typing import Dict, Optional
import numpy as np
from dataclasses import dataclass

from .product_enrichment import ProductRecord
from .config import Config

logger = logging.getLogger(__name__)


@dataclass
class OpportunityScore:
    """Product opportunity score breakdown"""
    asin: str
    total_score: float

    demand_score: float
    competition_score: float
    margin_score: float
    simplicity_score: float
    price_stability_score: float

    demand_weight: float
    competition_weight: float
    margin_weight: float
    simplicity_weight: float
    price_stability_weight: float

    flags: list[str] = None

    def __post_init__(self):
        if self.flags is None:
            self.flags = []

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "asin": self.asin,
            "total_score": round(self.total_score, 2),
            "demand_score": round(self.demand_score, 2),
            "competition_score": round(self.competition_score, 2),
            "margin_score": round(self.margin_score, 2),
            "simplicity_score": round(self.simplicity_score, 2),
            "price_stability_score": round(self.price_stability_score, 2),
            "flags": self.flags,
        }


class ProductScorer:
    """Calculate product opportunity scores"""

    def __init__(self, config: Config):
        self.config = config
        self.weights = config.app.scoring.weights
        self.thresholds = config.app.scoring.thresholds

    def score_product(self, product: ProductRecord) -> OpportunityScore:
        """
        Calculate total opportunity score (0-100)

        Score = weighted sum of:
        - Demand (30%): Sales rank stability and velocity
        - Competition (25%): Low seller count, high review barrier
        - Margin (20%): Price point and stability
        - Simplicity (15%): Easy to source/manufacture
        - Price Stability (10%): Low volatility
        """
        demand = self._score_demand(product)
        competition = self._score_competition(product)
        margin = self._score_margin(product)
        simplicity = self._score_simplicity(product)
        price_stability = self._score_price_stability(product)

        total = (
            demand * self.weights.demand +
            competition * self.weights.competition +
            margin * self.weights.margin +
            simplicity * self.weights.simplicity +
            price_stability * self.weights.price_stability
        )

        flags = self._generate_flags(product)

        return OpportunityScore(
            asin=product.asin,
            total_score=total,
            demand_score=demand,
            competition_score=competition,
            margin_score=margin,
            simplicity_score=simplicity,
            price_stability_score=price_stability,
            demand_weight=self.weights.demand,
            competition_weight=self.weights.competition,
            margin_weight=self.weights.margin,
            simplicity_weight=self.weights.simplicity,
            price_stability_weight=self.weights.price_stability,
            flags=flags,
        )

    def _score_demand(self, product: ProductRecord) -> float:
        """
        Score demand (0-100) based on sales rank

        Lower sales rank = higher demand
        Uses 90-day average for stability
        """
        rank = product.avg_90_sales_rank or product.current_sales_rank

        if rank is None:
            return 0.0

        t = self.thresholds

        if rank <= t.sales_rank_excellent:
            return 100.0
        elif rank <= t.sales_rank_good:
            return 85.0
        elif rank <= t.sales_rank_acceptable:
            return 70.0
        else:
            decay_factor = min(1.0, (rank - t.sales_rank_acceptable) / 50000)
            return max(0.0, 70.0 * (1 - decay_factor))

    def _score_competition(self, product: ProductRecord) -> float:
        """
        Score competition (0-100) based on seller count and review barrier

        Fewer sellers + high review count = higher barrier = better opportunity
        """
        seller_count = product.new_offer_count
        review_count = product.review_count

        t = self.thresholds

        if seller_count <= t.seller_count_low:
            seller_score = 100.0
        elif seller_count <= t.seller_count_medium:
            seller_score = 70.0
        elif seller_count <= t.seller_count_high:
            seller_score = 40.0
        else:
            seller_score = max(0.0, 40.0 - (seller_count - t.seller_count_high) * 2)

        if review_count >= t.review_barrier_high:
            barrier_score = 100.0
        elif review_count >= t.review_barrier_medium:
            barrier_score = 70.0
        elif review_count >= t.review_barrier_low:
            barrier_score = 40.0
        else:
            barrier_score = max(0.0, 40.0 - (t.review_barrier_low - review_count) * 0.5)

        return (seller_score * 0.6) + (barrier_score * 0.4)

    def _score_margin(self, product: ProductRecord) -> float:
        """
        Score margin potential (0-100) based on price point

        Ideal price range: $20-$35 (good margins, not too expensive)
        """
        price = product.avg_90_price or product.current_price

        if price is None:
            return 0.0

        t = self.thresholds

        if t.price_ideal_min <= price <= t.price_ideal_max:
            return 100.0
        elif price < t.price_ideal_min:
            if price < 10:
                return 30.0
            return 30.0 + (70.0 * (price - 10) / (t.price_ideal_min - 10))
        else:
            if price > 60:
                return 40.0
            return 100.0 - (60.0 * (price - t.price_ideal_max) / (60 - t.price_ideal_max))

    def _score_simplicity(self, product: ProductRecord) -> float:
        """
        Score product simplicity (0-100)

        Uses review count as proxy:
        - Fewer reviews often means simpler products
        - Simple products easier to source/manufacture
        """
        review_count = product.review_count

        t = self.thresholds

        if review_count <= t.simple_review_max:
            return 100.0
        elif review_count <= t.moderate_review_max:
            return 70.0
        else:
            decay = min(1.0, (review_count - t.moderate_review_max) / 1000)
            return max(30.0, 70.0 * (1 - decay))

    def _score_price_stability(self, product: ProductRecord) -> float:
        """
        Score price stability (0-100) using coefficient of variation

        CV = std / mean
        Lower CV = more stable = better for planning
        """
        price_history = product.price_history

        if not price_history or len(price_history) < 5:
            return 50.0

        try:
            prices = np.array([p for p in price_history if p > 0])

            if len(prices) < 5:
                return 50.0

            mean_price = np.mean(prices)
            std_price = np.std(prices)

            if mean_price == 0:
                return 0.0

            cv = std_price / mean_price

            t = self.thresholds

            if cv <= t.stable_cv_max:
                return 100.0
            elif cv <= t.moderate_cv_max:
                return 70.0
            else:
                decay = min(1.0, (cv - t.moderate_cv_max) / 0.3)
                return max(30.0, 70.0 * (1 - decay))

        except Exception as e:
            logger.warning(f"Failed to calculate price stability for {product.asin}: {e}")
            return 50.0

    def _generate_flags(self, product: ProductRecord) -> list[str]:
        """Generate warning/opportunity flags"""
        flags = []

        if not product.amazon_in_stock:
            flags.append("AMAZON_OUT_OF_STOCK")

        if product.amazon_seller:
            flags.append("AMAZON_COMPETES")

        if product.new_offer_count == 0:
            flags.append("NO_COMPETITION")

        if product.rating and product.rating < 3.5:
            flags.append("LOW_RATING")

        if product.review_count < 10:
            flags.append("INSUFFICIENT_REVIEWS")

        if product.current_sales_rank and product.current_sales_rank > 100000:
            flags.append("LOW_DEMAND")

        if product.fba_available is False:
            flags.append("NO_FBA")

        return flags


if __name__ == "__main__":
    from .config import Config
    from .keepa_client import KeepaClient
    from .product_enrichment import ProductEnrichment

    logging.basicConfig(level=logging.INFO)

    config = Config()
    keepa_client = KeepaClient(config.keepa_api_key)
    enrichment = ProductEnrichment(keepa_client)
    scorer = ProductScorer(config)

    test_asins = ["B0BSHF7WHW"]
    records = enrichment.enrich_asins(test_asins)

    for record in records:
        score = scorer.score_product(record)
        print(f"\n{record.asin}: {record.title}")
        print(f"Total Score: {score.total_score:.1f}")
        print(f"  Demand: {score.demand_score:.1f}")
        print(f"  Competition: {score.competition_score:.1f}")
        print(f"  Margin: {score.margin_score:.1f}")
        print(f"  Simplicity: {score.simplicity_score:.1f}")
        print(f"  Price Stability: {score.price_stability_score:.1f}")
        print(f"Flags: {', '.join(score.flags) if score.flags else 'None'}")
