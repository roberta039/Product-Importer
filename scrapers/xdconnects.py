# scrapers/xdconnects.py
# XD Connects Scraper v6.1 (stable)
# - Login (optional via Streamlit secrets)
# - Extract description + specifications
# - Extract ALL color variants (variantId) when available
# - Return dict (single) or list[dict] (variants)

import re
import time
from typing import Dict, List, Optional

import streamlit as st
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from scrapers.base_scraper import BaseScraper
from utils.image_handler import make_absolute_url
from utils.helpers import clean_price

XD_SCRAPER_VERSION = "2026-02-18-xd-v6.1-stable"

_VALID_VARIANT_RE = re.compile(r"^[P]\d{3}\.\d{2,3}$", re.IGNORECASE)


def _is_variant_id(v: str) -> bool:
    v = (v or "").strip()
    return bool(_VALID_VARIANT_RE.match(v))


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in items:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


class XDConnectsScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.name = "xdconnects"
        self.base_url = "https://www.xdconnects.com"
        self._logged_in = False

    # ---------------------------
    # Session / login helpers
    # ---------------------------
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
                    time.sleep(1)
                    return
            except NoSuchElementException:
                continue
            except Exception:
                continue
        # fallback: remove overlays if present
        try:
            self.driver.execute_script(
                "['#CybotCookiebotDialog','#CybotCookiebotDialogBodyUnderlay','.cookie','.cookies']"
                ".forEach(s=>document.querySelectorAll(s).forEach(e=>e.remove()));"
                "document.body.style.overflow='auto';"
            )
        except Exception:
            pass

    def _login_if_needed(self):
        if self._logged_in:
            return
        print("XD SCRAPER VERSION:", XD_SCRAPER_VERSION)

        try:
            xd_user = st.secrets.get("SOURCES", {}).get("XD_USER", "")
            xd_pass = st.secrets.get("SOURCES", {}).get("XD_PASS", "")
        except Exception:
            xd_user, xd_pass = "", ""

        # Dacă nu ai credențiale în Secrets, continuăm anonim
        if not xd_user or not xd_pass:
            self._logged_in = True
            return

        self._init_driver()
        if not self.driver:
            self._logged_in = True
            return

        try:
            st.info("🔐 XD: Mă conectez...")
            self.driver.get(self.base_url + "/en-gb/profile/login")
            time.sleep(4)
            self._dismiss_cookie_banner()

            # email
            email_el = None
            for sel in ["input[type='email'][name='email']", "input[name='email']", "input[type='email']"]:
                try:
                    for f in self.driver.find_elements(By.CSS_SELECTOR, sel):
                        if f.is_displayed() and f.is_enabled():
                            email_el = f
                            break
                    if email_el:
                        break
                except Exception:
                    continue
            if email_el:
                email_el.clear()
                email_el.send_keys(xd_user)

            # pass
            try:
                pw = self.driver.find_element(By.CSS_SELECTOR, "input[type='password']")
                pw.clear()
                pw.send_keys(xd_pass)
            except Exception:
                pass

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
                    if submitted:
                        break
                except Exception:
                    continue

            time.sleep(5)
            self._logged_in = True
            st.success("✅ XD: Login reușit!")
        except Exception as e:
            st.warning(f"⚠️ XD login: {type(e).__name__}: {repr(e)}")
            self._logged_in = True

    # ---------------------------
    # Variant extraction
    # ---------------------------
    def _set_variant_in_url(self, url: str, variant_id: str) -> str:
        variant_id = (variant_id or "").strip().upper()
        if "variantId=" in url:
            return re.sub(r"variantId=([A-Z0-9\.]+)", "variantId=" + variant_id, url, flags=re.IGNORECASE)
        joiner = "&" if "?" in url else "?"
        return url + joiner + "variantId=" + variant_id

    def _get_variant_options(self) -> List[Dict[str, str]]:
        """Returnează opțiuni: [{'variantId': 'P705.709', 'color': 'light blue'}]."""
        if not self.driver:
            return []

        try:
            data = self.driver.execute_script(
                r"""
                const out = [];
                const seen = new Set();
                const isVid = (v) => /^[Pp]\d{3}\.\d{2,3}$/.test((v||'').trim());

                // 1) <select> cu id/name ce conține color/colour
                document.querySelectorAll('select').forEach(sel => {
                  const meta = ((sel.id||'') + ' ' + (sel.name||'')).toLowerCase();
                  if (!meta.match(/colou?r|color/)) return;
                  sel.querySelectorAll('option').forEach(opt => {
                    const v = (opt.value||'').trim();
                    const t = (opt.textContent||'').trim();
                    if (isVid(v) && !seen.has(v)) { out.push({variantId: v.toUpperCase(), color: t}); seen.add(v); }
                  });
                });

                // 2) elemente cu atribute data-variant*
                const attrs = ['data-variant','data-variantid','data-variant-id','data-variantId'];
                document.querySelectorAll('*').forEach(el => {
                  for (const a of attrs) {
                    const v = (el.getAttribute(a)||'').trim();
                    if (isVid(v) && !seen.has(v)) {
                      out.push({variantId: v.toUpperCase(), color: (el.textContent||'').trim()});
                      seen.add(v);
                    }
                  }
                  // 3) href cu variantId=
                  const href = el.getAttribute('href')||'';
                  if (href.includes('variantId=')) {
                    const m = href.match(/variantId=([A-Za-z0-9\.]+)/);
                    if (m) {
                      const v = (m[1]||'').trim();
                      if (isVid(v) && !seen.has(v)) {
                        out.push({variantId: v.toUpperCase(), color: (el.textContent||'').trim()});
                        seen.add(v);
                      }
                    }
                  }
                });

                return out;
                """
            )
        except Exception:
            return []

        out: List[Dict[str, str]] = []
        if isinstance(data, list):
            for it in data:
                if not isinstance(it, dict):
                    continue
                vid = (it.get("variantId") or "").strip().upper()
                col = (it.get("color") or "").strip()
                if _is_variant_id(vid):
                    out.append({"variantId": vid, "color": col})
        # dedupe by variantId
        seen = set()
        deduped = []
        for it in out:
            if it["variantId"] in seen:
                continue
            seen.add(it["variantId"])
            deduped.append(it)
        return deduped[:60]

    # ---------------------------
    # Single variant scrape
    # ---------------------------
    def _scrape_one(self, url: str) -> Optional[dict]:
        if not self.driver:
            return None

        self.driver.get(url)
        time.sleep(5)
        self._dismiss_cookie_banner()

        # scroll pt lazy images
        try:
            for frac in [0.35, 0.8, 1.0, 0.0]:
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight*arguments[0]);", frac)
                time.sleep(0.7)
        except Exception:
            pass

        page_source = self.driver.page_source or ""
        soup = BeautifulSoup(page_source, "html.parser")

        # Nume
        h1 = soup.select_one("h1")
        name = h1.get_text(strip=True) if h1 else ""
        if not name:
            name = "Produs XD Connects"

        # SKU (Item no.)
        sku = ""
        m = re.search(r"Item\s*no\.?\s*:?\s*([A-Z0-9.]+)", page_source, re.IGNORECASE)
        if m:
            sku = m.group(1).upper()
        if not sku:
            m = re.search(r"variantId=([A-Z0-9.]+)", url, re.IGNORECASE)
            if m:
                sku = m.group(1).upper()

        # Preț (nu te interesează acum, dar îl păstrăm 0)
        price = 0.0
        currency = "EUR"
        try:
            txt = (self.driver.execute_script("return document.body.innerText || ''") or "")
            m = re.search(r"\bPrice\b\s*€\s*(\d{1,6}(?:[\.,]\d{1,2})?)", txt, re.IGNORECASE)
            if not m:
                m = re.search(r"€\s*(\d{1,6}(?:[\.,]\d{1,2})?)", txt)
            if m:
                price = clean_price(m.group(1))
                currency = "EUR"
        except Exception:
            pass

        # Descriere + Specificații (folosim metode robuste din BaseScraper)
        description_html = self.extract_description(soup, page_source)
        specifications = self.extract_specifications(soup, page_source)

        # Curățăm ce nu vrei
        drop_keys = {"Quantity", "Cantitate", "Printed", "Imprimat", "Plain", "Simplu", "Price", "Preț", "Pret", "From"}
        specifications = {k: v for k, v in (specifications or {}).items() if k and k.strip() and k.strip() not in drop_keys}

        # Culoare (fallback din text, dacă există)
        color = None
        try:
            txt = (self.driver.execute_script("return document.body.innerText || ''") or "")
            cm = re.search(r"\bColour\b\s*[:\t ]+\s*([^\n\r\t]+)", txt, flags=re.IGNORECASE)
            if cm:
                color = cm.group(1).strip()
                color = re.split(r"\s{2,}|\t|•|\|", color)[0].strip()
        except Exception:
            pass

        if color:
            specifications = specifications or {}
            specifications["Culoare"] = color

        # Imagini
        images: List[str] = []
        for img in soup.select("img"):
            src = img.get("src") or img.get("data-src") or ""
            if not src:
                continue
            if "/product/image/" in src or "xdconnects.com" in src:
                images.append(make_absolute_url(src, self.base_url))
        images = _dedupe_keep_order(images)

        product = self._build_product(
            name=name,
            description=description_html,
            sku=sku,
            price=price,
            currency=currency,
            images=images,
            colors=[color] if color else [],
            specifications=specifications or {},
            source_url=url,
            source_site="xdconnects",
        )
        return product

    # ---------------------------
    # Public API
    # ---------------------------
    def scrape(self, url: str):
        """Returnează dict (1 variantă) sau list[dict] (toate variantele de culoare)."""
        self._login_if_needed()
        self._init_driver()
        if not self.driver:
            return None

        try:
            # open once, get options
            self.driver.get(url)
            time.sleep(5)
            self._dismiss_cookie_banner()
        except Exception:
            pass

        options = self._get_variant_options()
        if not options:
            return self._scrape_one(url)

        products: List[dict] = []
        for opt in options:
            vid = (opt.get("variantId") or "").strip().upper()
            if not _is_variant_id(vid):
                continue
            vurl = self._set_variant_in_url(url, vid)
            p = self._scrape_one(vurl)
            if isinstance(p, dict):
                col = (opt.get("color") or "").strip()
                if col:
                    p["colors"] = [col]
                    specs = p.get("specifications") or {}
                    specs["Culoare"] = col
                    p["specifications"] = specs
                p["sku"] = vid
                p["source_url"] = vurl
                products.append(p)

        if len(products) >= 2:
            return products
        return products[0] if products else self._scrape_one(url)
