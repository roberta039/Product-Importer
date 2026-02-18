# scrapers/xdconnects.py
"""
XD Connects scraper (variants by color)

Goals:
- Extract description + specifications reliably from HTML (even when tabs hide content).
- Discover ALL color variants for a product, and return a LIST of product dicts (one per variant).
- Works with this project's BaseScraper (scrapers/base_scraper.py). Does NOT require get_driver().
"""

import re
import time
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper
from utils.image_handler import make_absolute_url


_VARIANT_ID_RE = re.compile(r"variantId=([A-Za-z0-9\.\-]+)")
# filenames like: p705.70__p705.709__5001.jpg  -> capture p705.709
_FILE_VARIANT_RE = re.compile(r"__([pP]\d+\.\d{3})__")


def _norm_variant(v: str) -> str:
    v = (v or "").strip()
    if not v:
        return ""
    # normalize p705.709 -> P705.709
    if v[0].lower() == "p":
        return "P" + v[1:]
    return v.upper()


def _extract_parent_from_url(url: str) -> str:
    """
    From ...-p705.70?variantId=P705.709 -> P705.70
    """
    m = re.search(r"-p(\d+\.\d+)", url, flags=re.IGNORECASE)
    if not m:
        return ""
    return "P" + m.group(1)


def _set_variant_in_url(url: str, variant_id: str) -> str:
    pr = urlparse(url)
    qs = parse_qs(pr.query)
    qs["variantId"] = [variant_id]
    new_query = urlencode(qs, doseq=True)
    return urlunparse((pr.scheme, pr.netloc, pr.path, pr.params, new_query, pr.fragment))


def _get_body_text(soup: BeautifulSoup) -> str:
    # For hidden/tab content, soup.get_text() can still include it.
    return soup.get_text("\n", strip=True)


def _extract_color_from_text(text: str) -> str:
    """
    Prefer:
      Item no. P705.709\nlight blue\n
    Fallback:
      Colour\tlight blue
    """
    if not text:
        return ""

    m = re.search(r"Item no\.\s*[A-Z0-9\.]+\s*\n([A-Za-z][A-Za-z \-]{2,40})\n", text)
    if m:
        return m.group(1).strip()

    m = re.search(r"\bColour\b\s*[:\t ]+\s*([^\n\r\t]+)", text, flags=re.IGNORECASE)
    if m:
        val = m.group(1).strip()
        val = re.split(r"\s{2,}|\t|•|\|", val)[0].strip()
        if 1 <= len(val) <= 40:
            return val
    return ""


def _extract_description_and_specs(soup: BeautifulSoup) -> tuple[str, dict]:
    """
    Looks for a 'Product details' table-like section where rows are Key/Value.
    We keep a dict of specs and extract the 'Description' field as description.
    """
    specs: dict[str, str] = {}
    desc = ""

    # Many XD pages contain key/value rows in any <table> or <dl> inside "Product details"
    # We'll parse ALL tables and dl blocks and then pick the best keys.
    # TABLES
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if len(cells) >= 2:
                k = cells[0].get_text(" ", strip=True)
                v = cells[1].get_text(" ", strip=True)
                if k and v:
                    specs[k] = v

    # DL blocks
    for dl in soup.find_all("dl"):
        dts = dl.find_all("dt")
        dds = dl.find_all("dd")
        for dt, dd in zip(dts, dds):
            k = dt.get_text(" ", strip=True)
            v = dd.get_text(" ", strip=True)
            if k and v:
                specs[k] = v

    # Description key variants
    for k in list(specs.keys()):
        if k.lower() in ("description", "descriere"):
            desc = specs.get(k, "") or desc

    return desc, specs


