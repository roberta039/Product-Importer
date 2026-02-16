# scrapers/generic.py
"""
Scraper generic pentru site-uri necunoscute.
Încearcă să extragă date folosind selectori comuni.
"""
import re
from scrapers.base_scraper import BaseScraper
from utils.helpers import clean_price
from utils.image_handler import make_absolute_url
import streamlit as st


class GenericScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.name = "generic"

    def scrape(self, url: str) -> dict | None:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            base = f"{parsed.scheme}://{parsed.netloc}"

            soup = self.get_page(url, wait_selector='h1', prefer_selenium=True)
            if not soup:
                return None

            # NUME - primul h1
            name = ""
            h1 = soup.select_one('h1')
            if h1:
                name = h1.get_text(strip=True)

            if not name:
                title = soup.select_one('title')
                if title:
                    name = title.get_text(strip=True)

            # SKU
            sku = ""
            for sel in [
                '[class*="sku"]', '[class*="article"]',
                '[class*="product-code"]', '[class*="reference"]'
            ]:
                el = soup.select_one(sel)
                if el:
                    sku = el.get_text(strip=True)
                    break

            # PREȚ
            price = 0.0
            for sel in ['.price', '[class*="price"]',
                         '[itemprop="price"]']:
                el = soup.select_one(sel)
                if el:
                    price_val = el.get('content', '') or el.get_text(strip=True)
                    price = clean_price(price_val)
                    if price > 0:
                        break

            # DESCRIERE
            description = ""
            for sel in [
                '[class*="description"]', '[itemprop="description"]',
                '.product-info', '.product-details'
            ]:
                el = soup.select_one(sel)
                if el:
                    description = str(el)
                    break

            # IMAGINI
            images = []
            for img in soup.select('img'):
                src = img.get('src', '') or img.get('data-src', '')
                if src and any(
                    kw in src.lower()
                    for kw in ['product', 'media', 'upload', 'image',
                               'photo', 'pic']
                ):
                    abs_url = make_absolute_url(src, base)
                    if (abs_url not in images
                            and 'icon' not in abs_url.lower()
                            and 'logo' not in abs_url.lower()
                            and 'flag' not in abs_url.lower()):
                        images.append(abs_url)

            return self._build_product(
                name=name or "Produs Importat",
                sku=sku,
                price=price,
                description=description,
                images=images,
                colors=[],
                specifications={},
                source_url=url,
                source_site=parsed.netloc,
            )

        except Exception as e:
            st.error(f"❌ Eroare scraping generic: {str(e)}")
            return None
