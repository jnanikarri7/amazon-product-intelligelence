# Amazon Product Intelligence System

Production-grade Amazon product opportunity discovery system using Keepa API.

## Features

- Automated product discovery via Keepa Product Finder
- ASIN enrichment with pricing, sales rank, reviews, and competition data
- Multi-factor opportunity scoring (0-100)
- SQLite storage with full history tracking
- CSV/JSON export
- Rate limiting and retry logic
- Clean logging and error handling

## Installation

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

1. Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

2. Add your Keepa API key to `.env`:
```
KEEPA_API_KEY=your_key_here
```

3. Adjust filters and scoring weights in `config.yaml`

## Usage

Run the full pipeline:
```bash
python -m src.main
```

Results are saved to:
- `data/processed/opportunities.csv`
- `data/processed/opportunities.json`
- `data/amazon_products.db` (SQLite)

## Project Structure

```
amazon_product_intelligence/
├── src/
│   ├── config.py              # Configuration management
│   ├── keepa_client.py        # Keepa API wrapper
│   ├── product_discovery.py   # Product finder logic
│   ├── product_enrichment.py  # Data normalization
│   ├── scoring.py             # Opportunity scoring engine
│   ├── storage.py             # SQLite persistence
│   ├── export.py              # CSV/JSON export
│   └── main.py                # CLI entry point
├── data/
│   ├── raw/                   # Raw Keepa responses
│   ├── processed/             # Scored results
│   └── amazon_products.db     # SQLite database
├── notebooks/
│   └── exploratory_analysis.ipynb
├── config.yaml
├── .env.example
└── requirements.txt
```

## Scoring Model

Opportunity score (0-100) based on weighted factors:

| Factor | Weight | Description |
|--------|--------|-------------|
| Demand | 30% | Sales rank stability and velocity |
| Competition | 25% | Low seller count, high review barrier |
| Margin | 20% | Price point and stability |
| Simplicity | 15% | Easy to source/manufacture |
| Price Stability | 10% | Low volatility |

## Future Enhancements

- Claude API integration for review sentiment analysis
- AI-powered niche discovery
- Streamlit dashboard
- Automated supplier research
- Profit calculator with FBA fees
- Trend detection (seasonal, growth)

## Compliance

- Uses official Keepa API only
- No Amazon scraping violations
- Rate limiting respected
- Terms of service compliant

## License

MIT
