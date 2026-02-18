# scrapers/xdconnects.py
"""
XD Connects Scraper (stable) - v5.1
Goals:
- Extract title, SKU (variantId), price EUR, description, specifications, images.
- Avoid wrong navigation (e.g., About page) by NOT clicking broad tabs.
- Description/specs: parse from page_source (includes hidden tabs) by locating rows like "Description".
- Colors:
  - Always extract current color (best-effort) from page text / specs.
  - Try to detect available variantIds from HTML; if found, return as variants (id list) and colors list if names found.
Notes:
- Must be compatible with scrapers/__init__.py factory: XDConnectsScraper() with no args.
- Uses BaseScraper for Selenium setup/login helpers.
"""
from __future__ import annotations

import re
import time
from urllib.parse import urlparse, parse_qs

import streamlit as st
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from scrapers.base_scraper import BaseScraper
from utils.helpers import clean_price
from utils.image_handler import make_absolute_url


_VERSION = "2026-02-18-xd-v5.1-stable"


class XDConnectsScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.name = "xdconnects"
        self.base_url = "https://www.xdconnects.com"
        self._logged_in = False

    # ----------------------------
    # Helpers
    # ----------------------------
    def _dismiss_cookie_banner(self):
        if not self.driver:
            return
        for sel in [
            "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
            "#CybotCookiebotDialogBodyButtonAccept",
            "button#onetrust-accept-btn-handler",
        ]:
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, sel)
                if btn.is_displayed():
                    self.driver.execute_script("arguments[0].click();", btn)
                    time.sleep(1.0)
                    return
            except NoSuchElementException:
                continue
            except Exception:
                continue
        # Hard remove if overlay blocks clicks
        try:
            self.driver.execute_script(
                "var s=['#CybotCookiebotDialog','#CybotCookiebotDialogBodyUnderlay',"
                "'#onetrust-banner-sdk','.onetrust-pc-dark-filter'];"
                "s.forEach(function(x){document.querySelectorAll(x).forEach(function(e){e.remove();});});"
                "document.body.style.overflow='auto';"
            )
        except Exception:
            pass

    def _login_if_needed(self):
        if self._logged_in:
            return
        try:
            xd_user = st.secrets.get("SOURCES", {}).get("XD_USER", "")
            xd_pass = st.secrets.get("SOURCES", {}).get("XD_PASS", "")
            if not xd_user or not xd_pass:
                self._logged_in = True
                return

            self._init_driver()
            if not self.driver:
                self._logged_in = True
                return

            st.info("🔐 XD: Mă conectez...")
            self.driver.get(self.base_url + "/en-gb/profile/login")
            time.sleep(4)
            self._dismiss_cookie_banner()
            time.sleep(1)

            # Email
            email_selectors = [
                "input[type='email'][name='email']",
                "input[name='email']",
                "input[type='email']",
            ]
            for sel in email_selectors:
                try:
                    for f in self.driver.find_elements(By.CSS_SELECTOR, sel):
                        if f.is_displayed() and f.is_enabled():
                            f.clear()
                            f.send_keys(xd_user)
                            raise StopIteration
                except StopIteration:
                    break
                except Exception:
                    continue

            # Password
            try:
                for f in self.driver.find_elements(By.CSS_SELECTOR, "input[type='password']"):
                    if f.is_displayed() and f.is_enabled():
                        f.clear()
                        f.send_keys(xd_pass)
                        break
            except Exception:
                pass

            self._dismiss_cookie_banner()

            # Submit
            for sel in ["form button[type='submit']", "button[type='submit']"]:
                try:
                    for btn in self.driver.find_elements(By.CSS_SELECTOR, sel):
                        if btn.is_displayed() and btn.is_enabled():
                            self.driver.execute_script("arguments[0].click();", btn)
                            raise StopIteration
                except StopIteration:
                    break
                except Exception:
                    continue

            time.sleep(5)
            self._logged_in = True
            st.success("✅ XD: Login reușit!")
        except Exception as e:
            st.warning(f"⚠️ XD login: {str(e)[:120]}")
            self._logged_in = True

    def _sku_from_url(self, url: str) -> str:
        try:
            qs = parse_qs(urlparse(url).query)
            vid = (qs.get("variantId") or [""])[0]
            if vid:
                return vid.strip()
        except Exception:
            pass
        # fallback: last token like P705.709
        m = re.search(r"\bP\d{3}\.\d{3,4}\b", url)
        return m.group(0) if m else ""

    def _parse_price_eur(self, text: str) -> float:
        """
        Accepts:
        - "Price €73.8"
        - "€ 73,80"
        - "€ 94,95"
        - "From Price €94.95"
        """
        if not text:
            return 0.0

        # Prefer "Price €"
        patterns = [
            r"Price\s*€\s*([0-9]+(?:[.,][0-9]{1,2})?)",
            r"From\s*Price\s*€\s*([0-9]+(?:[.,][0-9]{1,2})?)",
            r"€\s*([0-9]+(?:[.,][0-9]{1,2})?)",
        ]
        for pat in patterns:
            m = re.search(pat, text, flags=re.IGNORECASE)
            if m:
                raw = m.group(1).strip().replace(" ", "")
                raw = raw.replace(",", ".")
                try:
                    return float(raw)
                except Exception:
                    continue
        return 0.0

    def _extract_current_color(self, soup: BeautifulSoup, raw_text: str) -> str:
        # From specs table cell "Colour"
        for key in ["Colour", "Color", "Culoare"]:
            cell = soup.find(string=re.compile(rf"^{re.escape(key)}$", re.I))
            if cell:
                td = getattr(cell, "parent", None)
                if td and td.find_next(["td", "th"]):
                    val = td.find_next(["td", "th"]).get_text(" ", strip=True)
                    if val and len(val) <= 40:
                        return val

        # From "Item no." then next line often color
        if raw_text:
            m = re.search(r"Item no\.\s*[A-Z0-9\.]+\s*\n([A-Za-z][A-Za-z \-]{2,40})\n", raw_text)
            if m:
                return m.group(1).strip()

            # From label "Colour:" in UI
            m = re.search(r"\bColour\b\s*:\s*\n?\s*([A-Za-z][A-Za-z \-]{2,40})\b", raw_text, flags=re.I)
            if m:
                cand = m.group(1).strip()
                # Avoid known non-color words
                if cand.lower() not in {"recommended sales price", "order"}:
                    return cand

        return ""

    def _extract_desc_and_specs(self, soup: BeautifulSoup) -> tuple[str, dict]:
        """
        XD Product details often appears as a key/value table.
        We'll locate rows where first cell is 'Description' etc.
        """
        specs: dict[str, str] = {}
        desc = ""

        # Gather candidate tables (product details + any table)
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for tr in rows:
                cells = tr.find_all(["th", "td"])
                if len(cells) < 2:
                    continue
                k = cells[0].get_text(" ", strip=True)
                v = cells[1].get_text(" ", strip=True)
                if not k or not v:
                    continue
                # skip noisy pricing table rows
                if k.lower() in {"quantity", "cantitate", "printed*", "printed", "plain", "simplu", "imprimat*", "imprimat"}:
                    continue
                if "€" in v and k.lower() in {"printed*", "plain", "imprimat*", "simplu"}:
                    continue

                # Normalize keys
                k_norm = k.strip()
                v_norm = v.strip()
                if len(k_norm) > 80 or len(v_norm) > 500:
                    # still accept description which can be long
                    pass

                # Capture description
                if re.search(r"^description$|^descriere$|^beschreibung$", k_norm, flags=re.I):
                    if len(v_norm) > 30:
                        desc = v_norm
                    continue

                specs[k_norm] = v_norm

        # If description still missing, use BaseScraper heuristics on whole page
        if not desc:
            try:
                html = str(soup)
                desc_html = self.extract_description(soup, html)
                # extract_description returns HTML string
                if desc_html:
                    # Convert to plain text for downstream (or keep HTML)
                    desc = BeautifulSoup(desc_html, "html.parser").get_text(" ", strip=True)
            except Exception:
                pass

        # Filter out additional noisy keys
        noisy_keys = {
            "Quantity", "Cantitate", "Printed*", "Printed", "Plain", "Simplu", "Imprimat*", "Imprimat",
            "Recommended sales price", "Recommended Sales Price", "From",
        }
        specs = {k: v for k, v in specs.items() if k not in noisy_keys}

        return desc, specs

    def _extract_variant_ids(self, html: str) -> list[str]:
        if not html:
            return []
        vids = set()
        # variantId= in links
        for m in re.finditer(r"variantId=([A-Z0-9\.]+)", html):
            vids.add(m.group(1))
        # JSON-ish
        for m in re.finditer(r'"variantId"\s*:\s*"([A-Z0-9\.]+)"', html):
            vids.add(m.group(1))
        # Sanity: only P###.###
        vids2 = []
        for v in vids:
            if re.match(r"^P\d{3}\.\d{3,4}$", v):
                vids2.append(v)
        return sorted(vids2)

    def _extract_images(self, soup: BeautifulSoup, page_url: str) -> list[str]:
        imgs = []
        # img tags
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-lazy")
            if not src:
                continue
            if "languages/" in src or "logo" in src.lower():
                continue
            absu = make_absolute_url(src, page_url)
            if absu and absu not in imgs:
                imgs.append(absu)

        # background-image in style
        for el in soup.select("[style*='background']"):
            style = el.get("style", "")
            m = re.search(r'url\(["\']?([^"\')]+)', style)
            if m:
                absu = make_absolute_url(m.group(1), page_url)
                if absu and absu not in imgs:
                    imgs.append(absu)

        return imgs

    # ----------------------------
    # Main
    # ----------------------------
    def scrape(self, url: str) -> dict:
        # Never return None to avoid app crashes.
        product = {
            "name": "",
            "sku": self._sku_from_url(url),
            "price_eur": 0.0,
            "description": "",
            "specifications": {},
            "colors": [],
            "images": [],
            "url": url,
            "source": "xdconnects",
            "variants": [],  # list of variantIds found
            "error": "",
            "scraper_version": _VERSION,
        }

        try:
            self._login_if_needed()
            self._init_driver()
            if not self.driver:
                product["error"] = "Selenium driver not available"
                return product

            st.info(f"📦 XD v5.1: {url[:70]}...")
            self.driver.get(url)
            time.sleep(6)
            self._dismiss_cookie_banner()
            time.sleep(1)

            # Gentle scroll for lazy content
            for frac in [0.25, 0.55, 0.85, 1.0, 0.0]:
                try:
                    self.driver.execute_script(
                        "window.scrollTo(0, document.body.scrollHeight * arguments[0]);",
                        frac
                    )
                    time.sleep(0.7)
                except Exception:
                    pass

            page_source = self.driver.page_source or ""
            raw_text = ""
            try:
                raw_text = self.driver.execute_script("return document.body.innerText || ''") or ""
            except Exception:
                pass

            soup = BeautifulSoup(page_source, "html.parser")

            # Title
            h1 = soup.find("h1")
            if h1:
                product["name"] = h1.get_text(" ", strip=True)
            if not product["name"]:
                # fallback from title tag
                tt = soup.find("title")
                if tt:
                    product["name"] = tt.get_text(" ", strip=True)

            # Price EUR
            price_eur = self._parse_price_eur(raw_text)
            if price_eur <= 0:
                price_eur = self._parse_price_eur(soup.get_text("\n", strip=True))
            product["price_eur"] = float(price_eur or 0.0)

            # Description + specs
            desc, specs = self._extract_desc_and_specs(soup)
            product["description"] = desc or ""
            product["specifications"] = specs or {}

            # Current color
            current_color = self._extract_current_color(soup, raw_text)
            if current_color:
                product["colors"] = [current_color]

            # Variants (best-effort)
            vids = self._extract_variant_ids(page_source)
            product["variants"] = vids
            # If we found variantIds and current page is one variant, keep colors list as unique if we can map:
            # Try to map via simple regex: variantId then nearby color name (very best-effort).
            if vids:
                colors = set(product["colors"])
                for vid in vids[:20]:
                    # search around vid in HTML for known color labels
                    m = re.search(rf"{re.escape(vid)}(.{{0,200}})", page_source, flags=re.I | re.S)
                    if m:
                        chunk = m.group(1)
                        cm = re.search(r"(?:colour|color)\W{{0,20}}([A-Za-z][A-Za-z \-]{{2,40}})", chunk, flags=re.I)
                        if cm:
                            c = cm.group(1).strip()
                            if c.lower() not in {"recommended sales price", "order"}:
                                colors.add(c)
                product["colors"] = [c for c in colors if c]

            # Images
            product["images"] = self._extract_images(soup, url)

            return product

        except Exception as e:
            product["error"] = str(e)[:200]
            return product
