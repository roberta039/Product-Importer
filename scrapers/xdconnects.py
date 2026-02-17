# scrapers/xdconnects.py
# XD Connects Scraper v5.2 (no-tab-click, robust)
# Goals:
# - Stay on product page (avoid mis-click navigation)
# - Extract Description + Specifications reliably from page text/HTML
# - Color fallback (from specs or raw text)
# - Images extraction

import re
import time
from typing import Any, Dict, List, Optional

import streamlit as st
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from scrapers.base_scraper import BaseScraper
from utils.helpers import clean_price
from utils.image_handler import make_absolute_url

XD_SCRAPER_VERSION = "2026-02-17-xd-v5.2-no-tab-click"


def _specs_to_dict(specs: Any) -> Dict[str, str]:
    if isinstance(specs, dict):
        return {str(k).strip(): str(v).strip() for k, v in specs.items()}
    d: Dict[str, str] = {}
    try:
        for k, v in specs:
            ks = str(k).strip()
            vs = str(v).strip()
            if ks:
                d[ks] = vs
    except Exception:
        pass
    return d


def _extract_colour_from_text(raw_text: str) -> Optional[str]:
    if not raw_text:
        return None

    # 1) "Colour <value>" (often in Primary specifications)
    m = re.search(r"\bColour\b\s*[:\t ]+\s*([^\n\r\t]+)", raw_text, flags=re.IGNORECASE)
    if m:
        val = m.group(1).strip()
        val = re.split(r"\s{2,}|\t|•|\|", val)[0].strip()
        if 1 <= len(val) <= 40:
            return val

    # 2) after "Item no."
    m = re.search(r"Item no\.\s*[A-Z0-9\.]+\s*\n([A-Za-z][A-Za-z \-]{2,40})\n", raw_text)
    if m:
        return m.group(1).strip()

    return None


def _parse_product_details_from_text(raw_text: str) -> (str, Dict[str, str]):
    """
    Parse the 'Product details' section from body text.
    Works even when Product details is rendered as plain text (common on XD pages).
    Returns (description_text, specs_dict).
    """
    if not raw_text:
        return "", {}

    # Focus around Product details if present
    txt = raw_text
    # Keep a slice starting at "Product details" if available to reduce noise
    idx = txt.lower().find("product details")
    if idx != -1:
        txt = txt[idx: idx + 8000]

    # Normalize: replace multiple spaces, keep newlines
    txt = txt.replace("\r", "\n")
    txt = re.sub(r"[ \t]+\n", "\n", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt).strip()

    specs: Dict[str, str] = {}

    # Pattern: lines like "Key\tValue" or "Key  Value"
    # We'll scan line by line and also handle multi-line values (e.g., Product USPs list)
    lines = [ln.strip() for ln in txt.split("\n") if ln.strip()]
    i = 0
    while i < len(lines):
        ln = lines[i]

        # stop if we hit footer-ish areas
        if ln.lower() in {"login", "register", "privacy policy"}:
            break

        # Detect a key that is followed by a value on same line separated by tab(s) or multiple spaces
        m = re.match(r"^([A-Za-z][A-Za-z0-9 \-/®™’']{1,40})\s{2,}(.+)$", ln)
        if not m:
            m = re.match(r"^([A-Za-z][A-Za-z0-9 \-/®™’']{1,40})\t+(.+)$", ln)

        if m:
            key = m.group(1).strip()
            val = m.group(2).strip()
            # handle Product USPs: may continue on next lines until next key-ish line
            if key.lower() == "product usps":
                vals = []
                if val:
                    vals.append(val)
                j = i + 1
                while j < len(lines):
                    nxt = lines[j]
                    # heuristically: a new key line often contains a tab or 2+ spaces; also "Primary specifications"
                    if re.match(r"^[A-Za-z].{0,45}\s{2,}.+$", nxt) or re.match(r"^[A-Za-z].{0,45}\t+.+$", nxt) or nxt.lower() in {"primary specifications", "description"}:
                        break
                    # skip headings
                    if nxt.lower() in {"product details", "primary specifications"}:
                        j += 1
                        continue
                    vals.append(nxt)
                    j += 1
                specs[key] = " ".join([v.strip() for v in vals if v.strip()])
                i = j
                continue

            specs[key] = val
            i += 1
            continue

        # Headings
        if ln.lower() in {"primary specifications"}:
            i += 1
            continue

        # Sometimes Description is "Description <text>" on one line without tabs
        if ln.lower().startswith("description"):
            desc = ln[len("description"):].strip(" :\t")
            if not desc:
                # maybe next line(s) contain desc until next key
                vals = []
                j = i + 1
                while j < len(lines):
                    nxt = lines[j]
                    if re.match(r"^[A-Za-z].{0,45}\s{2,}.+$", nxt) or re.match(r"^[A-Za-z].{0,45}\t+.+$", nxt):
                        break
                    if nxt.lower() in {"product usps", "primary specifications"}:
                        break
                    vals.append(nxt)
                    j += 1
                desc = " ".join(vals).strip()
                i = j
            else:
                i += 1
            if desc:
                specs["Description"] = desc
            continue

        i += 1

    description_text = specs.get("Description", "")
    return description_text, specs


class XDConnectsScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.name = "xdconnects"
        self.base_url = "https://www.xdconnects.com"
        self._logged_in = False

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
                    time.sleep(1.2)
                    return
            except NoSuchElementException:
                continue
            except Exception:
                continue
        # fallback: remove overlay if present
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

    def _looks_like_product_page(self, body_text: str, page_source: str) -> bool:
        t = (body_text or "").lower()
        s = (page_source or "").lower()
        return ("item no." in t) or ("item no." in s) or ("from" in t and "price" in t and "€" in t)

    def scrape(self, url: str) -> dict | None:
        try:
            self._login_if_needed()
            self._init_driver()
            if not self.driver:
                return None

            st.info(f"📦 XD v5.2: {url[:70]}...")
            self.driver.get(url)
            time.sleep(6)
            self._dismiss_cookie_banner()

            # Debug current URL (detect redirects)
            try:
                cur = self.driver.current_url
                if cur and cur != url:
                    print("XD DEBUG current_url:", cur)
            except Exception:
                pass

            # Small scroll to trigger lazy content without aggressive clicks
            for frac in [0.35, 0.8, 0.0]:
                try:
                    self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight*arguments[0]);", frac)
                except Exception:
                    pass
                time.sleep(0.7)

            # Optional screenshot
            try:
                ss = self.driver.get_screenshot_as_png()
                st.image(ss, caption="XD pagina produs", width=700)
            except Exception:
                pass

            # Get raw text + HTML
            try:
                raw_text = self.driver.execute_script("return document.body.innerText || '';") or ""
            except Exception:
                raw_text = ""

            page_source = self.driver.page_source or ""
            soup = BeautifulSoup(page_source, "html.parser")

            # If we got redirected to a non-product page, retry once (sometimes session/cookies settle)
            if not self._looks_like_product_page(raw_text, page_source):
                print("XD WARNING: page does not look like product page, retrying once...")
                self.driver.get(url)
                time.sleep(6)
                self._dismiss_cookie_banner()
                try:
                    raw_text = self.driver.execute_script("return document.body.innerText || '';") or ""
                except Exception:
                    raw_text = raw_text or ""
                page_source = self.driver.page_source or ""
                soup = BeautifulSoup(page_source, "html.parser")

            try:
                st.text_area("DEBUG: Text vizibil pe pagină", (raw_text or "")[:2000], height=200)
            except Exception:
                pass

            # Name
            h1 = soup.select_one("h1")
            name = h1.get_text(strip=True) if h1 else ""
            if not name:
                # fallback: first non-empty title-ish line
                for ln in (raw_text or "").split("\n"):
                    ln = ln.strip()
                    if ln and len(ln) < 120:
                        name = ln
                        break
            if not name:
                name = "Produs XD Connects"

            # SKU
            sku = ""
            im = re.search(r"Item\s*no\.?\s*:?\s*([A-Z0-9.]+)", page_source, re.IGNORECASE)
            if im:
                sku = im.group(1).upper()
            if not sku:
                # try from url variantId first
                vm = re.search(r"variantId=([A-Z0-9.]+)", url, re.IGNORECASE)
                if vm:
                    sku = vm.group(1).upper()
            if not sku:
                sm = re.search(r"([pP]\d{3}\.\d{2,3})", url)
                if sm:
                    sku = sm.group(1).upper()

            # Price
            price = 0.0
            currency = "EUR"
            try:
                price_info = self.driver.execute_script(
                    r"""
                    const body = document.body.innerText || '';
                    const res = {price:'', currency:''};
                    let m = body.match(/(?:From\s+)?(\d{1,6}[.,]\d{2})\s*RON/i);
                    if (m) { res.price=m[1]; res.currency='RON'; return res; }
                    m = body.match(/(?:From\s+)?[€]\s*(\d{1,6}[.,]\d{2})/);
                    if (m) { res.price=m[1]; res.currency='EUR'; return res; }
                    m = body.match(/(?:From\s+)?(\d{1,6}[.,]\d{2})\s*EUR/i);
                    if (m) { res.price=m[1]; res.currency='EUR'; return res; }
                    return res;
                    """
                )
                if price_info and price_info.get("price"):
                    price = clean_price(str(price_info.get("price")))
                    currency = price_info.get("currency", "EUR")
            except Exception:
                pass

            st.info(f"💰 PREȚ: {price} {currency}")

            # Product details: parse from raw text first (most reliable)
            description_text, specifications = _parse_product_details_from_text(raw_text)

            # If empty, try HTML tables as fallback
            if not specifications:
                # look for a table that has 'Description' row
                for table in soup.select("table"):
                    rows = table.select("tr")
                    for row in rows:
                        cells = row.find_all(["th", "td"])
                        if len(cells) >= 2:
                            k = cells[0].get_text(" ", strip=True)
                            v = cells[1].get_text(" ", strip=True)
                            if k and v:
                                specifications[k.strip()] = v.strip()
                description_text = specifications.get("Description", description_text)

            # Always include Item no.
            if sku and "Item no." not in specifications:
                specifications["Item no."] = sku

            description = f"<p>{description_text}</p>" if description_text else ""
            st.info(f"📝 DESC: {len(description)} car")
            st.info(f"📋 SPECS: {len(specifications)}")

            # Colors
            specs_dict = _specs_to_dict(specifications)
            detected_color = None
            for key in ("Colour", "Color", "Culoare"):
                if key in specs_dict and specs_dict[key]:
                    detected_color = specs_dict[key].strip()
                    break
            if not detected_color:
                detected_color = _extract_colour_from_text(raw_text)
            colors = [detected_color] if detected_color else []
            st.info(f"🎨 CULORI: {len(colors)} = {colors}")

            # Images
            images: List[str] = []
            try:
                for img in soup.select("img"):
                    src = img.get("src") or img.get("data-src") or ""
                    if not src:
                        continue
                    if any(x in src.lower() for x in ["logo", "sprite", "icon", "data:image"]):
                        continue
                    images.append(make_absolute_url(src, self.base_url))

                # background-image
                for el in soup.select("*[style*='background-image']"):
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
            st.warning(f"⚠️ XD scrape error: {str(e)[:160]}")
            return None
