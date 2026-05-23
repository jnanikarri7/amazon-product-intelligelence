"""Main entry point for Amazon Product Intelligence System"""

import logging
import sys
from pathlib import Path

from .config import Config
from .keepa_client import KeepaClient
from .product_discovery import ProductDiscovery
from .product_enrichment import ProductEnrichment
from .scoring import ProductScorer
from .storage import ProductStorage
from .export import ProductExporter


def setup_logging(config: Config):
    """Configure logging"""
    logging.basicConfig(
        level=getattr(logging, config.app.logging.level),
        format=config.app.logging.format,
    )


def print_summary(products, scores):
    """Print summary of top opportunities"""
    if not products or not scores:
        print("\nNo products found.")
        return

    score_map = {s.asin: s for s in scores}

    scored_products = []
    for product in products:
        score = score_map.get(product.asin)
        if score:
            scored_products.append((product, score))

    scored_products.sort(key=lambda x: x[1].total_score, reverse=True)

    print("\n" + "="*100)
    print("TOP 20 PRODUCT OPPORTUNITIES")
    print("="*100)
    print(f"{'Rank':<5} {'ASIN':<12} {'Score':<7} {'Title':<50} {'Price':<8} {'Rank':<10}")
    print("-"*100)

    for i, (product, score) in enumerate(scored_products[:20], 1):
        title = product.title[:47] + "..." if len(product.title) > 50 else product.title
        price = f"${product.current_price:.2f}" if product.current_price else "N/A"
        rank = f"{product.current_sales_rank:,}" if product.current_sales_rank else "N/A"

        print(f"{i:<5} {product.asin:<12} {score.total_score:<7.1f} {title:<50} {price:<8} {rank:<10}")

    print("\n" + "="*100)
    print("SCORE BREAKDOWN (Average of Top 20)")
    print("="*100)

    top_20_scores = [s for _, s in scored_products[:20]]

    avg_demand = sum(s.demand_score for s in top_20_scores) / len(top_20_scores)
    avg_competition = sum(s.competition_score for s in top_20_scores) / len(top_20_scores)
    avg_margin = sum(s.margin_score for s in top_20_scores) / len(top_20_scores)
    avg_simplicity = sum(s.simplicity_score for s in top_20_scores) / len(top_20_scores)
    avg_stability = sum(s.price_stability_score for s in top_20_scores) / len(top_20_scores)

    print(f"  Demand (30%):          {avg_demand:.1f}")
    print(f"  Competition (25%):     {avg_competition:.1f}")
    print(f"  Margin (20%):          {avg_margin:.1f}")
    print(f"  Simplicity (15%):      {avg_simplicity:.1f}")
    print(f"  Price Stability (10%): {avg_stability:.1f}")
    print()


def main():
    """Run the full product intelligence pipeline"""
    try:
        print("Initializing Amazon Product Intelligence System...")

        config = Config()
        setup_logging(config)
        logger = logging.getLogger(__name__)

        logger.info("Starting product intelligence pipeline")

        keepa_client = KeepaClient(config.keepa_api_key)
        print(f"✓ Keepa API connected (Tokens: {keepa_client.tokens_left})")

        discovery = ProductDiscovery(config, keepa_client)
        print("\nStep 1: Discovering products...")
        asins = discovery.discover_products()
        print(f"✓ Discovered {len(asins)} ASINs")

        if not asins:
            print("No products found. Try adjusting your filters in config.yaml")
            return

        enrichment = ProductEnrichment(keepa_client)
        print("\nStep 2: Enriching product data...")
        products = enrichment.enrich_asins(
            asins,
            domain_id=config.app.discovery.domain_id,
        )
        print(f"✓ Enriched {len(products)}/{len(asins)} products")

        if not products:
            print("Failed to enrich products. Check API status and try again.")
            return

        scorer = ProductScorer(config)
        print("\nStep 3: Calculating opportunity scores...")
        scores = [scorer.score_product(p) for p in products]
        print(f"✓ Scored {len(scores)} products")

        storage = ProductStorage(config.database_path)
        print("\nStep 4: Saving to database...")

        run_id = storage.save_discovery_run(
            asins_discovered=len(asins),
            asins_enriched=len(products),
            filters_used=str(config.get_discovery_filters()),
        )

        storage.save_products(products, scores)
        print(f"✓ Saved to database: {config.database_path}")

        exporter = ProductExporter(config.csv_path, config.json_path)
        print("\nStep 5: Exporting results...")
        exporter.export(products, scores, top_n=config.app.export.top_n)
        print(f"✓ CSV: {config.csv_path}")
        print(f"✓ JSON: {config.json_path}")

        print_summary(products, scores)

        storage.close()

        print(f"\n✓ Pipeline complete! Discovery run ID: {run_id}")
        print(f"\nNext steps:")
        print(f"  1. Review results in {config.csv_path}")
        print(f"  2. Manually validate top opportunities on Amazon")
        print(f"  3. Research suppliers for high-scoring products")
        print(f"  4. Calculate profitability with FBA fees")

    except KeyboardInterrupt:
        print("\n\nPipeline interrupted by user")
        sys.exit(1)

    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        print(f"\n✗ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
