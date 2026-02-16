# scrapers/psi.py
"""
Scraper pentru psiproductfinder.de.
"""
import re
import time
from scrapers.base_scraper import BaseScraper
from utils.helpers import clean_price
from utils.image_handler import make_absolute_url
import streamlit as st


class PSIScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.name = "psi"
        self.base_url = "https://psiproductfinder.de"

    def _login_if_needed(self):
        """Login pe PSI dacă avem credențiale."""
        try:
            psi_user = st.secrets.get("SOURCES", {}).get("PSI_USER", "")
            psi_pass = st.secrets.get("SOURCES", {}).get("PSI_PASS", "")

            if not psi_user or not psi_pass:
                return

            self._init_driver()
            if not self.driver:
                return

            self.driver.get(f"{self.base_url}/login")
            time.sleep(3)

            try:
                email_field = self.driver.find_element(
                    "css selector",
                    "input[type='email'], input[name='email'], "
                    "input[id*='email'], input[name='username'], "
                    "input[type='text']"
                )
                email_field.clear()
                email_field.send_keys(psi_user)

                pass_field = self.driver.find_element(
                    "css selector",
                    "input[type='password']"
                )
                pass_field.clear()
                pass_field.send_keys(psi_pass)

                submit_btn = self.driver.find_element(
                    "css selector",
                    "button[type='submit'], input[type='submit']"
                )
                submit_btn.click()
                time.sleep(5)
                st.info("✅ Logat pe PSI Product Finder")
            except Exception as e:
                st.warning(f"⚠️ Login PSI eșuat: {str(e)[:80]}")

        except Exception:
            pass

    def scrape(self, url: str) -> dict | None:
        try:
            self._login_if_needed()

            soup = self.get_page(
                url,
                wait_selector='h1, .product-name, [class*="product"]',
                prefer_selenium=True
            )
            if not soup:
                return None

            name = ""
            for sel in ['h1', '.product-name', '.product-title',
                         '[class*="product-detail"] h1',
                         '[class*="product"] h1']:
                el = soup.select_one(sel)
                if el and el.get_text(strip=True):
                    name = el.get_text(strip=True)
                    break

            sku = ""
            # Din URL: p-ae08d17a-fahrradschloss...
            sku_match = re.search(r'/p-([a-f0-9]+)-', url)
            if sku_match:
                sku = f"PSI-{sku_match.group(1).upper()[:8]}"

            for sel in ['.product-sku', '[class*="sku"]',
                         '.article-number', '[class*="article"]']:
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
                         '.description']:
                el = soup.select_one(sel)
                if el:
                    description = str(el)
                    break

            specifications = {}
            for sel in ['table', '.product-specifications',
                         '[class*="spec"]', '.product-attributes']:
                container = soup.select_one(sel)
                if container:
                    rows = container.select('tr, li, dl')
                    for row in rows:
                        cells = row.select('td, th, dt, dd, span')
                        if len(cells) >= 2:
                            k = cells[0].get_text(strip=True)
                            v = cells[1].get_text(strip=True)
                            if k and v:
                                specifications[k] = v
                    if specifications:
                        break

            images = []
            for sel in [
                '.product-gallery img', '.product-images img',
                '[class*="gallery"] img', '.product-image img',
                'img[src*="product"]', 'img[src*="media"]'
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

            return self._build_product(
                name=name or f"Produs PSI {sku}",
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
            st.error(f"❌ Eroare scraping PSI: {str(e)}")
            return None
