# scrapers/xdconnects.py
# XD Connects Scraper v5.4
# Fixes:
# - Robust price parsing (EUR/RON) (no syntax issues)
# - Robust Description + Specifications extraction (HTML + visible text + hidden DOM textContent)
# - Color extraction: default color + (when available) all color variants (variantId list)
# - Specs filtering (remove pricing table noise: Quantity/Printed/Plain)

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from scrapers.base_scraper import BaseScraper
from utils.helpers import clean_price
from utils.image_handler import make_absolute_url


XD_SCRAPER_VERSION = "2026-02-17-xd-v5.4"


def _specs_to_dict(specs: Any) -> Dict[str, str]:
    """Normalize specs into dict."""
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

    # 1) "Colour: xxx" or in table columns
    m = re.search(r"\bColour\b\s*[:\t ]+\s*([^\n\r\t]+)", raw_text, flags=re.IGNORECASE)
    if m:
        val = m.group(1).strip()
        val = re.split(r"\s{2,}|\t|•|\|", val)[0].strip()
        if 1 <= len(val) <= 40:
            return val

    # 2) after "Item no. Pxxx" the next line is often the color
    m = re.search(r"Item no\.\s*[A-Z0-9\.]+\s*\n([A-Za-z][A-Za-z \-]{2,40})\n", raw_text)
    if m:
        return m.group(1).strip()

    return None


def _parse_product_details_from_text(raw_text: str) -> Tuple[str, Dict[str, str]]:
    """Parse Product details section from text (works when the site renders details as text)."""
    if not raw_text:
        return "", {}

    txt = raw_text.replace("\r", "\n")
    idx = txt.lower().find("product details")
    if idx != -1:
        txt = txt[idx : idx + 12000]

    txt = re.sub(r"[ \t]+\n", "\n", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt).strip()

    lines = [ln.strip() for ln in txt.split("\n") if ln.strip()]
    specs: Dict[str, str] = {}

    i = 0
    while i < len(lines):
        ln = lines[i]

        if ln.lower() in {"login", "register", "privacy policy"}:
            break

        # Key  Value (2+ spaces) or Key\tValue
        m = re.match(r"^([A-Za-z][A-Za-z0-9 \-/®™’']{1,60})\s{2,}(.+)$", ln)
        if not m:
            m = re.match(r"^([A-Za-z][A-Za-z0-9 \-/®™’']{1,60})\t+(.+)$", ln)

        if m:
            key = m.group(1).strip()
            val = m.group(2).strip()

            # Product USPs often continues on multiple lines
            if key.lower() == "product usps":
                vals = []
                if val:
                    vals.append(val)
                j = i + 1
                while j < len(lines):
                    nxt = lines[j]
                    if re.match(r"^[A-Za-z].{0,60}\s{2,}.+$", nxt) or re.match(
                        r"^[A-Za-z].{0,60}\t+.+$", nxt
                    ):
                        break
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

        # Description sometimes: "Description <text>" on same line
        if ln.lower().startswith("description"):
            desc = ln[len("description") :].strip(" :\t")
            if not desc:
                vals = []
                j = i + 1
                while j < len(lines):
                    nxt = lines[j]
                    if re.match(r"^[A-Za-z].{0,60}\s{2,}.+$", nxt) or re.match(
                        r"^[A-Za-z].{0,60}\t+.+$", nxt
                    ):
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

    return specs.get("Description", ""), specs


