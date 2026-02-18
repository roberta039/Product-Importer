
import re
import time
from urllib.parse import urlparse, parse_qs

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


class XDConnectsScraper:
    """XD Connects scraper (safe version).
    - Never returns None (app expects dict with .get()).
    - Avoids risky clicks that can navigate away.
    - Extracts: title, sku (variantId), price_eur, description, specs (dict), colors (list), images (list).
    """

    SOURCE = "xdconnects"

    def __init__(self, driver, base_url="https://www.xdconnects.com"):
        self.driver = driver
        self.base_url = base_url.rstrip("/")

    def _abs(self, url: str) -> str:
        if not url:
            return url
        if url.startswith("http"):
            return url
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return self.base_url + url
        return url

    def _get_variant_id_from_url(self, url: str) -> str:
        try:
            qs = parse_qs(urlparse(url).query)
            return (qs.get("variantId") or [""])[0].strip()
        except Exception:
            return ""

    def _wait_dom_ready(self, timeout=15):
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
            )
        except Exception:
            pass

    def _body_text_and_source(self):
        body_text = ""
        page_source = ""
        try:
            # textContent captures hidden tab content much more often than innerText
            body_text = self.driver.execute_script("return document.body ? document.body.textContent : ''") or ""
        except Exception:
            pass
        try:
            page_source = self.driver.page_source or ""
        except Exception:
            pass
        return body_text, page_source

    def _parse_price_eur(self, body_text: str) -> float:
        text = (body_text or "").replace("\u00a0", " ")
        # Prefer "Price €73.8" / "Price € 73,80"
        m = re.search(r"\bPrice\s*€\s*([0-9]+(?:[\.,][0-9]+)?)", text, re.IGNORECASE)
        if not m:
            m = re.search(r"\bFrom\s*Price\s*€\s*([0-9]+(?:[\.,][0-9]+)?)", text, re.IGNORECASE)
        if not m:
            m = re.search(r"€\s*([0-9]+(?:[\.,][0-9]+)?)", text)
        if not m:
            return 0.0
        s = m.group(1).replace(",", ".").strip()
        try:
            return float(s)
        except Exception:
            return 0.0

    def _parse_title(self, body_text: str) -> str:
        lines = [ln.strip() for ln in (body_text or "").splitlines() if ln.strip()]
        for i, ln in enumerate(lines):
            if re.search(r"\bItem no\.", ln, re.IGNORECASE) and i > 0:
                prev = lines[i-1]
                if len(prev) > 3:
                    return prev
        for ln in lines:
            if "," in ln and re.search(r"\bbackpack\b|\brfid\b|\banti-?theft\b", ln, re.IGNORECASE):
                return ln
        try:
            t = (self.driver.title or "").split("|")[0].strip()
            return t or "Produs"
        except Exception:
            return "Produs"

    def _parse_color_current(self, body_text: str) -> str:
        txt = body_text or ""
        m = re.search(r"Item no\.\s*[A-Z0-9\.]+\s*\n([A-Za-z][A-Za-z \-]{2,40})\n", txt)
        if m:
            return m.group(1).strip()
        m = re.search(r"\bColour\b\s*[:\t ]+\s*([^\n\r\t]+)", txt, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            val = re.split(r"\s{2,}|\t|•|\|", val)[0].strip()
            if 1 <= len(val) <= 40:
                return val
        return ""

    def _parse_product_details_table(self, body_text: str) -> dict:
        specs = {}
        text = (body_text or "").replace("\u00a0", " ")
        idx = text.lower().find("product details")
        region = text[idx:] if idx != -1 else text
        # stop markers
        stop = None
        for mk in ["esg features", "documentation", "login", "register", "© copyright", "contact  |  privacy"]:
            j = region.lower().find(mk)
            if j != -1:
                stop = j
                break
        if stop:
            region = region[:stop]

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
                if 1 <= len(k) <= 40:
                    specs[k] = v

        if "Description" not in specs:
            m = re.search(r"\bDescription\b\s+(.+)", region, re.IGNORECASE | re.DOTALL)
            if m:
                chunk = m.group(1)
                chunk = re.split(r"\nProduct USPs|\nPrimary specifications|\nESG Features|\nDocumentation", chunk, flags=re.IGNORECASE)[0]
                desc = " ".join([x.strip() for x in chunk.splitlines() if x.strip()])
                if desc:
                    specs["Description"] = desc
        return specs

    def _filter_specs(self, specs: dict) -> dict:
        drop = {
            "Quantity", "Printed*", "Printed", "Plain", "Recommended sales price",
            "Cantitate", "Imprimat*", "Imprimat", "Simplu", "Pret de vanzare recomandat"
        }
        out = {}
        for k, v in (specs or {}).items():
            kk = (k or "").strip()
            if not kk or kk in drop:
                continue
            out[kk] = (v or "").strip()
        return out

    def _extract_images(self, page_source: str) -> list:
        ps = page_source or ""
        imgs = []
        for m in re.finditer(r'"/product/image/large/[^"]+\.(?:jpg|jpeg|png|webp)[^"]*"', ps, re.IGNORECASE):
            imgs.append(self._abs(m.group(0).strip('"')))
        if not imgs:
            for m in re.finditer(r'<img[^>]+src="([^"]+)"', ps, re.IGNORECASE):
                u = m.group(1)
                if "languages" in u and u.lower().endswith(".gif"):
                    continue
                if any(ext in u.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                    imgs.append(self._abs(u))
        # dedup
        out, seen = [], set()
        for u in imgs:
            if u and u not in seen:
                seen.add(u)
                out.append(u)
        return out

    def _extract_variant_ids(self, page_source: str, current_variant: str) -> list:
        vids = set()
        ps = page_source or ""
        for m in re.finditer(r"variantId=([A-Z0-9\.]+)", ps):
            vids.add(m.group(1))
        for m in re.finditer(r'"variantId"\s*:\s*"([A-Z0-9\.]+)"', ps):
            vids.add(m.group(1))
        if current_variant:
            vids.add(current_variant)
        return sorted(vids)

    def scrape(self, url: str) -> dict:
        product = {
            "source": self.SOURCE,
            "url": url,
            "sku": self._get_variant_id_from_url(url) or "",
            "title": "Produs",
            "price_eur": 0.0,
            "description": "",
            "specs": {},
            "colors": [],
            "images": [],
            "variants": [],
        }

        try:
            self.driver.get(url)
            self._wait_dom_ready(20)
            time.sleep(1.0)

            body_text, page_source = self._body_text_and_source()

            product["title"] = self._parse_title(body_text)

            if not product["sku"]:
                m = re.search(r"Item no\.\s*([A-Z0-9\.]+)", body_text)
                if m:
                    product["sku"] = m.group(1).strip()

            product["price_eur"] = self._parse_price_eur(body_text)

            specs = self._filter_specs(self._parse_product_details_table(body_text))
            product["specs"] = specs

            desc = ""
            if specs.get("Description"):
                desc = specs.get("Description", "").strip()
            elif specs.get("Descriere"):
                desc = specs.get("Descriere", "").strip()
            product["description"] = desc

            col = ""
            for k in ("Colour", "Color", "Culoare"):
                if specs.get(k):
                    col = specs.get(k).strip()
                    break
            if not col:
                col = self._parse_color_current(body_text)
            if col:
                product["colors"] = [col]

            product["images"] = self._extract_images(page_source)

            vids = self._extract_variant_ids(page_source, product["sku"])
            product["variants"] = [{"variantId": v} for v in vids]

            return product

        except Exception as e:
            product["error"] = str(e)
            return product
