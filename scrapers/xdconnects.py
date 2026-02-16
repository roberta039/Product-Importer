# scrapers/xdconnects.py
"""
Scraper pentru xdconnects.com (Bobby, Swiss Peak, etc.)
"""
import re
import time
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper
from utils.helpers import clean_price
from utils.image_handler import make_absolute_url
import streamlit as st


class XDConnectsScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.name = "xdconnects"
        self.base_url = "https://www.xdconnects.com"

    def _login_if_needed(self):
        """Login pe xdconnects dacă avem credențiale."""
        try:
            xd_user = st.secrets.get("SOURCES", {}).get("XD_USER", "")
            xd_pass = st.secrets.get("SOURCES", {}).get("XD_PASS", "")

            if not xd_user or not xd_pass:
                return

            self._init_driver()
            if not self.driver:
                return

            self.driver.get(f"{self.base_url}/en-gb/login")
            time.sleep(3)

            # Accept cookies dacă apare
            try:
                cookie_btn = self.driver.find_element(
                    "css selector",
                    "button[id*='cookie'], button[class*='cookie'], "
                    ".accept-cookies, #accept-cookies"
                )
                cookie_btn.click()
                time.sleep(1)
            except Exception:
                pass

            # Completăm login
            try:
                email_field = self.driver.find_element(
                    "css selector",
                    "input[type='email'], input[name='email'], "
                    "input[id*='email'], input[name='username']"
                )
                email_field.clear()
                email_field.send_keys(xd_user)

                pass_field = self.driver.find_element(
                    "css selector",
                    "input[type='password'], input[name='password']"
                )
                pass_field.clear()
                pass_field.send_keys(xd_pass)

                submit_btn = self.driver.find_element(
                    "css selector",
                    "button[type='submit'], input[type='submit']"
                )
                submit_btn.click()
                time.sleep(5)

                st.info("✅ Logat pe XD Connects")
            except Exception as e:
                st.warning(f"⚠️ Login XD eșuat: {str(e)[:80]}")

        except Exception as e:
            st.warning(f"⚠️ XD login error: {str(e)[:80]}")

    def scrape(self, url: str) -> dict | None:
        """Scrape produs de pe xdconnects.com."""
        try:
            self._login_if_needed()

            soup = self.get_page(
                url,
                wait_selector='.product-detail, .product-info, '
                              '[class*="product"], h1',
                prefer_selenium=True
            )

            if not soup:
                return None

            # NUME PRODUS
            name = ""
            name_selectors = [
                'h1.product-detail-name',
                'h1.product-name',
                'h1[class*="product"]',
                '.product-detail h1',
                '.product-info h1',
                'h1',
            ]
            for sel in name_selectors:
                el = soup.select_one(sel)
                if el and el.get_text(strip=True):
                    name = el.get_text(strip=True)
                    break

            if not name:
                st.warning(f"⚠️ Nu am găsit numele produsului: {url[:60]}")
                name = "Produs XD Connects"

            # SKU
            sku = ""
            sku_selectors = [
                '.product-detail-sku',
                '.product-sku',
                '[class*="sku"]',
                '[class*="article-number"]',
                '[class*="product-id"]',
            ]
            for sel in sku_selectors:
                el = soup.select_one(sel)
                if el:
                    sku = el.get_text(strip=True)
                    break

            if not sku:
                # Extragem din URL (ex: p705.29)
                sku_match = re.search(r'([pP]\d{3}\.\d{2,3})', url)
                if sku_match:
                    sku = sku_match.group(1).upper()

            # PREȚ
            price = 0.0
            price_selectors = [
                '.product-detail-price',
                '.product-price',
                '[class*="price"]',
                '.price',
            ]
            for sel in price_selectors:
                el = soup.select_one(sel)
                if el:
                    price_text = el.get_text(strip=True)
                    price = clean_price(price_text)
                    if price > 0:
                        break

            # DESCRIERE
            description = ""
            desc_selectors = [
                '.product-detail-description',
                '.product-description',
                '[class*="description"]',
                '.product-detail-body',
                '#product-description',
            ]
            for sel in desc_selectors:
                el = soup.select_one(sel)
                if el:
                    description = str(el)
                    break

            # SPECIFICAȚII
            specifications = {}
            spec_selectors = [
                '.product-detail-properties',
                '.product-properties',
                '.product-specifications',
                'table.specifications',
                '[class*="specification"]',
                '[class*="properties"]',
            ]
            for sel in spec_selectors:
                spec_container = soup.select_one(sel)
                if spec_container:
                    rows = spec_container.select(
                        'tr, .property-row, .spec-row, '
                        'dl dt, [class*="property"]'
                    )
                    for row in rows:
                        cells = row.select('td, dt, dd, span')
                        if len(cells) >= 2:
                            key = cells[0].get_text(strip=True)
                            val = cells[1].get_text(strip=True)
                            if key and val:
                                specifications[key] = val
                    break

            # IMAGINI
            images = []
            img_selectors = [
                '.product-detail-images img',
                '.product-gallery img',
                '.product-images img',
                '[class*="gallery"] img',
                '[class*="product-image"] img',
                '.product-detail img[src*="product"]',
            ]
            for sel in img_selectors:
                imgs = soup.select(sel)
                if imgs:
                    for img in imgs:
                        src = (
                            img.get('data-src')
                            or img.get('src')
                            or img.get('data-lazy')
                            or ''
                        )
                        if src and 'placeholder' not in src.lower():
                            abs_url = make_absolute_url(src, self.base_url)
                            if abs_url not in images:
                                images.append(abs_url)
                    break

            # Dacă nu am găsit imagini cu selectori specifici
            if not images:
                all_imgs = soup.select('img')
                for img in all_imgs:
                    src = img.get('src', '') or img.get('data-src', '')
                    if src and any(
                        kw in src.lower()
                        for kw in ['product', 'media', 'image', 'upload']
                    ):
                        abs_url = make_absolute_url(src, self.base_url)
                        if (abs_url not in images
                                and 'icon' not in abs_url.lower()
                                and 'logo' not in abs_url.lower()):
                            images.append(abs_url)

            # CULORI
            colors = []
            color_selectors = [
                '.product-detail-configurator .color-option',
                '[class*="color"] [class*="option"]',
                '.color-selector a',
                '.color-picker a',
                '[data-color]',
            ]
            for sel in color_selectors:
                color_els = soup.select(sel)
                if color_els:
                    for el in color_els:
                        color_name = (
                            el.get('title')
                            or el.get('aria-label')
                            or el.get('data-color')
                            or el.get_text(strip=True)
                        )
                        if color_name and color_name not in colors:
                            colors.append(color_name)
                    break

            return self._build_product(
                name=name,
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
            st.error(f"❌ Eroare scraping XD Connects: {str(e)}")
            return None
