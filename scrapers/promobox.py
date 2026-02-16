# scrapers/promobox.py
"""
Scraper pentru promobox.com.
"""
import re
from scrapers.base_scraper import BaseScraper
from utils.helpers import clean_price
from utils.image_handler import make_absolute_url
import streamlit as st


class PromoboxScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.name = "promobox"
        self.base_url = "https://promobox.com"

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
                         '[class*="product"] h1', 'h2.product-name']:
                el = soup.select_one(sel)
                if el and el.get_text(strip=True):
                    name = el.get_text(strip=True)
                    break

            # SKU din URL (ex: MAGNUM, CROSS, GORDON)
            sku = ""
            sku_match = re.search(r'/products/([^?/]+)', url)
            if sku_match:
                sku = sku_match.group(1).upper()

            for sel in ['.product-sku', '[class*="sku"]', '.sku',
                         '.article-number']:
                el = soup.select_one(sel)
                if el:
                    sku_text = el.get_text(strip=True)
                    if sku_text:
                        sku = sku_text
                    break

            # PREȚ
            price = 0.0
            for sel in ['.product-price', '.price', '[class*="price"]',
                         'span.price']:
                el = soup.select_one(sel)
                if el:
                    price = clean_price(el.get_text(strip=True))
                    if price > 0:
                        break

            # DESCRIERE
            description = ""
            for sel in ['.product-description', '[class*="description"]',
                         '.product-info', '.description']:
                el = soup.select_one(sel)
                if el:
                    description = str(el)
                    break

            # SPECIFICAȚII
            specifications = {}
            for sel in ['.product-specifications', 'table',
                         '[class*="spec"]', '.properties',
                         '[class*="properties"]']:
                container = soup.select_one(sel)
                if container:
                    rows = container.select('tr, .row, li')
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
                'img[src*="product"]', 'img[src*="upload"]'
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

            if not images:
                all_imgs = soup.select('img')
                for img in all_imgs:
                    src = img.get('src', '')
                    if src and any(
                        kw in src.lower()
                        for kw in ['product', 'media', 'upload', 'image']
                    ):
                        abs_url = make_absolute_url(src, self.base_url)
                        if (abs_url not in images
                                and 'icon' not in abs_url.lower()
                                and 'logo' not in abs_url.lower()):
                            images.append(abs_url)

            # CULORI
            colors = []
            for sel in [
                '.color-selector a', '[class*="color"] option',
                '[data-color]', 'select[name*="color"] option'
            ]:
                color_els = soup.select(sel)
                for el in color_els:
                    c = (el.get('title') or el.get('data-color')
                         or el.get_text(strip=True))
                    if c and c not in colors and c != '--':
                        colors.append(c)
                if colors:
                    break

            return self._build_product(
                name=name or f"Produs Promobox {sku}",
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
            st.error(f"❌ Eroare scraping Promobox: {str(e)}")
            return None
