# scrapers/utteam.py
"""
Scraper pentru utteam.com.
"""
import re
from scrapers.base_scraper import BaseScraper
from utils.helpers import clean_price
from utils.image_handler import make_absolute_url
import streamlit as st


class UTTeamScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.name = "utteam"
        self.base_url = "https://utteam.com"

    def scrape(self, url: str) -> dict | None:
        try:
            soup = self.get_page(
                url,
                wait_selector='h1, .product-name, [class*="product"]',
                prefer_selenium=True
            )
            if not soup:
                return None

            name = ""
            for sel in ['h1', '.product-name', '.product-title',
                         '[class*="product"] h1']:
                el = soup.select_one(sel)
                if el and el.get_text(strip=True):
                    name = el.get_text(strip=True)
                    break

            # SKU din URL (ex: ki0888, KI0889)
            sku = ""
            sku_match = re.search(r'/product/([^?/]+)', url, re.IGNORECASE)
            if sku_match:
                sku = sku_match.group(1).upper()

            price = 0.0
            for sel in ['.product-price', '.price', '[class*="price"]']:
                el = soup.select_one(sel)
                if el:
                    price = clean_price(el.get_text(strip=True))
                    if price > 0:
                        break

            description = ""
            for sel in ['.product-description', '[class*="description"]',
                         '.description', '.product-info']:
                el = soup.select_one(sel)
                if el:
                    description = str(el)
                    break

            specifications = {}
            for sel in ['table', '.product-specifications',
                         '[class*="spec"]', '.product-attributes',
                         '.product-info-table']:
                container = soup.select_one(sel)
                if container:
                    rows = container.select('tr, li')
                    for row in rows:
                        text = row.get_text(strip=True)
                        if ':' in text:
                            parts = text.split(':', 1)
                            specifications[parts[0].strip()] = (
                                parts[1].strip()
                            )
                        else:
                            cells = row.select('td, span')
                            if len(cells) >= 2:
                                specifications[
                                    cells[0].get_text(strip=True)
                                ] = cells[1].get_text(strip=True)
                    if specifications:
                        break

            images = []
            for sel in [
                '.product-gallery img', '.product-images img',
                '[class*="gallery"] img', '.product-image img',
                'img[src*="product"]'
            ]:
                imgs = soup.select(sel)
                if imgs:
                    for img in imgs:
                        src = (img.get('data-src') or img.get('src') or '')
                        if src and 'placeholder' not in src.lower():
                            abs_url = make_absolute_url(src, self.base_url)
                            if abs_url not in images:
                                images.append(abs_url)
                    break

            colors = []
            for sel in [
                '.color-selector a', '[class*="color"]',
                '[data-color]'
            ]:
                color_els = soup.select(sel)
                for el in color_els:
                    c = (el.get('title') or el.get('data-color')
                         or el.get_text(strip=True))
                    if c and c not in colors:
                        colors.append(c)
                if colors:
                    break

            return self._build_product(
                name=name or f"Produs UT Team {sku}",
                sku=sku,
                price=price,
                description=description,
                images=images,
                colors=colors,
                specifications=specifications,
                source_url=url,
                source_site=self.name,
            )

        except Exception as e:
            st.error(f"❌ Eroare scraping UT Team: {str(e)}")
            return None