def _extract_images(soup: BeautifulSoup, base_url: str) -> list[str]:
    urls = set()

    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        if src and not src.startswith("data:"):
            urls.add(make_absolute_url(src, base_url))

    # background-image urls
    for tag in soup.find_all(style=True):
        style = tag.get("style") or ""
        m = re.findall(r"url\(['\"]?(.*?)['\"]?\)", style, flags=re.IGNORECASE)
        for u in m:
            u = u.strip()
            if u and not u.startswith("data:"):
                urls.add(make_absolute_url(u, base_url))

    # anchors to images
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if any(href.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp")):
            urls.add(make_absolute_url(href, base_url))

    return sorted(urls)


def _discover_variant_ids_from_html(html: str) -> list[str]:
    if not html:
        return []
    vids = set()

    for m in _VARIANT_ID_RE.finditer(html):
        vids.add(_norm_variant(m.group(1)))

    for m in _FILE_VARIANT_RE.finditer(html):
        vids.add(_norm_variant(m.group(1)))

    # sanity filter: keep only Pxxx.xxx (at least one dot)
    vids = {v for v in vids if v.startswith("P") and "." in v and len(v) >= 6}
    return sorted(vids)


class XDConnectsScraper(BaseScraper):
    name = "xdconnects"

    def __init__(self):
        super().__init__()
        self._logged_in = False

    def _ensure_login(self):
        # Uses existing BaseScraper login utilities if present, otherwise does nothing.
        # We keep this minimal; the user already has XD creds in secrets.
        if self._logged_in:
            return

        username = self._get_secret("SOURCES", "XD_USER")
        password = self._get_secret("SOURCES", "XD_PASS")
        if not username or not password:
            # no creds, skip
            self._logged_in = True
            return

        self._init_driver()
        driver = self.driver

        # If already logged in, skip
        try:
            # quick heuristic: account menu present
            driver.get("https://www.xdconnects.com/en-gb/login")
            time.sleep(2)
        except Exception:
            pass

        try:
            # Fill login form (best effort)
            # XD uses standard fields often: input[type=email], input[type=password]
            email_el = driver.find_element("css selector", "input[type='email'], input[name*='email' i], input[id*='email' i]")
            pass_el = driver.find_element("css selector", "input[type='password']")
            email_el.clear()
            email_el.send_keys(username)
            pass_el.clear()
            pass_el.send_keys(password)

            # submit
            btn = driver.find_element("css selector", "button[type='submit'], button[name='login'], input[type='submit']")
            btn.click()
            time.sleep(3)
        except Exception:
            # If login page layout differs, ignore; sometimes product pages are accessible.
            pass

        self._logged_in = True

    def scrape(self, url: str):
        """
        Returns:
          - list[dict] (one per color variant) when variants are discoverable
          - dict for single variant
        """
        self._ensure_login()
        self._init_driver()
        driver = self.driver

        driver.get(url)
        time.sleep(2.5)

        html = driver.page_source or ""
        parent_sku = _extract_parent_from_url(url)
        base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"

        variant_ids = _discover_variant_ids_from_html(html)
        # Always include the requested variantId (if any)
        qs = parse_qs(urlparse(url).query)
        current_vid = _norm_variant((qs.get("variantId") or [""])[0])
        if current_vid:
            if current_vid not in variant_ids:
                variant_ids.insert(0, current_vid)

        # If we still only have 0/1 variant id, return single product dict
        if len(variant_ids) <= 1:
            return self._scrape_single_variant(url, parent_sku=parent_sku)

        # Otherwise, scrape each variant (limit to avoid huge loops)
        max_variants = 30
        variant_ids = variant_ids[:max_variants]

        products = []
        for vid in variant_ids:
            vurl = _set_variant_in_url(url, vid)
            try:
                p = self._scrape_single_variant(vurl, parent_sku=parent_sku, forced_sku=vid)
                products.append(p)
            except Exception as e:
                # Keep going; return partial list
                products.append({
                    "name": "",
                    "sku": vid,
                    "parent_sku": parent_sku,
                    "source_site": "xdconnects",
                    "source_url": vurl,
                    "description": "",
                    "specifications": {},
                    "colors": [],
                    "images": [],
                    "price_eur": 0.0,
                    "error": str(e)[:200],
                })

        # Deduplicate by SKU (some pages repeat same vid)
        seen = set()
        uniq = []
        for p in products:
            sku = (p.get("sku") or "").strip()
            if sku and sku in seen:
                continue
            if sku:
                seen.add(sku)
            uniq.append(p)
        return uniq

    def _scrape_single_variant(self, url: str, parent_sku: str = "", forced_sku: str = "") -> dict:
        self._init_driver()
        driver = self.driver
        driver.get(url)
        time.sleep(2.5)

        html = driver.page_source or ""
        soup = BeautifulSoup(html, "html.parser")
        text = _get_body_text(soup)

        # name
        title = ""
        # Often the h1 contains product name
        h1 = soup.find(["h1", "h2"])
        if h1:
            title = h1.get_text(" ", strip=True)
        if not title:
            # fallback: first strong-ish title in text
            title = (text.split("\n")[0] if text else "").strip()

        desc, specs = _extract_description_and_specs(soup)

        # If description still empty, try to find a "Description" label in body text
        if not desc:
            m = re.search(r"\bDescription\b\s+(.{40,2000})", text, flags=re.IGNORECASE | re.S)
            if m:
                desc = m.group(1).strip()

        # SKU / item no.
        sku = forced_sku.strip() if forced_sku else ""
        if not sku:
            # try "Item no. P705.709" in text
            m = re.search(r"Item no\.\s*([A-Z0-9\.]+)", text)
            if m:
                sku = _norm_variant(m.group(1))

        if not sku:
            # fallback: query param
            qs = parse_qs(urlparse(url).query)
            sku = _norm_variant((qs.get("variantId") or [""])[0])

        color = _extract_color_from_text(text)
        colors = [color] if color else []

        images = _extract_images(soup, base_url=base_url)

        product = {
            "name": title,
            "sku": sku,
            "parent_sku": parent_sku or _extract_parent_from_url(url),
            "source_site": "xdconnects",
            "source_url": url,
            "description": desc,
            "specifications": specs or {},
            "colors": colors,
            "images": images,
            "price_eur": 0.0,  # not required now
        }
        return product
