# Quick Setup Guide

## 1. Install Dependencies

```bash
cd amazon_product_intelligence
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

## 2. Configure API Key

```bash
copy .env.example .env
```

Edit `.env` and add your Keepa API key:
```
KEEPA_API_KEY=your_actual_key_here
```

## 3. Adjust Filters (Optional)

Edit `config.yaml` to customize:
- Price range
- Sales rank threshold
- Review count limits
- Scoring weights

## 4. Run Pipeline

```bash
python -m src.main
```

## Expected Output

```
Initializing Amazon Product Intelligence System...
✓ Keepa API connected (Tokens: 450)

Step 1: Discovering products...
✓ Discovered 87 ASINs

Step 2: Enriching product data...
✓ Enriched 85/87 products

Step 3: Calculating opportunity scores...
✓ Scored 85 products

Step 4: Saving to database...
✓ Saved to database: data/amazon_products.db

Step 5: Exporting results...
✓ CSV: data/processed/opportunities.csv
✓ JSON: data/processed/opportunities.json

TOP 20 PRODUCT OPPORTUNITIES
========================================
Rank  ASIN         Score   Title                      Price    Rank      
----------------------------------------
1     B08XYZ123    87.3    Kitchen Gadget Widget      $24.99   8,432    
2     B09ABC456    84.1    Home Organization Tool     $19.99   12,103   
...
```

## 5. Analyze Results

Open the Jupyter notebook:
```bash
jupyter notebook notebooks/exploratory_analysis.ipynb
```

Or review CSV directly:
```bash
data/processed/opportunities.csv
```

## Testing Individual Modules

Test Keepa connection:
```bash
python -m src.keepa_client
```

Test discovery:
```bash
python -m src.product_discovery
```

Test scoring:
```bash
python -m src.scoring
```

## Troubleshooting

**"KEEPA_API_KEY not found"**
- Ensure `.env` file exists in project root
- Check that key is on its own line without quotes

**"No products found"**
- Filters may be too restrictive
- Try increasing `sales_rank_max` in config.yaml
- Check Keepa token balance

**"Failed to enrich products"**
- Check Keepa API status
- Verify sufficient tokens remaining
- Try reducing batch size in config

**Import errors**
- Activate virtual environment: `venv\Scripts\activate`
- Reinstall dependencies: `pip install -r requirements.txt`
