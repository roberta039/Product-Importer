# scrapers/xdconnects.py
# VERSIUNE 5.0.2 - compatibil BaseScraper (fara get_driver in Base),
# fix pret EUR cu 1-2 zecimale, descriere/specs stabile, culoare curenta

import re
import time
from bs4 import BeautifulSoup
import streamlit as st
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from scrapers.base_scraper import BaseScraper
from utils.helpers import clean_price
from utils.image_handler import make_absolute_url


class XDConnectsScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.name = "xdconnects"
        self.base_url = "https://www.xdconnects.com"
        self._logged_in = False

    # --- compat helper (unele versiuni de cod apeleaza get_driver) ---
    def get_driver(self):
        self._init_driver()
        return self.driver

    def _dismiss_cookie_banner(self):
        if not self.driver:
            return
        for sel in [
            "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
            "#CybotCookiebotDialogBodyButtonAccept",
        ]:
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, sel)
                if btn.is_displayed():
                    self.driver.execute_script("arguments[0].click();", btn)
                    time.sleep(1.5)
                    return
            except NoSuchElementException:
                continue
            except Exception:
                continue
        # fallback: elimina overlay
        try:
            self.driver.execute_script(
                "var s=['#CybotCookiebotDialog','#CybotCookiebotDialogBodyUnderlay'];"
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

            # email
            email_selectors = [
                "input[type='email'][name='email']",
                "input[name='email']",
                "input[type='email']",
            ]
            email_filled = False
            for sel in email_selectors:
                try:
                    for f in self.driver.find_elements(By.CSS_SELECTOR, sel):
                        if f.is_displayed() and f.is_enabled():
                            f.clear()
                            f.send_keys(xd_user)
                            email_filled = True
                            break
                    if email_filled:
                        break
                except Exception:
                    continue

            # pass
            try:
                for f in self.driver.find_elements(By.CSS_SELECTOR, "input[type='password']"):
                    if f.is_displayed() and f.is_enabled():
                        f.clear()
                        f.send_keys(xd_pass)
                        break
            except Exception:
                pass

            self._dismiss_cookie_banner()

            # submit
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

    @staticmethod
    def _extract_price_from_text(text: str) -> float:
        """Robust EUR extraction from visible text."""
        if not text:
            return 0.0
        # prefer patterns with EUR/€ close by
        patterns = [
            r"Price\s*[€]\s*(\d{1,6}(?:[\.,]\d{1,2})?)",
            r"From\s*\n?\s*Price\s*[€]\s*(\d{1,6}(?:[\.,]\d{1,2})?)",
            r"[€]\s*(\d{1,6}(?:[\.,]\d{1,2})?)",
            r"(\d{1,6}(?:[\.,]\d{1,2})?)\s*EUR\b",
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                try:
                    return clean_price(m.group(1))
                except Exception:
                    continue
        return 0.0

    def scrape(self, url: str) -> dict | None:
        # IMPORTANT: returnam mereu dict ca sa nu crape .get in app
        product = {
            "name": "",
            "sku": "",
            "price": 0.0,
            "currency": "EUR",
            "description": "",
            "specifications": {},
            "colors": [],
            "color_variants": [],
            "images": [],
            "url": url,
            "source": "xdconnects",
            "stock": 1,
        }

        try:
            self._login_if_needed()
            self._init_driver()
            if not self.driver:
                product["error"] = "Selenium driver not available"
                return product

            st.info(f"📦 XD v5.0.2: {url[:70]}...")
            self.driver.get(url)
            time.sleep(6)
            self._dismiss_cookie_banner()
            time.sleep(1)

            # Scroll for lazy load
            for frac in [0.25, 0.5, 0.85, 1.0, 0.0]:
                try:
                    self.driver.execute_script(
                        "window.scrollTo(0, document.body.scrollHeight*arguments[0]);",
                        frac,
                    )
                    time.sleep(0.6)
                except Exception:
                    pass

            # screenshot debug (optional)
            try:
                ss = self.driver.get_screenshot_as_png()
                st.image(ss, caption="XD pagina produs", width=700)
            except Exception:
                pass

            page_source = self.driver.page_source or ""
            soup = BeautifulSoup(page_source, "html.parser")

            # visible text for debugging + price
            visible_text = ""
            try:
                visible_text = self.driver.execute_script(
                    "return document.body.innerText || '';"
                )
                st.text_area(
                    "DEBUG: Text vizibil pe pagină",
                    str(visible_text)[:2000],
                    height=200,
                )
            except Exception:
                visible_text = ""

            # --- Name ---
            h1 = soup.select_one("h1")
            if h1:
                product["name"] = h1.get_text(strip=True)
            if not product["name"]:
                product["name"] = "Produs XD Connects"

            # --- SKU ---
            sku = ""
            m = re.search(r"Item\s*no\.?\s*: ?\s*([A-Z0-9.]+)", visible_text or page_source, re.IGNORECASE)
            if m:
                sku = m.group(1).upper()
            if not sku:
                m2 = re.search(r"variantId=([A-Z0-9.]+)", url, re.IGNORECASE)
                if m2:
                    sku = m2.group(1).upper()
            if not sku:
                m3 = re.search(r"([pP]\d{3}\.\d{2,3})", url)
                if m3:
                    sku = m3.group(1).upper()
            product["sku"] = sku

            # --- Price (EUR) ---
            price_eur = 0.0
            try:
                # prefer visible text
                price_eur = self._extract_price_from_text(visible_text)
                if price_eur <= 0:
                    # fallback to html
                    price_eur = self._extract_price_from_text(page_source)
            except Exception:
                price_eur = 0.0

            product["price"] = float(price_eur or 0.0)
            product["currency"] = "EUR"
            st.info(f"💰 PREȚ: {product['price']} {product['currency']}")

            # --- Description + Specs: use HTML tables that contain 'Description' ---
            description_text = ""
            specs = {}

            # find 'Product details' block by scanning for key rows
            # Many XD pages render a table with rows: Item no., Description, Product USPs, Primary specifications...
            for table in soup.select("table"):
                rows = table.select("tr")
                for row in rows:
                    cells = [c.get_text(" ", strip=True) for c in row.select("th,td")]
                    if len(cells) >= 2:
                        k = cells[0].strip()
                        v = cells[1].strip()
                        if not k or not v:
                            continue
                        # skip price matrix rows
                        if k.lower() in {"quantity", "printed*", "printed", "plain"}:
                            continue
                        if "€" in v or "eur" in v.lower() or "ron" in v.lower():
                            # likely price grid
                            continue
                        # capture description
                        if k.lower() in {"description", "descriere"} and len(v) > 30:
                            description_text = v
                        # specs
                        if len(k) < 80 and len(v) < 500:
                            specs[k] = v

            # fallback: try definition lists
            if not specs:
                dts = soup.select("dt")
                dds = soup.select("dd")
                for dt, dd in zip(dts, dds):
                    k = dt.get_text(" ", strip=True)
                    v = dd.get_text(" ", strip=True)
                    if not k or not v:
                        continue
                    if "€" in v or "eur" in v.lower() or "ron" in v.lower():
                        continue
                    specs[k] = v

            # if still no description, use meta description
            if not description_text:
                meta = soup.select_one("meta[name='description']")
                if meta:
                    description_text = (meta.get("content") or "").strip()

            # build html description
            if description_text:
                product["description"] = f"<p>{description_text}</p>"
            else:
                product["description"] = ""

            # filter out unwanted keys
            drop_keys = {
                "Quantity",
                "Printed*",
                "Printed",
                "Plain",
                "Recommended sales price",
                "Recommended sales price ",
            }
            specs_filtered = {}
            for k, v in (specs or {}).items():
                if k.strip() in drop_keys:
                    continue
                # also drop the explicit price-grid artifacts
                if k.strip().lower() in {"cantitate", "imprimat*", "simplu"}:
                    continue
                specs_filtered[k] = v
            product["specifications"] = specs_filtered

            st.info(f"📝 DESC: {len(product['description'])} car")
            st.info(f"📋 SPECS: {len(product['specifications'])} = {list(product['specifications'].items())[:3]}")

            # --- Current color (robust) ---
            color = ""
            # try from specs
            for key in ["Colour", "Color", "Culoare"]:
                if key in specs_filtered:
                    color = specs_filtered[key]
                    break
            if not color:
                # from visible text after Item no.
                mt = re.search(r"Item no\.\s*[A-Z0-9.]+\s*\n([A-Za-z][A-Za-z \-]{2,40})\n", visible_text or "")
                if mt:
                    color = mt.group(1).strip()
            if color:
                product["colors"] = [color]
            st.info(f"🎨 CULORI: {len(product['colors'])} = {product['colors']}")

            # --- Images ---
            images = []
            try:
                # include images from HTML
                for img in soup.select("img"):
                    src = img.get("data-src") or img.get("src") or img.get("data-lazy") or ""
                    if not src or len(src) < 10:
                        continue
                    if any(bad in src.lower() for bad in ["icon", "logo", "flag", "badge", "pixel", "svg", "data:"]):
                        continue
                    if any(good in src for good in ["/product/image/", "ProductImages", "/content/files/", "static.xd"]):
                        full = make_absolute_url(src, self.base_url)
                        if full not in images:
                            images.append(full)

                # background-image urls
                if len(images) < 3:
                    for el in soup.select("[style*='background']"):
                        style = el.get("style") or ""
                        m = re.search(r"url\(['\"]?([^'\"\)]+)", style)
                        if not m:
                            continue
                        src = m.group(1)
                        if any(good in src for good in ["/product/image/", "ProductImages", "static.xd"]):
                            full = make_absolute_url(src, self.base_url)
                            if full not in images:
                                images.append(full)
            except Exception:
                pass

            product["images"] = images

            st.info(f"📸 Total img: {len(product['images'])}")

            return product

        except Exception as e:
            product["error"] = str(e)
            st.warning(f"⚠️ XD scrape error: {str(e)[:160]}")
            return product
