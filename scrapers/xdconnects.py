# scrapers/xdconnects.py
# XD Connects Scraper v6.0 (stable)
# - Robust click on "Product details" panel
# - Extract full Description + Specifications from Product details
# - Color fallback (from specs or raw text)
# - Images extraction (src + background-image)

import re
import time
from typing import Any

import streamlit as st
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from scrapers.base_scraper import BaseScraper
from utils.helpers import clean_price
from utils.image_handler import make_absolute_url

XD_SCRAPER_VERSION = "2026-02-17-xd-v6-productdetails-colors"


def _specs_to_dict(specs: Any) -> dict:
    """Normalize specs that might be dict OR list of (k,v)."""
    if isinstance(specs, dict):
        return {str(k).strip(): str(v).strip() for k, v in specs.items()}
    d: dict[str, str] = {}
    try:
        for k, v in specs:
            ks = str(k).strip()
            vs = str(v).strip()
            if ks:
                d[ks] = vs
    except Exception:
        pass
    return d


def _extract_colour_from_text(raw_text: str) -> str | None:
    if not raw_text:
        return None

    # 1) "Colour  light blue" etc.
    m = re.search(r"\bColour\b\s*[:\t ]+\s*([^\n\r\t]+)", raw_text, flags=re.IGNORECASE)
    if m:
        val = m.group(1).strip()
        val = re.split(r"\s{2,}|\t|•|\|", val)[0].strip()
        if 1 <= len(val) <= 40:
            return val

    # 2) after Item no.
    m = re.search(r"Item no\.\s*[A-Z0-9\.]+\s*\n([A-Za-z][A-Za-z \-]{2,40})\n", raw_text)
    if m:
        return m.group(1).strip()

    return None


class XDConnectsScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.name = "xdconnects"
        self.base_url = "https://www.xdconnects.com"
        self._logged_in = False

    # -----------------------------
    # Helpers
    # -----------------------------
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
        # fallback: remove overlay
        try:
            self.driver.execute_script(
                "var s=['#CybotCookiebotDialog','#CybotCookiebotDialogBodyUnderlay'];"
                "s.forEach(function(x){document.querySelectorAll(x).forEach(function(e){e.remove();});});"
                "document.body.style.overflow='auto';"
            )
        except Exception:
            pass

    def _click_by_text(self, texts: list[str]) -> bool:
        """Try click any element that contains one of the provided texts."""
        if not self.driver:
            return False
        lowered = [t.lower() for t in texts]
        # Try XPath exact-ish
        for t in texts:
            try:
                els = self.driver.find_elements(
                    By.XPATH,
                    f"//*[self::a or self::button or self::div or self::span][contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{t.lower()}')]",
                )
                for el in els:
                    try:
                        if el.is_displayed():
                            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                            time.sleep(0.3)
                            self.driver.execute_script("arguments[0].click();", el)
                            time.sleep(1.2)
                            return True
                    except Exception:
                        continue
            except Exception:
                continue

        # JS fallback: search clickable nodes
        try:
            return bool(
                self.driver.execute_script(
                    """
                    const targets = Array.from(document.querySelectorAll('a,button,[role=tab],[role=button],div,span'))
                      .filter(e => e && e.innerText);
                    const want = arguments[0];
                    for (const el of targets) {
                      const txt = el.innerText.trim().toLowerCase();
                      if (!txt) continue;
                      if (want.some(w => txt === w || txt.includes(w))) {
                        try { el.scrollIntoView({block:'center'}); } catch(e) {}
                        try { el.click(); } catch(e) { try { el.dispatchEvent(new MouseEvent('click', {bubbles:true})); } catch(e2) {} }
                        return true;
                      }
                    }
                    return false;
                    """,
                    lowered,
                )
            )
        except Exception:
            return False

    def _open_product_details(self) -> None:
        """Open Product details panel/accordion."""
        if not self.driver:
            return
        # click tab
        self._click_by_text(["product details", "details", "detalii produs", "detalii"])
        time.sleep(0.8)

        # Expand accordions inside content
        try:
            self.driver.execute_script(
                """
                const acc = Array.from(document.querySelectorAll('[aria-expanded]'));
                for (const a of acc) {
                  const v = a.getAttribute('aria-expanded');
                  if (v === 'false') { try { a.click(); } catch(e) {} }
                }
                """
            )
        except Exception:
            pass
        time.sleep(0.8)

    def _get_details_html(self) -> str:
        """Return HTML for the product details container if possible."""
        if not self.driver:
            return ""
        try:
            html = self.driver.execute_script(
                """
                // best-effort: find heading/button containing 'Product details'
                function findNode(){
                  const nodes = Array.from(document.querySelectorAll('*'))
                    .filter(e => e && e.innerText && e.innerText.trim().toLowerCase() === 'product details');
                  return nodes.length ? nodes[0] : null;
                }
                const h = findNode();
                if (!h) return '';
                // container: walk up a bit
                let c = h;
                for (let i=0; i<6 && c; i++) {
                  if (c.querySelector && (c.querySelector('table') || c.querySelector('dl') || c.querySelector('[class*=description]'))) {
                    return c.outerHTML;
                  }
                  c = c.parentElement;
                }
                // fallback: nearest main content
                const main = document.querySelector('main') || document.querySelector('[role=main]') || document.body;
                return main ? main.innerHTML : '';
                """
            )
            return html or ""
        except Exception:
            return ""

    def _login_if_needed(self):
        if self._logged_in:
            return
        print("XD SCRAPER VERSION:", XD_SCRAPER_VERSION)
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
            email_el = None
            for sel in email_selectors:
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
            for sel in ["form button[type='submit']", "button[type='submit']"]:
                try:
                    for btn in self.driver.find_elements(By.CSS_SELECTOR, sel):
                        if btn.is_displayed():
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

    # -----------------------------
    # Main scrape
    # -----------------------------
    def scrape(self, url: str) -> dict | None:
        try:
            self._login_if_needed()
            self._init_driver()
            if not self.driver:
                return None

            st.info(f"📦 XD v6.0: {url[:70]}...")
            self.driver.get(url)
            time.sleep(6)
            self._dismiss_cookie_banner()

            # light scroll to trigger lazy content
            for frac in [0.25, 0.55, 0.85, 1.0, 0.0]:
                self.driver.execute_script(
                    "window.scrollTo(0, document.body.scrollHeight*arguments[0]);",
                    frac,
                )
                time.sleep(0.7)

            # Open Product details (key)
            self._open_product_details()

            # Screenshot debug (optional)
            try:
                ss = self.driver.get_screenshot_as_png()
                st.image(ss, caption="XD pagina produs", width=700)
            except Exception:
                pass

            raw_text = ""
            try:
                raw_text = self.driver.execute_script("return document.body.innerText || '';")
            except Exception:
                raw_text = ""

            # Keep your visible debug box small
            try:
                st.text_area("DEBUG: Text vizibil pe pagină", (raw_text or "")[:2000], height=200)
            except Exception:
                pass

            page_source = self.driver.page_source
            soup = BeautifulSoup(page_source, "html.parser")

            # Name
            name = (soup.select_one("h1").get_text(strip=True) if soup.select_one("h1") else "")
            if not name:
                name = "Produs XD Connects"

            # SKU
            sku = ""
            im = re.search(r"Item\s*no\.?\s*:?\s*([A-Z0-9.]+)", page_source, re.IGNORECASE)
            if im:
                sku = im.group(1).upper()
            if not sku:
                sm = re.search(r"([pP]\d{3}\.\d{2,3})", url)
                if sm:
                    sku = sm.group(1).upper()

            # Price (EUR/RON)
            price = 0.0
            currency = "EUR"
            try:
                price_info = self.driver.execute_script(
                    """
                    const body = document.body.innerText || '';
                    const res = {price:'', currency:''};
                    let m = body.match(/(?:From\s+)?(\d{1,6}[.,]\d{2})\s*RON/i);
                    if (m) { res.price=m[1]; res.currency='RON'; return res; }
                    m = body.match(/(?:From\s+)?[€]\s*(\d{1,6}[.,]\d{2})/);
                    if (m) { res.price=m[1]; res.currency='EUR'; return res; }
                    m = body.match(/(?:From\s+)?(\d{1,6}[.,]\d{2})\s*EUR/i);
                    if (m) { res.price=m[1]; res.currency='EUR'; return res; }
                    m = body.match(/(?:From\s+)?(\d{1,6}[.,]\d{2})/);
                    if (m) { res.price=m[1]; res.currency='EUR'; return res; }
                    return res;
                    """
                )
                if price_info and price_info.get("price"):
                    price = clean_price(str(price_info.get("price")))
                    currency = price_info.get("currency", "EUR")
            except Exception:
                pass

            if price <= 0:
                for pattern, cur in [
                    (r"(\d{1,6}[.,]\d{2})\s*RON", "RON"),
                    (r"[€]\s*(\d{1,6}[.,]\d{2})", "EUR"),
                    (r"(\d{1,6}[.,]\d{2})\s*EUR", "EUR"),
                ]:
                    pm = re.search(pattern, page_source, re.IGNORECASE)
                    if pm:
                        price = clean_price(pm.group(1))
                        currency = cur
                        break

            st.info(f"💰 PREȚ: {price} {currency}")

            # --- Product details extraction (HTML + text)
            details_html = self._get_details_html()
            details_soup = BeautifulSoup(details_html or "", "html.parser")

            # Description: prefer row labeled Description inside Product details
            description_text = ""
            # Try table rows
            for row in details_soup.select("tr"):
                cells = row.find_all(["th", "td"])
                if len(cells) >= 2:
                    k = cells[0].get_text(" ", strip=True)
                    v = cells[1].get_text(" ", strip=True)
                    if k and v and k.strip().lower() == "description":
                        description_text = v.strip()
                        break

            if not description_text:
                # Try definition list
                dts = details_soup.find_all("dt")
                for dt in dts:
                    if dt.get_text(" ", strip=True).strip().lower() == "description":
                        dd = dt.find_next_sibling("dd")
                        if dd:
                            description_text = dd.get_text(" ", strip=True).strip()
                            break

            if not description_text:
                # fallback: meta description
                meta = soup.select_one('meta[name="description"]')
                if meta and meta.get("content"):
                    description_text = meta.get("content").strip()

            description = ""
            if description_text:
                description = f"<p>{description_text}</p>"

            st.info(f"📝 DESC: {len(description)} car")

            # Specifications: parse key/value pairs from Product details container
            specifications: dict[str, str] = {}

            # Primary attempt: table key/value rows, skip pricing table
            for row in details_soup.select("tr"):
                cells = row.find_all(["th", "td"])
                if len(cells) >= 2:
                    k = cells[0].get_text(" ", strip=True)
                    v = cells[1].get_text(" ", strip=True)
                    if not k or not v:
                        continue
                    kl = k.strip().lower()
                    # skip pricing table headers
                    if kl in {"quantity", "printed*", "plain"}:
                        continue
                    if "€" in v or "ron" in v.lower():
                        # still allow if it's a spec row like "CO2-eq" etc.
                        pass
                    # flatten Product USPs lists
                    if kl == "product usps":
                        v = " ".join(v.split())
                    specifications[k.strip()] = v.strip()

            # Secondary: dl dt/dd
            if not specifications:
                for dt in details_soup.find_all("dt"):
                    dd = dt.find_next_sibling("dd")
                    if not dd:
                        continue
                    k = dt.get_text(" ", strip=True)
                    v = dd.get_text(" ", strip=True)
                    if k and v:
                        specifications[k.strip()] = v.strip()

            # Always include Item no.
            if sku and "Item no." not in specifications:
                specifications["Item no."] = sku

            # ---- Colors
            colors: list[str] = []

            # Try swatches (sometimes hidden)
            try:
                swatches = self.driver.find_elements(By.CSS_SELECTOR, "[data-testid*='colour'], [class*='swatch'], [class*='color']")
                # Not reliable; keep minimal
                _ = swatches
            except Exception:
                pass

            specs_dict = _specs_to_dict(specifications)
            detected_color = None
            for key in ("Colour", "Color", "Culoare"):
                if key in specs_dict and specs_dict[key]:
                    detected_color = specs_dict[key].strip()
                    break
            if not detected_color:
                detected_color = _extract_colour_from_text(raw_text)
            if detected_color:
                colors = [detected_color]

            st.info(f"🎨 CULORI: {len(colors)} = {colors}")

            # ---- Images
            images: list[str] = []
            try:
                # collect from img tags
                for img in soup.select("img"):
                    src = img.get("src") or img.get("data-src") or ""
                    if not src:
                        continue
                    if any(x in src.lower() for x in ["logo", "sprite", "icon", "data:image"]):
                        continue
                    images.append(make_absolute_url(src, self.base_url))

                # background-image
                style_elems = soup.select("*[style*​='background'] , *[style*='background-image']")
                for el in style_elems:
                    style = el.get("style", "")
                    m = re.search(r"background-image\s*:\s*url\(['\"]?([^'\")]+)", style)
                    if m:
                        images.append(make_absolute_url(m.group(1), self.base_url))

                # de-dup keep order
                seen = set()
                images2 = []
                for u in images:
                    if u not in seen:
                        seen.add(u)
                        images2.append(u)
                images = images2
            except Exception:
                pass

            st.info(f"📸 Total img pe pagină: {len(soup.select('img'))}, extrase: {len(images)}")
            if images:
                st.info(f"📸 IMG: {len(images)} ex: {images[0][:80]}...")

            # Build product
            return {
                "name": name,
                "sku": sku,
                "price": price,
                "currency": currency,
                "description": description,
                "specifications": specifications,
                "colors": colors,
                "images": images,
                "source_url": url,
            }

        except Exception as e:
            st.error(f"❌ XD scrape error: {str(e)[:200]}")
            return None
