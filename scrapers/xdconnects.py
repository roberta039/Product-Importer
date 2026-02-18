# scrapers/xdconnects.py
# XD Connects Scraper v5.6 (stable for Streamlit Cloud)
# - Compatible with project factory: XDConnectsScraper() takes no args (inherits BaseScraper)
# - Extracts description + specs from "Product details" even if hidden (uses textContent)
# - Extracts price from "Price €73.8" / "€ 73,80" formats
# - Extracts current color + tries to discover all variantId colors by iterating variants (limited)
# - Filters out pricing-table specs you don't want (Quantity/Printed/Plain/etc.)
# - Never returns None (always a dict)

import re
import time
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import streamlit as st
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from scrapers.base_scraper import BaseScraper
from utils.helpers import clean_price, double_price, generate_sku
from utils.image_handler import make_absolute_url


class XDConnectsScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.name = "xdconnects"
        self.base_url = "https://www.xdconnects.com"
        self._logged_in = False

    # ---------------------------
    # Utilities
    # ---------------------------
    def _dismiss_cookie_banner(self):
        if not self.driver:
            return
        selectors = [
            "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
            "#CybotCookiebotDialogBodyButtonAccept",
            "button#onetrust-accept-btn-handler",
        ]
        for sel in selectors:
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, sel)
                if btn.is_displayed():
                    self.driver.execute_script("arguments[0].click();", btn)
                    time.sleep(1)
                    return
            except Exception:
                continue
        # hard remove overlays
        try:
            self.driver.execute_script(
                "['#CybotCookiebotDialog','#CybotCookiebotDialogBodyUnderlay',"
                "'#onetrust-consent-sdk','#onetrust-banner-sdk'].forEach(function(s){"
                "document.querySelectorAll(s).forEach(function(e){e.remove();});});"
                "document.body.style.overflow='auto';"
            )
        except Exception:
            pass

    def _login_if_needed(self):
        """Login once per session (if creds exist)."""
        if self._logged_in:
            return

        xd_user = st.secrets.get("SOURCES", {}).get("XD_USER", "")
        xd_pass = st.secrets.get("SOURCES", {}).get("XD_PASS", "")
        if not xd_user or not xd_pass:
            # allow scraping without login (may work for some pages)
            self._logged_in = True
            return

        self._init_driver()
        if not self.driver:
            return

        st.info("🔐 XD: Mă conectez...")
        try:
            self.driver.get(self.base_url + "/en-gb/profile/login")
            time.sleep(4)
            self._dismiss_cookie_banner()
            time.sleep(1)

            # email
            email_selectors = [
                "input[type='email'][name='email']",
                "input[name='email']",
                "input[type='email']",
            ]
            email_el = None
            for sel in email_selectors:
                try:
                    for el in self.driver.find_elements(By.CSS_SELECTOR, sel):
                        if el.is_displayed() and el.is_enabled():
                            email_el = el
                            break
                except Exception:
                    continue
                if email_el:
                    break
            if email_el:
                email_el.clear()
                email_el.send_keys(xd_user)

            # password
            pw_el = None
            try:
                for el in self.driver.find_elements(By.CSS_SELECTOR, "input[type='password']"):
                    if el.is_displayed() and el.is_enabled():
                        pw_el = el
                        break
            except Exception:
                pw_el = None
            if pw_el:
                pw_el.clear()
                pw_el.send_keys(xd_pass)

            self._dismiss_cookie_banner()

            # submit
            submitted = False
            for sel in ["form button[type='submit']", "button[type='submit']"]:
                try:
                    for btn in self.driver.find_elements(By.CSS_SELECTOR, sel):
                        if btn.is_displayed() and btn.is_enabled():
                            self.driver.execute_script("arguments[0].click();", btn)
                            submitted = True
                            break
                except Exception:
                    continue
                if submitted:
                    break

            time.sleep(4)
            self._logged_in = True
            st.success("✅ XD: Login reușit!")
        except Exception as e:
            st.warning(f"⚠️ XD login a eșuat: {str(e)[:120]}")
            self._logged_in = True  # don't block

    def _get_variant_id_from_url(self, url: str) -> str:
        try:
            qs = parse_qs(urlparse(url).query)
            return (qs.get("variantId") or [""])[0].strip()
        except Exception:
            return ""

    def _set_variant_in_url(self, url: str, variant_id: str) -> str:
        try:
            p = urlparse(url)
            qs = parse_qs(p.query)
            qs["variantId"] = [variant_id]
            new_query = urlencode({k: v[0] for k, v in qs.items()})
            return urlunparse((p.scheme, p.netloc, p.path, p.params, new_query, p.fragment))
        except Exception:
            return url

    def _get_body_text_and_html(self):
        """Return (textContent, page_source). textContent often includes hidden tab content."""
        text = ""
        html = ""
        if self.driver:
            try:
                text = self.driver.execute_script("return document.body ? document.body.textContent : ''") or ""
            except Exception:
                text = ""
            try:
                html = self.driver.page_source or ""
            except Exception:
                html = ""
        return text, html

    # ---------------------------
    # Parsers
    # ---------------------------
    def _parse_title(self, body_text: str) -> str:
        lines = [ln.strip() for ln in (body_text or "").splitlines() if ln.strip()]
        # Often the title is right before "Item no."
        for i, ln in enumerate(lines):
            if re.search(r"\bItem no\.", ln, re.I) and i > 0:
                prev = lines[i - 1]
                if len(prev) > 3:
                    return prev
        # fallback: driver.title
        try:
            t = (self.driver.title or "").split("|")[0].strip()
            if t:
                return t
        except Exception:
            pass
        return "Produs"

    def _parse_price_eur(self, body_text: str) -> float:
        t = (body_text or "").replace("\u00a0", " ")
        # Strong patterns first
        patterns = [
            r"\bPrice\s*€\s*([0-9]+(?:[\.,][0-9]+)?)",
            r"\bFrom\s*Price\s*€\s*([0-9]+(?:[\.,][0-9]+)?)",
            r"€\s*([0-9]+(?:[\.,][0-9]+)?)",
        ]
        for pat in patterns:
            m = re.search(pat, t, flags=re.I)
            if m:
                s = m.group(1).strip().replace(",", ".")
                try:
                    return float(s)
                except Exception:
                    # as fallback, use clean_price
                    return float(clean_price(s))
        return 0.0

    def _parse_current_color(self, body_text: str) -> str:
        txt = body_text or ""
        # after Item no.
        m = re.search(r"Item no\.\s*[A-Z0-9\.]+\s*\n([A-Za-z][A-Za-z \-]{2,40})\n", txt)
        if m:
            return m.group(1).strip()
        # "Colour  light blue" in tables
        m = re.search(r"\bColour\b\s*[:\t ]+\s*([^\n\r\t]+)", txt, re.I)
        if m:
            val = m.group(1).strip()
            val = re.split(r"\s{2,}|\t|•|\|", val)[0].strip()
            if 1 <= len(val) <= 40:
                return val
        return ""

    def _extract_variant_ids_from_html(self, html: str) -> list:
        if not html:
            return []
        vids = re.findall(r"variantId=([A-Z0-9\.]+)", html, flags=re.I)
        # also JSON-ish: "variantId":"P705.709"
        vids += re.findall(r'"variantId"\s*:\s*"([A-Z0-9\.]+)"', html, flags=re.I)
        uniq = []
        for v in vids:
            vv = v.strip()
            if vv and vv not in uniq:
                uniq.append(vv)
        return uniq

    def _parse_specs_from_product_details(self, body_text: str) -> dict:
        """Parse key/value pairs from Product details region."""
        specs = {}
        text = (body_text or "").replace("\u00a0", " ")
        # focus after "Product details"
        low = text.lower()
        start = low.find("product details")
        region = text[start:] if start != -1 else text

        # stop at common footer markers
        stop_markers = ["esg features", "documentation", "login", "register", "© copyright", "contact", "privacy"]
        stop = None
        for mk in stop_markers:
            j = region.lower().find(mk)
            if j != -1:
                stop = j
                break
        if stop:
            region = region[:stop]

        # Parse lines with tabs (table-like) or multiple spaces
        lines = [ln.rstrip() for ln in region.splitlines() if ln.strip()]
        for ln in lines:
            lnl = ln.strip().lower()
            if lnl in ("product details", "primary specifications"):
                continue

            if "\t" in ln:
                parts = [p.strip() for p in ln.split("\t") if p.strip()]
                if len(parts) >= 2:
                    specs[parts[0]] = " ".join(parts[1:])
                    continue

            parts = re.split(r"\s{2,}", ln.strip())
            if len(parts) >= 2:
                k = parts[0].strip()
                v = " ".join(p.strip() for p in parts[1:] if p.strip())
                if 1 <= len(k) <= 60 and v:
                    specs[k] = v

        # Ensure Description captured even if not aligned
        if "Description" not in specs and "Descriere" not in specs:
            m = re.search(r"\bDescription\b\s+(.+)", region, re.I | re.S)
            if m:
                chunk = m.group(1)
                chunk = re.split(r"\nProduct USPs|\nPrimary specifications|\nESG Features|\nDocumentation", chunk, flags=re.I)[0]
                desc = " ".join([x.strip() for x in chunk.splitlines() if x.strip()])
                if desc:
                    specs["Description"] = desc

        return specs

    def _filter_specs(self, specs: dict) -> dict:
        drop = {
            "Quantity", "Printed*", "Printed", "Plain", "Recommended sales price",
            "Cantitate", "Imprimat*", "Imprimat", "Simplu", "Pret de vanzare recomandat",
            "Preț", "Pret", "Price", "From", "From Price",
        }
        out = {}
        for k, v in (specs or {}).items():
            kk = (k or "").strip()
            if not kk or kk in drop:
                continue
            if kk.lower().startswith("quantity"):
                continue
            out[kk] = (v or "").strip()
        return out

    def _specs_to_html(self, specs: dict) -> str:
        if not specs:
            return ""
        rows = []
        for k, v in specs.items():
            rows.append(f"<tr><th>{k}</th><td>{v}</td></tr>")
        return "<table>" + "".join(rows) + "</table>"

    # ---------------------------
    # Main scrape
    # ---------------------------
    def scrape(self, url: str) -> dict:
        # Always return a dict to keep app stable
        product = {
            "name": "",
            "sku": "",
            "original_price": 0.0,
            "currency": "EUR",
            "final_price": 1.0,
            "stock": 1,
            "colors": [],
            "color_variants": [],
            "images": [],
            "description": "",
            "description_html": "",
            "specs": {},
            "specs_html": "",
            "source_url": url,
            "source_site": "xdconnects",
        }

        try:
            self._login_if_needed()
            self._init_driver()
            if not self.driver:
                product["error"] = "Selenium driver not available"
                return product

            st.write(f"📦 XD v5.6: {url[:70]}...")

            self.driver.get(url)
            time.sleep(4)
            self._dismiss_cookie_banner()
            time.sleep(1)

            # small scroll for lazy content
            try:
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
                time.sleep(0.5)
                self.driver.execute_script("window.scrollTo(0, 0);")
            except Exception:
                pass

            body_text, html = self._get_body_text_and_html()

            # title + sku
            name = self._parse_title(body_text)
            sku = self._get_variant_id_from_url(url) or ""
            if not sku:
                # fallback find in text
                m = re.search(r"\bItem no\.\s*([A-Z0-9\.]+)", body_text, re.I)
                if m:
                    sku = m.group(1).strip()
            product["name"] = name
            product["sku"] = generate_sku(sku, url)

            # price (EUR numeric)
            price_eur = self._parse_price_eur(body_text)
            product["original_price"] = float(price_eur or 0.0)
            product["final_price"] = double_price(product["original_price"])

            # specs + description
            specs_raw = self._parse_specs_from_product_details(body_text)
            specs = self._filter_specs(specs_raw)
            product["specs"] = specs
            product["specs_html"] = self._specs_to_html(specs)

            desc = specs.get("Description") or specs.get("Descriere") or ""
            if desc and len(desc) > 30:
                product["description"] = desc
                product["description_html"] = f"<p>{BeautifulSoup(desc, 'html.parser').get_text(' ', strip=True)}</p>"
            else:
                # try from specs_raw
                desc2 = specs_raw.get("Description") or specs_raw.get("Descriere") or ""
                if desc2:
                    product["description"] = desc2
                    product["description_html"] = f"<p>{BeautifulSoup(desc2, 'html.parser').get_text(' ', strip=True)}</p>"

            # images
            images = []
            try:
                soup = BeautifulSoup(html, "html.parser")
                for img in soup.select("img"):
                    src = img.get("src") or img.get("data-src") or ""
                    src = src.strip()
                    if not src:
                        continue
                    if any(x in src for x in ["/product/image/", ".jpg", ".jpeg", ".png", ".webp"]):
                        absu = make_absolute_url(src, self.base_url)
                        if absu not in images:
                            images.append(absu)
            except Exception:
                images = []
            product["images"] = images

            # color(s)
            current_color = self._parse_current_color(body_text)
            if current_color:
                product["colors"] = [current_color]

            # Discover variants (best-effort): parse variantIds in HTML and iterate a few
            variant_ids = self._extract_variant_ids_from_html(html)
            current_vid = self._get_variant_id_from_url(url)
            if current_vid and current_vid not in variant_ids:
                variant_ids.insert(0, current_vid)

            # limit to avoid huge runtime
            variant_ids = variant_ids[:15]

            color_variants = []
            colors_all = []
            if current_color:
                colors_all.append(current_color)
                color_variants.append({"variantId": current_vid or product["sku"], "color": current_color})

            # iterate other variants to read their current color line
            for vid in variant_ids:
                if not vid or vid == current_vid:
                    continue
                try:
                    vurl = self._set_variant_in_url(url, vid)
                    self.driver.get(vurl)
                    time.sleep(3)
                    self._dismiss_cookie_banner()
                    btxt, _ = self._get_body_text_and_html()
                    c = self._parse_current_color(btxt)
                    if c:
                        if c not in colors_all:
                            colors_all.append(c)
                        color_variants.append({"variantId": vid, "color": c})
                except Exception:
                    continue

            if colors_all:
                product["colors"] = colors_all
            if color_variants:
                product["color_variants"] = color_variants

            return product

        except Exception as e:
            product["error"] = str(e)
            # keep minimum required fields
            if not product.get("final_price"):
                product["final_price"] = 1.0
            return product
