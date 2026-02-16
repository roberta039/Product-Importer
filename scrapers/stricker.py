# scrapers/stricker.py
"""
Scraper pentru stricker-europe.com.
"""
import re
from scrapers.base_scraper import BaseScraper
from utils.helpers import clean_price
from utils.image_handler import make_absolute_url
import streamlit as st


class StrickerScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.name = "stricker"
        self.base_url = "https://www.stricker-europe.com"

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
                         '.product-detail h1']:
                el = soup.select_one(sel)
                if el and el.get_text(strip=True):
                    name = el.get_text(strip=True)
                    break

            # SKU din URL (ex: 92190)
            sku = ""
            sku_match = re.search(r'/(\d{5,})/', url)
            if sku_match:
                sku = sku_match.group(1)

            for sel in ['.product-sku', '[class*="sku"]',
                         '.reference', '[class*="reference"]']:
                el = soup.select_one(sel)
                if el:
                    sku_text = el.get_text(strip=True)
                    if sku_text:
                        sku = sku_text
                    break

            price = 0.0
            for sel in ['.product-price', '.price', '[class*="price"]']:
                el = soup.select_one(sel)
                if el:
                    price = clean_price(el.get_text(strip=True))
                    if price > 0:
                        break

            description = ""
            for sel in ['.product-description', '[class*="description"]',
                         '.description', '#product-description']:
                el = soup.select_one(sel)
                if el:
                    description = str(el)
                    break

            specifications = {}
            for sel in ['table', '.product-specifications',
                         '[class*="spec"]', '.features',
                         '.product-features']:
                container = soup.select_one(sel)
                if container:
                    rows = container.select('tr, li, .feature')
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
                '.product-cover img', 'img[src*="product"]'
            ]:
                imgs = soup.select(sel)
                if imgs:
                    for img in imgs:
                        src = (img.get('data-src') or img.get('src')
                               or img.get('data-image-large-src') or '')
                        if src and 'placeholder' not in src.lower():
                            abs_url = make_absolute_url(src, self.base_url)
                            if abs_url not in images:
                                images.append(abs_url)
                    break

            colors = []
            for sel in [
                '.color-selector a', '[class*="color"]',
                '[data-color]', '.product-variants .color'
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
                name=name or f"Produs Stricker {sku}",
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
            st.error(f"❌ Eroare scraping Stricker: {str(e)}")
            return None
