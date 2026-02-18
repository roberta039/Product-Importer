# scrapers/xdconnects.py
# XD Connects scraper - Stable (factory-compatible) version
# Focus: Step 1 extraction (name, sku, price, description, specs, colors, images)

import re
import time
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import streamlit as st
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from scrapers.base_scraper import BaseScraper
from utils.helpers import clean_price
from utils.image_handler import make_absolute_url


XD_SCRAPER_VERSION = "2026-02-18-xd-stable-v57"


class XDConnectsScraper(BaseScraper):
    """XD Connects scraper (Selenium). Compatible with scrapers.get_scraper factory."""

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
            "button[aria-label='Accept all']",
        ]:
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
                "var ids=['#CybotCookiebotDialog','#CybotCookiebotDialogBodyUnderlay'];"
                "ids.forEach(function(x){document.querySelectorAll(x).forEach(e=>e.remove());});"
                "document.body.style.overflow='auto';"
            )
        except Exception:
            pass

    def _login_if_needed(self):
        if self._logged_in:
            return

        xd_user = (st.secrets.get("SOURCES", {}) or {}).get("XD_USER", "")
        xd_pass = (st.secrets.get("SOURCES", {}) or {}).get("XD_PASS", "")
        if not xd_user or not xd_pass:
            # continue without login
            self._logged_in = True
            return

        try:
            self._init_driver()
            if not self.driver:
                self._logged_in = True
                return

            st.info("🔐 XD: Mă conectez...")
            self.driver.get(self.base_url + "/en-gb/profile/login")
            time.sleep(4)
            self._dismiss_cookie_banner()

            # email
            email_done = False
            for sel in [
                "input[type='email'][name='email']",
                "input[name='email']",
                "input[type='email']",
            ]:
                try:
                    for f in self.driver.find_elements(By.CSS_SELECTOR, sel):
                        if f.is_displayed() and f.is_enabled():
                            f.clear()
                            f.send_keys(xd_user)
                            email_done = True
                            break
                    if email_done:
                        break
                except Exception:
                    continue

            # password
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

    def _get_full_text(self) -> str:
        """Get page text even if some sections are hidden (textContent)."""
        if not self.driver:
            return ""
        try:
            txt = self.driver.execute_script("return document.body && document.body.textContent ? document.body.textContent : ''; ")
            return txt or ""
        except Exception:
            try:
                return self.driver.execute_script("return document.body.innerText || ''; ") or ""
            except Exception:
                return ""

    def _extract_price_eur(self, text: str) -> float:
        if not text:
            return 0.0
        # Prefer explicit "Price €73.8" or "Price € 73,80"
        m = re.search(r"\bPrice\s*€\s*([0-9]{1,6}(?:[\.,][0-9]{1,2})?)", text, flags=re.IGNORECASE)
        if not m:
            # sometimes "From\nPrice €73.8" or just "€ 73,80" near the top
            m = re.search(r"€\s*([0-9]{1,6}(?:[\.,][0-9]{1,2})?)", text)
        if not m:
            return 0.0
        val = m.group(1).strip().replace(" ", "")
        val = val.replace(",", ".")
        try:
            return float(val)
        except Exception:
            return 0.0

    def _extract_sku(self, url: str, text: str) -> str:
        # prefer variantId from query
        try:
            q = parse_qs(urlparse(url).query)
            vid = (q.get("variantId") or [""])[0]
            if vid:
                return vid.strip().upper()
        except Exception:
            pass
        # from text "Item no. P705.709"
        m = re.search(r"Item\s*no\.?\s*([A-Z0-9.]+)", text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip().upper()
        # from url path p705.70
        m = re.search(r"([pP]\d{3}\.\d{2,3})", url)
        if m:
            return m.group(1).upper()
        return ""

    def _extract_current_colour(self, text: str) -> str:
        if not text:
            return ""
        # pattern: Item no. P705.709 \n light blue \n
        m = re.search(r"Item\s*no\.?\s*[A-Z0-9.]+\s*\n\s*([A-Za-z][A-Za-z \-]{2,40})\s*\n", text)
        if m:
            return m.group(1).strip()
        # pattern: Colour\tlight blue
        m = re.search(r"\bColour\b\s*[:\t ]+\s*([^\n\r\t]{1,40})", text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return ""

    def _extract_product_details_block(self, text: str) -> str:
        if not text:
            return ""
        # try to capture from "Product details" to next section
        start = re.search(r"\bProduct details\b", text, flags=re.IGNORECASE)
        if not start:
            return ""
        after = text[start.end():]
        end = re.search(r"\b(ESG Features|Documentation|Login\b|Register\b|About Us\b)\b", after, flags=re.IGNORECASE)
        block = after[: end.start()] if end else after
        return block.strip()

    def _parse_specs_from_details(self, block: str) -> tuple[str, dict]:
        """Return (description, specs_dict) from the Product details text block."""
        if not block:
            return "", {}

        # Normalize: split lines, but also break on tabs
        lines = []
        for raw in block.splitlines():
            raw = raw.strip()
            if not raw:
                continue
            if "\t" in raw:
                parts = [p.strip() for p in raw.split("\t") if p.strip()]
                # keep as a single line pair if exactly 2
                if len(parts) == 2:
                    lines.append(parts[0] + "\t" + parts[1])
                else:
                    lines.extend(parts)
            else:
                lines.append(raw)

        specs = {}
        desc = ""

        # Parse pairs (key\tvalue) OR key then value on next line
        i = 0
        while i < len(lines):
            line = lines[i]
            if "\t" in line:
                k, v = line.split("\t", 1)
                k = k.strip()
                v = v.strip()
                if k:
                    specs[k] = v
                i += 1
                continue

            # Sometimes a key line followed by value line
            if i + 1 < len(lines):
                nxt = lines[i + 1]
                # likely key if short and next is longer
                if len(line) <= 40 and len(nxt) > 0 and ("\t" not in nxt):
                    # avoid section headers
                    if line.lower() not in {"product details", "primary specifications"}:
                        # heuristic: treat as pair if next doesn't look like another key
                        if not re.match(r"^[A-Za-z ]{2,30}$", nxt) or len(nxt) > 30:
                            specs[line] = nxt
                            i += 2
                            continue
            i += 1

        # Description
        for k in list(specs.keys()):
            if k.lower() in {"description", "descriere"}:
                desc = specs.pop(k)
                break

        # Clean up unwanted entries
        blacklist_keys = {
            "quantity", "cantitate",
            "printed*", "printed", "imprimat*", "imprimat",
            "plain", "simplu",
            "recommended sales price", "pret de vanzare recomandat",
        }
        cleaned = {}
        for k, v in specs.items():
            kl = k.strip().lower()
            if kl in blacklist_keys:
                continue
            if kl.startswith("quantity"):
                continue
            cleaned[k.strip()] = v.strip() if isinstance(v, str) else v

        return desc.strip(), cleaned

    def _extract_images(self, soup: BeautifulSoup, page_source: str, url: str) -> list[str]:
        images = set()

        # img tags
        for img in soup.select("img"):
            for attr in ["src", "data-src", "data-lazy", "srcset", "data-srcset"]:
                val = img.get(attr)
                if not val:
                    continue
                # srcset can be multiple
                if " " in val and "," in val:
                    parts = [p.strip().split(" ")[0] for p in val.split(",") if p.strip()]
                else:
                    parts = [val]
                for p in parts:
                    if p.startswith("data:"):
                        continue
                    absu = make_absolute_url(p, url)
                    if absu and ("/product/image/" in absu or absu.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif"))):
                        images.add(absu)

        # background-image urls
        for m in re.finditer(r"background-image\s*:\s*url\(['\"]?([^'\")]+)['\"]?\)", page_source, flags=re.IGNORECASE):
            absu = make_absolute_url(m.group(1), url)
            if absu:
                images.add(absu)

        # XD product images often include /product/image/
        for m in re.finditer(r"(/product/image/[^\s'\"\\]+\.(?:jpg|jpeg|png|webp))", page_source, flags=re.IGNORECASE):
            absu = make_absolute_url(m.group(1), url)
            if absu:
                images.add(absu)

        return list(images)

    def _build_variant_url(self, url: str, variant_id: str) -> str:
        try:
            p = urlparse(url)
            q = parse_qs(p.query)
            q["variantId"] = [variant_id]
            new_query = urlencode(q, doseq=True)
            return urlunparse((p.scheme, p.netloc, p.path, p.params, new_query, p.fragment))
        except Exception:
            return url

    # ----------------------------
    # Main
    # ----------------------------
    def scrape(self, url: str) -> dict:
        """Return a product dict; never returns None."""
        product = {
            "name": "",
            "sku": "",
            "price": 0.0,
            "currency": "EUR",
            "description": "",
            "specs": {},
            "colors": [],
            "variants": [],
            "images": [],
            "source": "xdconnects",
            "url": url,
            "error": "",
        }

        try:
            self._login_if_needed()
            self._init_driver()
            if not self.driver:
                product["error"] = "Selenium driver unavailable"
                return product

            st.info(f"📦 XD {XD_SCRAPER_VERSION}: {url[:70]}...")

            self.driver.get(url)
            time.sleep(6)
            self._dismiss_cookie_banner()
            time.sleep(1)

            # Scroll for lazy content
            for frac in [0.3, 0.6, 0.9, 1.0, 0.0]:
                try:
                    self.driver.execute_script(
                        "window.scrollTo(0, document.body.scrollHeight * arguments[0]);",
                        frac,
                    )
                    time.sleep(0.6)
                except Exception:
                    pass

            # Screenshot for debug (optional)
            try:
                ss = self.driver.get_screenshot_as_png()
                st.image(ss, caption="XD pagina produs", width=700)
            except Exception:
                pass

            page_source = self.driver.page_source or ""
            soup = BeautifulSoup(page_source, "html.parser")

            full_text = self._get_full_text()

            # DEBUG visible snippet (keep small)
            try:
                snippet = (full_text or "")[:1800]
                st.text_area("DEBUG: Text vizibil pe pagină", snippet, height=200)
            except Exception:
                pass

            # Name
            h1 = soup.select_one("h1")
            name = h1.get_text(strip=True) if h1 else ""
            if not name:
                # fallback from title
                t = soup.select_one("title")
                name = t.get_text(strip=True) if t else "Produs XD Connects"
            product["name"] = name

            # SKU
            sku = self._extract_sku(url, full_text)
            product["sku"] = sku

            # Price
            price_eur = self._extract_price_eur(full_text)
            product["price"] = float(price_eur) if price_eur else 0.0
            product["currency"] = "EUR"

            # Product details
            details_block = self._extract_product_details_block(full_text)
            desc, specs = self._parse_specs_from_details(details_block)
            product["description"] = desc
            product["specs"] = specs

            # Colors (current)
            color = ""
            # try in specs
            for key in ["Colour", "Color", "Culoare"]:
                if key in specs and specs[key]:
                    color = str(specs[key]).strip()
                    break
            if not color:
                color = self._extract_current_colour(full_text)
            if color:
                product["colors"] = [color]

            # Variants (best-effort): collect variantIds from HTML
            variant_ids = []
            for m in re.finditer(r"variantId=([A-Z0-9.]+)", page_source):
                vid = m.group(1).strip().upper()
                if vid and vid not in variant_ids:
                    variant_ids.append(vid)
            # include current if present
            if sku and sku not in variant_ids and "." in sku:
                variant_ids.insert(0, sku)

            # If multiple variantIds found, fetch colors for each (limited)
            variants = []
            colors_all = []
            if len(variant_ids) > 1:
                for vid in variant_ids[:12]:
                    vurl = self._build_variant_url(url, vid)
                    try:
                        self.driver.get(vurl)
                        time.sleep(3)
                        self._dismiss_cookie_banner()
                        vtext = self._get_full_text()
                        vcolor = self._extract_current_colour(vtext)
                        if not vcolor:
                            # sometimes in details specs
                            vblock = self._extract_product_details_block(vtext)
                            _, vspecs = self._parse_specs_from_details(vblock)
                            vcolor = str(vspecs.get("Colour", "") or vspecs.get("Color", "") or "").strip()
                        variants.append({"variantId": vid, "color": vcolor})
                        if vcolor and vcolor not in colors_all:
                            colors_all.append(vcolor)
                    except Exception:
                        variants.append({"variantId": vid, "color": ""})

                product["variants"] = variants
                if colors_all:
                    product["colors"] = colors_all
            else:
                product["variants"] = [{"variantId": sku, "color": product["colors"][0] if product["colors"] else ""}] if sku else []

            # Restore original url page (optional)
            try:
                self.driver.get(url)
            except Exception:
                pass

            # Images
            product["images"] = self._extract_images(soup, page_source, url)

            # Debug prints (to logs)
            print("XD VERSION", XD_SCRAPER_VERSION, "sku=", sku, "price_eur=", price_eur, "colors=", product.get("colors"), "variants=", len(product.get("variants", [])), "desc_len=", len(product.get("description") or ""), "specs=", len(product.get("specs") or {}), "imgs=", len(product.get("images") or []))

            return product

        except Exception as e:
            product["error"] = str(e)
            try:
                st.warning(f"⚠️ XD scrape error: {str(e)[:140]}")
            except Exception:
                pass
            return product
