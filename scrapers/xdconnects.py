"""
XD Connects scraper (Selenium).

Goals:
- Login (if credentials provided)
- Extract: title, sku, price, description, specifications, colors, images
- Robust against XD's JS-driven tabs/accordions.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
    WebDriverException,
)

# If your project has a shared logger, replace prints with logger.*
def _log(msg: str) -> None:
    print(msg)


XD_SCRAPER_VERSION = "2026-02-17-xdconnects-full"


# -----------------------------
# Helpers
# -----------------------------
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _as_float_price(value: str) -> Optional[float]:
    """Parse price like "€ 73,80" or "73.8"."""
    if not value:
        return None
    txt = value.replace("\xa0", " ")
    txt = re.sub(r"[^\d,\.]", "", txt)
    if not txt:
        return None
    if "," in txt and "." in txt:
        if txt.rfind(",") > txt.rfind("."):
            txt = txt.replace(".", "").replace(",", ".")
        else:
            txt = txt.replace(",", "")
    else:
        if "," in txt and "." not in txt:
            txt = txt.replace(",", ".")
    try:
        return float(txt)
    except ValueError:
        return None


def _dedupe_preserve(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for x in items:
        x = (x or "").strip()
        if not x:
            continue
        key = x.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(x)
    return out


def _specs_to_dict(specs: Union[Dict[str, str], List[Tuple[str, str]], None]) -> Dict[str, str]:
    if specs is None:
        return {}
    if isinstance(specs, dict):
        return {str(k).strip(): str(v).strip() for k, v in specs.items() if str(k).strip()}
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
    m = re.search(r"\bColour\b\s*[:\t ]+\s*([^\n\r\t]+)", raw_text, flags=re.IGNORECASE)
    if m:
        val = m.group(1).strip()
        val = re.split(r"\s{2,}|\t|•|\|", val)[0].strip()
        if 1 <= len(val) <= 40:
            return val
    m = re.search(r"Item no\.\s*[A-Z0-9\.]+\s*\n([A-Za-z][A-Za-z \-]{2,40})\n", raw_text)
    if m:
        return m.group(1).strip()
    m = re.search(r"\bColour:\s*\n?([A-Za-z][A-Za-z \-]{2,40})\b", raw_text, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def _safe_click(driver: WebDriver, el) -> bool:
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.1)
        el.click()
        return True
    except (ElementClickInterceptedException, StaleElementReferenceException, WebDriverException):
        try:
            driver.execute_script("arguments[0].click();", el)
            return True
        except Exception:
            return False


def _click_by_text(driver: WebDriver, texts: List[str], timeout: int = 6) -> bool:
    for t in texts:
        if not t:
            continue
        xpath = f"//*[self::button or self::a or self::span or self::div][normalize-space()='{t}']"
        try:
            el = WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.XPATH, xpath)))
            if el and el.is_displayed():
                if _safe_click(driver, el):
                    return True
        except TimeoutException:
            continue
    for t in texts:
        if not t:
            continue
        tt = t.strip()
        if not tt:
            continue
        xpath = (
            "//*[self::button or self::a or self::span or self::div]"
            "[contains(translate(normalize-space(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), "
            f"'{tt.lower()}')]"
        )
        try:
            el = WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.XPATH, xpath)))
            if el and el.is_displayed():
                if _safe_click(driver, el):
                    return True
        except TimeoutException:
            continue
    return False


def _wait_dom_stable(seconds: float = 0.8) -> None:
    time.sleep(seconds)


def _extract_images(driver: WebDriver, base_url: str) -> List[str]:
    urls: List[str] = []
    try:
        imgs = driver.find_elements(By.CSS_SELECTOR, "img")
    except Exception:
        imgs = []
    for img in imgs:
        try:
            src = img.get_attribute("src") or ""
            data_src = img.get_attribute("data-src") or ""
            cand = src or data_src
            if not cand or "data:image" in cand:
                continue
            if "/product/image/" in cand:
                urls.append(cand if cand.startswith("http") else base_url.rstrip("/") + cand)
        except Exception:
            continue
    return _dedupe_preserve(urls)


def _parse_details_text(details_text: str) -> Tuple[str, List[Tuple[str, str]]]:
    lines = [l.strip() for l in (details_text or "").splitlines()]
    lines = [l for l in lines if l]
    specs: List[Tuple[str, str]] = []
    desc = ""

    if "Description" in lines:
        i = lines.index("Description")
        desc_parts = []
        for j in range(i + 1, len(lines)):
            if lines[j] in {"Product USPs", "Primary specifications", "Specifications", "Sustainability", "ESG Features"}:
                break
            desc_parts.append(lines[j])
        desc = _clean(" ".join(desc_parts))

    skip_headers = {"Product details", "Primary specifications", "Product USPs", "ESG Features", "Documentation"}
    i = 0
    while i < len(lines) - 1:
        key = lines[i]
        val = lines[i + 1]
        if key in skip_headers:
            i += 1
            continue
        if key == "Product USPs":
            usp_parts = []
            k = i + 1
            while k < len(lines) and lines[k] not in {"Primary specifications", "ESG Features", "Documentation"}:
                usp_parts.append(lines[k])
                k += 1
            usp = _clean(" ".join(usp_parts))
            if usp:
                specs.append(("Product USPs", usp))
            i = k
            continue
        if key == "Primary specifications":
            k = i + 1
            while k < len(lines):
                line = lines[k]
                parts = re.split(r"\s{2,}|\t", line)
                parts = [p.strip() for p in parts if p.strip()]
                if len(parts) >= 2:
                    if len(parts) % 2 == 0:
                        for p_i in range(0, len(parts), 2):
                            specs.append((parts[p_i], parts[p_i + 1]))
                    else:
                        specs.append((parts[0], _clean(" ".join(parts[1:]))))
                k += 1
            break
        if re.search(r"[A-Za-z]", key) and val not in skip_headers:
            specs.append((key, val))
            i += 2
            continue
        i += 1

    # dedupe keys
    out: List[Tuple[str, str]] = []
    seen = set()
    for k, v in specs:
        ks = _clean(k)
        vs = _clean(v)
        if not ks or not vs:
            continue
        if ks in seen:
            continue
        seen.add(ks)
        out.append((ks, vs))

    return desc, out


def _get_product_details_text(driver: WebDriver) -> str:
    _click_by_text(driver, ["Product details", "Product Details", "Details"], timeout=4)
    _wait_dom_stable(0.8)

    try:
        heading = driver.find_element(By.XPATH, "//*[normalize-space()='Product details' or normalize-space()='Product Details']")
        parent = heading.find_element(By.XPATH, "./ancestor::*[self::section or self::div][1]")
        txt = parent.text or ""
        if txt and len(txt) > 50:
            return txt
    except Exception:
        pass

    try:
        panels = driver.find_elements(By.CSS_SELECTOR, "[role='tabpanel'], .tab-content, .tabs-content")
        for p in panels:
            try:
                txt = p.text or ""
                if "Description" in txt and len(txt) > 80:
                    return txt
            except Exception:
                continue
    except Exception:
        pass

    try:
        return driver.find_element(By.TAG_NAME, "body").text or ""
    except Exception:
        return ""


# -----------------------------
# Data model
# -----------------------------
@dataclass
class XDProduct:
    url: str
    title: str
    sku: str
    price_eur: Optional[float]
    description: str
    specs: List[Tuple[str, str]]
    colors: List[str]
    images: List[str]


class XDConnectsScraper:
    def __init__(self, driver: WebDriver, base_url: str = "https://www.xdconnects.com"):
        self.driver = driver
        self.base_url = base_url.rstrip("/")

    def login(self, username: str, password: str) -> bool:
        _log("🔐 XD: Mă conectez...")
        try:
            self.driver.get(self.base_url + "/en-gb/login")
            WebDriverWait(self.driver, 12).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        except Exception:
            pass
        try:
            email_in = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='email'], input[name*='email'], input#email"))
            )
            pass_in = self.driver.find_element(By.CSS_SELECTOR, "input[type='password'], input[name*='pass'], input#password")
            email_in.clear(); email_in.send_keys(username)
            pass_in.clear(); pass_in.send_keys(password)

            btns = self.driver.find_elements(By.CSS_SELECTOR, "button[type='submit'], button")
            clicked = False
            for b in btns:
                txt = (b.text or "").lower()
                if "login" in txt or "sign in" in txt or b.get_attribute("type") == "submit":
                    if _safe_click(self.driver, b):
                        clicked = True
                        break
            if not clicked:
                pass_in.submit()

            WebDriverWait(self.driver, 12).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            _wait_dom_stable(1.0)
            _log("✅ XD: Login reușit!")
            return True
        except Exception as e:
            _log(f"⚠️ XD: Login posibil nereușit / deja logat. Detalii: {e}")
            return False

    def scrape_product(self, url: str) -> XDProduct:
        _log(f"📦 XD v5.0: {url[:80]}...")
        self.driver.get(url)
        WebDriverWait(self.driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        _wait_dom_stable(1.2)

        try:
            raw_text = self.driver.find_element(By.TAG_NAME, "body").text or ""
        except Exception:
            raw_text = ""

        # title
        title = ""
        for sel in ["h1", "h1 span", "h1.product-title"]:
            try:
                title = _clean(self.driver.find_element(By.CSS_SELECTOR, sel).text)
                if title:
                    break
            except Exception:
                continue
        if not title and raw_text:
            title = _clean(raw_text.splitlines()[0])

        # sku
        sku = ""
        m = re.search(r"Item no\.\s*([A-Z0-9\.]+)", raw_text)
        if m:
            sku = m.group(1).strip()

        # price
        price_eur: Optional[float] = None
        m = re.search(r"Price\s*€\s*([0-9\.,]+)", raw_text)
        if m:
            price_eur = _as_float_price(m.group(1))
        if price_eur is None:
            m = re.search(r"€\s*([0-9\.,]+)", raw_text)
            if m:
                price_eur = _as_float_price(m.group(1))

        # details
        details_text = _get_product_details_text(self.driver)
        description, specs = _parse_details_text(details_text)

        if not description:
            m = re.search(r"Description\s+(.+?)(?:Product USPs|Primary specifications|ESG Features|Documentation|$)", raw_text, flags=re.S)
            if m:
                description = _clean(m.group(1))

        # colors
        colors: List[str] = []
        colors = _dedupe_preserve(colors)

        if not colors:
            specs_dict = _specs_to_dict(specs)
            for key in ["Colour", "Color", "Culoare"]:
                if key in specs_dict and specs_dict[key]:
                    colors = [specs_dict[key].strip()]
                    break

        if not colors:
            c = _extract_colour_from_text(raw_text)
            if c:
                colors = [c]

        colors = _dedupe_preserve(colors)

        images = _extract_images(self.driver, self.base_url)

        _log(f"💰 PREȚ: {price_eur} EUR")
        _log(f"📝 DESC: {len(description or '')} car")
        _log(f"📋 SPECS: {len(specs)} = {specs[:3] if specs else []}")
        _log(f"🎨 CULORI: {len(colors)} = {colors}")
        try:
            _log(f"📸 Total img pe pagină: {len(self.driver.find_elements(By.CSS_SELECTOR, 'img'))}, extrase: {len(images)}")
        except Exception:
            _log(f"📸 extrase: {len(images)}")
        if images:
            _log(f"📸 IMG: {len(images)} ex: {images[0][:90]}...")

        return XDProduct(
            url=url,
            title=title,
            sku=sku,
            price_eur=price_eur,
            description=description,
            specs=specs,
            colors=colors,
            images=images,
        )
"""

with zipfile.ZipFile(out_zip, 'w', zipfile.ZIP_DEFLATED) as z:
    z.writestr(py_path_in_zip, code)

out_zip, os.path.getsize(out_zip)