def _parse_product_details_from_html(soup: BeautifulSoup) -> Tuple[str, Dict[str, str]]:
    """Parse details from DOM (includes hidden elements)."""
    specs: Dict[str, str] = {}
    if not soup:
        return "", specs

    # tables
    for table in soup.select("table"):
        for row in table.select("tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) >= 2:
                k = cells[0].get_text(" ", strip=True)
                v = cells[1].get_text(" ", strip=True)
                if k and v and len(k) <= 80:
                    specs[k.strip()] = v.strip()

    # dl/dt/dd
    for dl in soup.select("dl"):
        for dt in dl.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            if not dd:
                continue
            k = dt.get_text(" ", strip=True)
            v = dd.get_text(" ", strip=True)
            if k and v and len(k) <= 80:
                specs[k.strip()] = v.strip()

    # Explicit keys sometimes exist
    for key in ("Description", "Item no.", "Product USPs", "CO2-eq", "Colour"):
        if key in specs:
            continue
        node = soup.find(
            lambda tag: tag.name in {"div", "span", "p", "strong", "th", "td"}
            and tag.get_text(" ", strip=True) == key
        )
        if node:
            sib = node.find_next_sibling()
            if sib:
                v = sib.get_text(" ", strip=True)
                if v and v.lower() != key.lower():
                    specs[key] = v

    return specs.get("Description", ""), specs


def _filter_specs(specs: Dict[str, str]) -> Dict[str, str]:
    """Remove noisy keys user doesn't want."""
    blacklist_exact = {
        "Quantity",
        "Printed*",
        "Plain",
        "Recommended sales price",
        "From",
        "Price",
    }
    blacklist_prefix = (
        "Quantity",
        "Printed",
        "Plain",
        "Recommended",
    )
    cleaned: Dict[str, str] = {}
    for k, v in (specs or {}).items():
        ks = str(k).strip()
        if not ks:
            continue
        if ks in blacklist_exact:
            continue
        if any(ks.startswith(p) for p in blacklist_prefix):
            continue
        cleaned[ks] = str(v).strip()
    return cleaned


def _extract_variant_ids_and_names(soup: BeautifulSoup, current_variant: str) -> List[Dict[str, str]]:
    """Try to extract all color variants from DOM (variantId + label)."""
    variants: List[Dict[str, str]] = []
    if not soup:
        return variants

    candidates: List[Tuple[str, Any]] = []
    for a in soup.select("a[href*='variantId=']"):
        href = a.get("href") or ""
        m = re.search(r"variantId=([A-Z0-9\.]+)", href, re.IGNORECASE)
        if m:
            candidates.append((m.group(1).upper(), a))
    for el in soup.select("*[data-variantid], *[data-variant-id]"):
        vid = (el.get("data-variantid") or el.get("data-variant-id") or "").strip()
        if vid:
            candidates.append((vid.upper(), el))

    seen = set()
    for vid, el in candidates:
        if vid in seen:
            continue
        seen.add(vid)
        label = (
            (el.get("aria-label") or "").strip()
            or (el.get("title") or "").strip()
            or el.get_text(" ", strip=True)
        )
        label = re.sub(r"\s{2,}", " ", label).strip()
        if not label or len(label) > 60:
            label = vid
        variants.append({"variantId": vid, "name": label})

    if not variants and current_variant:
        variants = [{"variantId": current_variant, "name": current_variant}]
    return variants


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
                    time.sleep(1.0)
                    return
            except NoSuchElementException:
                continue
            except Exception:
                continue
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
            for sel in ["input[name='email']", "input[type='email']"]:
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

            # password
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

    def scrape(self, url: str) -> dict | None:
        try:
            self._login_if_needed()
            self._init_driver()
            if not self.driver:
                return None

            st.info(f"📦 XD v5.4: {url[:70]}...")
            self.driver.get(url)
            time.sleep(6)
            self._dismiss_cookie_banner()

            try:
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight*0.6);")
            except Exception:
                pass
            time.sleep(0.8)

            try:
                st.image(self.driver.get_screenshot_as_png(), caption="XD pagina produs", width=700)
            except Exception:
                pass

            try:
                raw_text = self.driver.execute_script("return document.body.innerText || ''; ") or ""
            except Exception:
                raw_text = ""
            page_source = self.driver.page_source or ""
            soup = BeautifulSoup(page_source, "html.parser")

            try:
                st.text_area("DEBUG: Text vizibil pe pagină", raw_text[:2000], height=200)
            except Exception:
                pass

            # Name
            name = ""
            h1 = soup.select_one("h1")
            if h1:
                name = h1.get_text(strip=True)
            if not name:
                for ln in raw_text.split("\n"):
                    ln = ln.strip()
                    if ln and len(ln) < 120:
                        name = ln
                        break
            if not name:
                name = "Produs XD Connects"

            # SKU
            sku = ""
            vm = re.search(r"variantId=([A-Z0-9\.]+)", url, re.IGNORECASE)
            if vm:
                sku = vm.group(1).upper()
            if not sku:
                im = re.search(r"Item\s*no\.?\s*:??\s*([A-Z0-9\.]+)", raw_text, re.IGNORECASE)
                if im:
                    sku = im.group(1).upper()

            # Price
            price = 0.0
            currency = "EUR"
            try:
                body = raw_text
                m = re.search(r"\bPrice\b\s*€\s*(\d{1,6}(?:[\.,]\d{1,2})?)", body, re.IGNORECASE)
                if not m:
                    m = re.search(r"€\s*(\d{1,6}(?:[\.,]\d{1,2})?)", body)
                if m:
                    price = clean_price(m.group(1))
                    currency = "EUR"
                else:
                    m = re.search(r"(\d{1,6}(?:[\.,]\d{1,2})?)\s*RON", body, re.IGNORECASE)
                    if m:
                        price = clean_price(m.group(1))
                        currency = "RON"
            except Exception:
                pass
            st.info(f"💰 PREȚ: {price} {currency}")

            # Details
            description_text, specifications = _parse_product_details_from_html(soup)
            if not specifications:
                description_text, specifications = _parse_product_details_from_text(raw_text)
            if not specifications:
                try:
                    dom_text = self.driver.execute_script(
                        """
                        const els = Array.from(document.querySelectorAll('body *'));
                        const parts = [];
                        for (const e of els) {
                          const t = (e.textContent||'').trim();
                          if (!t) continue;
                          if (t.includes('Item no.') && t.includes('Description')) parts.push(t);
                          if (t.includes('Product USPs') && t.includes('Description')) parts.push(t);
                          if (t.includes('Primary specifications') && t.includes('CO2')) parts.push(t);
                          if (parts.length >= 25) break;
                        }
                        return parts.join('\\n');
                        """
                    ) or ""
                    if dom_text:
                        d2, s2 = _parse_product_details_from_text(dom_text)
                        if s2:
                            description_text, specifications = d2, s2
                except Exception:
                    pass

            specifications = _specs_to_dict(specifications)
            if sku and "Item no." not in specifications:
                specifications["Item no."] = sku
            specifications = _filter_specs(specifications)

            description = f"<p>{description_text}</p>" if description_text else ""
            st.info(f"📝 DESC: {len(description)} car")
            st.info(f"📋 SPECS: {len(specifications)}")

            # Color(s)
            detected_color = None
            for key in ("Colour", "Color", "Culoare"):
                if specifications.get(key):
                    detected_color = specifications[key].strip()
                    break
            if not detected_color:
                detected_color = _extract_colour_from_text(raw_text)
            colors = [detected_color] if detected_color else []

            # Variants
            color_variants = _extract_variant_ids_and_names(soup, sku)
            if detected_color and color_variants:
                for v in color_variants:
                    if v.get("variantId") == sku:
                        v["name"] = detected_color
                        break

            st.info(f"🎨 CULORI: {len(colors)} = {colors}")
            if color_variants and len(color_variants) > 1:
                st.info(f"🎨 VARIANTE: {len(color_variants)}")

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

                for el in soup.select("*[style*='background-image']"):
                    style = el.get("style", "")
                    m = re.search(r"background-image\s*:\s*url\(['\"]?([^'\")]+)", style)
                    if m:
                        images.append(make_absolute_url(m.group(1), self.base_url))

                seen = set()
                images2 = []
                for u in images:
                    if u not in seen:
                        seen.add(u)
                        images2.append(u)
                images = images2
            except Exception:
                pass

            return {
                "name": name,
                "sku": sku,
                "price": price,
                "currency": currency,
                "description": description,
                "specifications": specifications,
                "colors": colors,
                "color_variants": color_variants,
                "images": images,
                "source_url": url,
            }
        except Exception as e:
            st.warning(f"⚠️ XD scrape error: {str(e)[:160]}")
            return None
