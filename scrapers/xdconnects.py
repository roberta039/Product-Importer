# scrapers/xdconnects.py
"""
XD Connects Scraper - v5.5 (2026-02-18)

Obiective (Pasul 1):
- Extrage: nume, descriere (din Product details), specificatii (fara Quantity/Printed/Plain/etc),
  pret EUR (robust), culori (default + variante daca sunt expuse), imagini.
- Evita click-uri pe taburi/meniuri (in headless pot redirectiona catre About).
- SKU: foloseste variantId din URL daca exista; altfel Item no.

Notă:
- La unele produse, XD nu expune lista completa de culori/variantId in DOM fara interactiune.
  In acel caz, intoarcem cel putin culoarea curenta.
"""
import re
import time
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from scrapers.base_scraper import BaseScraper
from utils.image_handler import make_absolute_url


class XDConnectsScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.name = "xdconnects"
        self.base_url = "https://www.xdconnects.com"

    # -------------------------
    # Helpers
    # -------------------------
    @staticmethod
    def _variant_id_from_url(url: str) -> str | None:
        try:
            qs = parse_qs(urlparse(url).query)
            return (qs.get("variantId", [None])[0] or None)
        except Exception:
            return None

    @staticmethod
    def _set_variant_id(url: str, variant_id: str) -> str:
        p = urlparse(url)
        qs = parse_qs(p.query)
        qs["variantId"] = [variant_id]
        q = urlencode(qs, doseq=True)
        return urlunparse((p.scheme, p.netloc, p.path, p.params, q, p.fragment))

    @staticmethod
    def _price_from_text(text: str) -> float | None:
        if not text:
            return None
        m = re.search(r"(?:Price\s*)?€\s*([0-9]+(?:[.,][0-9]+)?)", text, flags=re.IGNORECASE)
        if not m:
            return None
        val = m.group(1).strip().replace(",", ".")
        try:
            return float(val)
        except Exception:
            return None

    @staticmethod
    def _extract_between(text: str, start_markers: list[str], end_markers: list[str]) -> str:
        if not text:
            return ""
        lower = text.lower()
        start = -1
        for sm in start_markers:
            i = lower.find(sm.lower())
            if i != -1:
                start = i + len(sm)
                break
        if start == -1:
            return ""
        end = len(text)
        for em in end_markers:
            j = lower.find(em.lower(), start)
            if j != -1:
                end = min(end, j)
        return text[start:end].strip()

    @staticmethod
    def _parse_kv_block(block: str) -> dict:
        """
        Parseaza linii de tip: Key<TAB>Value sau Key  (2+spatii) Value.
        """
        specs = {}
        if not block:
            return specs
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        for ln in lines:
            if ln.lower() in {"product details", "primary specifications", "detalii produs"}:
                continue
            if "\t" in ln:
                parts = [p.strip() for p in ln.split("\t") if p.strip()]
                if len(parts) >= 2:
                    specs[parts[0]] = " ".join(parts[1:])
                continue
            m = re.match(r"^(.{2,40}?)\s{2,}(.+)$", ln)
            if m:
                specs[m.group(1).strip()] = m.group(2).strip()
        return specs

    @staticmethod
    def _extract_description(pd_block: str, fallback_text: str) -> str:
        for src in (pd_block, fallback_text):
            if not src:
                continue
            m = re.search(
                r"\b(Description|Descriere)\b\s*[:\t ]+\s*(.+?)(?:\n(?:Product USPs|USP-uri de produs|Primary specifications|Specificații primare)\b|\Z)",
                src,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if m:
                desc = m.group(2).strip()
                desc = re.sub(r"\s{2,}", " ", desc)
                return desc
        return ""

    @staticmethod
    def _html_p(text: str) -> str:
        if not text:
            return ""
        esc = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        return f"<p>{esc}</p>"

    @staticmethod
    def _extract_current_color(text: str) -> str | None:
        if not text:
            return None
        # dupa Item no. urmeaza culoarea pe linia urmatoare (foarte stabil la XD)
        m = re.search(r"Item no\.\s*[A-Z0-9\.]+\s*\n([A-Za-z][A-Za-z \-]{2,40})\n", text)
        if m:
            return m.group(1).strip()
        m = re.search(r"\bColour\b\s*[:\t ]+\s*([^\n\r\t]+)", text, flags=re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            val = re.split(r"\s{2,}|\t|•|\|", val)[0].strip()
            if 1 <= len(val) <= 40:
                return val
        return None

    @staticmethod
    def _extract_variant_ids(page_source: str) -> list[str]:
        if not page_source:
            return []
        vids = set()
        for m in re.finditer(r"variantId=([A-Z0-9\.]+)", page_source):
            vids.add(m.group(1))
        for m in re.finditer(r'"variantId"\s*:\s*"([A-Z0-9\.]+)"', page_source):
            vids.add(m.group(1))
        return sorted(vids)

    @staticmethod
    def _filter_specs(specs: dict) -> dict:
        drop = {
            "quantity", "cantitate",
            "printed", "printed*", "imprimat", "imprimat*",
            "plain", "simplu",
            "recommended sales price", "pret de vanzare recomandat",
            "from", "price", "pret", "preț",
        }
        out = {}
        for k, v in (specs or {}).items():
            ks = str(k).strip()
            vs = str(v).strip()
            if not ks or not vs:
                continue
            if ks.lower() in drop:
                continue
            if ks.lower() in {"description", "descriere"}:
                continue
            out[ks] = vs
        return out

    # -------------------------
    # Main
    # -------------------------
    def scrape(self, url: str) -> dict | None:
        driver = self.driver
        driver.get(url)
        time.sleep(1.0)

        # asteapta h1 (pagina produs)
        try:
            WebDriverWait(driver, 12).until(EC.presence_of_element_located((By.CSS_SELECTOR, "h1")))
        except Exception:
            pass

        # text vizibil + textContent (include si ascuns)
        try:
            visible = driver.execute_script("return document.body.innerText || ''") or ""
        except Exception:
            visible = ""
        try:
            all_text = driver.execute_script("return document.body.textContent || ''") or ""
        except Exception:
            all_text = ""

        page_source = driver.page_source or ""

        # nume produs
        name = ""
        try:
            name = driver.find_element(By.CSS_SELECTOR, "h1").text.strip()
        except Exception:
            # fallback: cauta prima linie "Bobby"
            for ln in visible.splitlines():
                if "bobby" in ln.lower() and len(ln) < 120:
                    name = ln.strip()
                    break
        name = name or "Produs XD"

        # SKU: variantId param > Item no.
        sku = self._variant_id_from_url(url)
        if not sku:
            m = re.search(r"Item no\.\s*([A-Z0-9\.]+)", visible)
            if m:
                sku = m.group(1).strip()
        sku = sku or ""

        # pret EUR robust
        price = self._price_from_text(visible)
        if price is None:
            price = self._price_from_text(all_text)
        price = float(price or 0.0)

        # Product details block (din textContent ca sa nu pierdem continut ascuns)
        pd_block = self._extract_between(
            all_text,
            start_markers=["Product details", "Detalii produs"],
            end_markers=["ESG Features", "Documentation", "Login", "Register", "About Us", "©"],
        )
        if not pd_block:
            pd_block = self._extract_between(
                visible,
                start_markers=["Product details", "Detalii produs"],
                end_markers=["ESG Features", "Documentation", "Login", "Register", "About Us", "©"],
            )

        # Primary specifications
        prim_block = ""
        mprim = re.search(
            r"(Primary specifications|Specificații primare)(.+?)(?:\n(?:Login|Register|Documentation|©)|\Z)",
            all_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if mprim:
            prim_block = (mprim.group(2) or "").strip()

        specs = {}
        specs.update(self._parse_kv_block(pd_block))
        specs.update(self._parse_kv_block(prim_block))
        specs = self._filter_specs(specs)

        desc_text = self._extract_description(pd_block, visible)
        description = self._html_p(desc_text)

        # culoare curenta
        current_color = None
        for key in ("Colour", "Color", "Culoare"):
            if key in specs and specs[key]:
                current_color = specs[key].strip()
                break
        if not current_color:
            current_color = self._extract_current_color(visible) or self._extract_current_color(all_text)

        # variante / culori
        variant_ids = self._extract_variant_ids(page_source)
        variants = []
        if variant_ids:
            # lookup culori pentru max 15 variante, pastrand sesiunea logata
            max_lookup = 15
            for vid in variant_ids[:max_lookup]:
                vurl = self._set_variant_id(url, vid)
                if sku and vid == sku and current_color:
                    variants.append({"variantId": vid, "color": current_color})
                    continue
                try:
                    driver.get(vurl)
                    time.sleep(0.8)
                    vtxt = driver.execute_script("return document.body.innerText || ''") or ""
                    vcol = self._extract_current_color(vtxt) or ""
                    variants.append({"variantId": vid, "color": vcol})
                except Exception:
                    variants.append({"variantId": vid, "color": ""})
            try:
                driver.get(url)
                time.sleep(0.5)
            except Exception:
                pass
        else:
            if sku:
                variants = [{"variantId": sku, "color": current_color or ""}]

        # lista culori unice
        colors = []
        seen = set()
        for v in variants:
            c = (v.get("color") or "").strip()
            if not c:
                continue
            key = c.lower()
            if key in seen:
                continue
            seen.add(key)
            colors.append(c)
        if not colors and current_color:
            colors = [current_color]

        # imagini
        images = []
        try:
            soup = BeautifulSoup(driver.page_source, "html.parser")
            for img in soup.find_all("img"):
                src = img.get("src") or img.get("data-src") or ""
                if not src:
                    continue
                if "product/image" in src or src.endswith((".jpg", ".jpeg", ".png", ".webp")):
                    images.append(make_absolute_url(src, self.base_url))
            for el in soup.select("[style*='background-image']"):
                style = el.get("style", "")
                m = re.search(r"background-image\s*:\s*url\(['\"]?([^'\")]+)", style)
                if m:
                    images.append(make_absolute_url(m.group(1), self.base_url))
        except Exception:
            pass
        # unique
        uniq, s = [], set()
        for im in images:
            if not im or im in s:
                continue
            s.add(im)
            uniq.append(im)
        images = uniq

        # Construieste produs standard pentru app
        product = self._build_product(
            name=name,
            description=description,
            sku=sku,
            price=price,
            currency="EUR",
            images=images,
            colors=colors,
            specifications=specs,
            source_url=url,
            source_site=self.name,
            category="",
        )

        # Extra fields utile pentru export/verificare
        product["variants"] = variants
        product["description_text"] = desc_text

        return product
