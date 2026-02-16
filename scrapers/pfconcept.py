# scrapers/pfconcept.py
"""
Scraper pentru pfconcept.com.
"""
import re
from scrapers.base_scraper import BaseScraper
from utils.helpers import clean_price
from utils.image_handler import make_absolute_url
import streamlit as st


class PFConceptScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.name = "pfconcept"
        self.base_url = "https://www.pfconcept.com"

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
            for sel in ['h1.product-name', 'h1', '.product-title h1',
                         '.product-detail h1']:
                el = soup.select_one(sel)
                if el and el.get_text(strip=True):
                    name = el.get_text(strip=True)
                    break

            # SKU - din URL
            sku = ""
            sku_match = re.search(r'(\d{6})', url)
            if sku_match:
                sku = sku_match.group(1)
            for sel in ['.product-sku', '[class*="sku"]',
                         '[class*="article"]']:
                el = soup.select_one(sel)
                if el:
                    sku = el.get_text(strip=True)
                    break

            # PREȚ
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
                         '.product-detail-description']:
                el = soup.select_one(sel)
                if el:
                    description = str(el)
                    break

            # SPECIFICAȚII
            specifications = {}
            for sel in ['.product-attributes', '.product-specifications',
                         'table', '[class*="spec"]']:
                container = soup.select_one(sel)
                if container:
                    rows = container.select('tr, .attribute, [class*="row"]')
                    for row in rows:
                        cells = row.select('td, th, span, .label, .value')
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
                '[class*="carousel"] img', 'img[class*="product"]'
            ]:
                imgs = soup.select(sel)
                if imgs:
                    for img in imgs:
                        src = (img.get('data-src') or img.get('src')
                               or img.get('data-zoom-image') or '')
                        if src and 'placeholder' not in src.lower():
                            abs_url = make_absolute_url(src, self.base_url)
                            if abs_url not in images:
                                images.append(abs_url)
                    break

            # CULORI
            colors = []
            for sel in [
                '.color-selector a', '[class*="color"] [class*="swatch"]',
                '[data-color]', '.color-options a'
            ]:
                color_els = soup.select(sel)
                for el in color_els:
                    c = (el.get('title') or el.get('aria-label')
                         or el.get_text(strip=True))
                    if c and c not in colors:
                        colors.append(c)
                if colors:
                    break

            return self._build_product(
                name=name or "Produs PF Concept",
                sku=sku,
                price=price,
                description=description,
                images=images,
                colors=colors,
                specifications=specifications,
                source_url=url,
                source_site=self.name,
                category='Rucsacuri Anti-Furt',
            )

        except Exception as e:
            st.error(f"❌ Eroare scraping PF Concept: {str(e)}")
            return None
