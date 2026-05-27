# business-frontpages

Business frontpages dashboard powered by Playwright scraping.

Tracked sources:

- Economic Times
- Mint
- CNBC TV18
- NDTV Profit
- Zee Business

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Usage

```bash
python scrape_business_frontpages.py \
  --site all \
  --headless \
  --out_csv docs/business_frontpages.csv \
  --out_json docs/business_frontpages.json \
  --out_html docs/index.html
```

## Output

Each row contains:

- `publisher`
- `source`
- `source_url`
- `rank`
- `headline`
- `link`
- `collected_at_iso`
