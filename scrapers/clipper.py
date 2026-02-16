# scrapers/clipper.py
"""
Scraper pentru clipperinterall.com.
"""
import re
from scrapers.base_scraper import BaseScraper
from utils.helpers import clean_price
from utils.image_handler import make_absolute_url
import streamlit as st


class ClipperScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.name = "clipper"
        self.base_url = "https://www.clipperinterall.com"

    def scrape(self, url: str) -> dict | None:
        try:
            soup = self.get_page(
                url,
                wait_selector='h1, .product-name, [class*="product"]',
                prefer_selenium=True
            )
            if not soup:
                return None

            # NUME
            name = ""
            for sel in ['h1', '.product-name', '.product-title',
                        '[class*="product"] h1']:
                el = soup.select_one(sel)
                if el and el.get_text(strip=True):
                    name = el.get_text(strip=True)
                    break

            # SKU
            sku = ""
            for sel in ['.product-sku', '[class*="sku"]',
                        '.product-code', '.article-number']:
                el = soup.select_one(sel)
                if el:
                    sku = el.get_text(strip=True)
                    break

            if not sku:
                parts = url.rstrip('/').split('/')
                if parts:
                    sku = parts[-1].upper().replace('-', '_')[:20]

            # PRET
            price = 0.0
            for sel in ['.product-price', '.price', '[class*="price"]']:
                el = soup.select_one(sel)
                if el:
                    price = clean_price(el.get_text(strip=True))
                    if price > 0:
                        break

            # DESCRIERE
            description = ""
            for sel in ['.product-description', '[class*="description"]',
                        '.description']:
                el = soup.select_one(sel)
                if el:
                    description = str(el)
                    break

            # SPECIFICATII
            specifications = {}
            for sel in ['table', '.product-specifications',
                        '[class*="spec"]']:
                container = soup.select_one(sel)
                if container:
                    rows = container.select('tr, li')
                    for row in rows:
                        cells = row.select('td, th, span')
                        if len(cells) >= 2:
                            k = cells[0].get_text(strip=True)
                            v = cells[1].get_text(strip=True)
                            if k and v:
                                specifications[k] = v
                    if specifications:
                        break

            # IMAGINI
            images = []
            for sel in [
                '.product-gallery img', '.product-images img',
                '[class*="gallery"] img', '.product-image img',
                'img[src*="product"]'
            ]:
                imgs = soup.select(sel)
                if imgs:
                    for img in imgs:
                        src = (img.get('data-src')
                               or img.get('src') or '')
                        if src and 'placeholder' not in src.lower():
                            abs_url = make_absolute_url(
                                src, self.base_url
                            )
                            if abs_url not in images:
                                images.append(abs_url)
                    break

            return self._build_product(
                name=name or "Produs Clipper",
                sku=sku,
                price=price,
                description=description,
                images=images,
                colors=[],
                specifications=specifications,
                source_url=url,
                source_site=self.name,
            )

        except Exception as e:
            st.error(f"❌ Eroare scraping Clipper: {str(e)}")
            return None
