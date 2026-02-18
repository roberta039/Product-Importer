# -*- coding: utf-8 -*-
"""
XD Connects scraper (Pasul 1 - extragere)
- stabil (nu face click pe taburi)
- extrage: titlu, SKU (variantId), pret EUR, descriere, specificatii (filtrate), culori (best effort), imagini
Compatibil cu factory-ul proiectului: get_scraper() -> XDConnectsScraper()
"""
from __future__ import annotations

import re
import time
from typing import Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper

XD_SCRAPER_VERSION = "2026-02-18-xd-v59-price+details+variants"
print("XD SCRAPER VERSION:", XD_SCRAPER_VERSION)


def _normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def _safe_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _parse_eur_from_text(text: str) -> float:
    """
    Accepta:
      - "Price €73.8"
      - "€ 73,80"
      - "€73"
    Returneaza 0.0 daca nu gaseste.
    """
    if not text:
        return 0.0

    t = text.replace("\xa0", " ")
    # 1) prefera "Price €..."
    patterns = [
        r"\bPrice\s*€\s*([0-9]{1,5}(?:[.,][0-9]{1,2})?)",
        r"\bFrom\s*Price\s*€\s*([0-9]{1,5}(?:[.,][0-9]{1,2})?)",
        r"€\s*([0-9]{1,5}(?:[.,][0-9]{1,2})?)",
    ]
    candidates: List[float] = []
    for pat in patterns:
        for m in re.finditer(pat, t, flags=re.IGNORECASE):
            raw = m.group(1).strip()
            raw = raw.replace(".", ".").replace(",", ".")
            val = _safe_float(raw)
            if val is None:
                continue
            # filtre simple ca sa evitam alte numere
            if 0.5 <= val <= 5000:
                candidates.append(val)

        if candidates:
            break

    return candidates[0] if candidates else 0.0


def _extract_item_no(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"\bItem no\.\s*([A-Z0-9.]+)", text)
    return m.group(1).strip() if m else None


def _extract_colour_from_text(text: str) -> Optional[str]:
    if not text:
        return None

    # 1) "Colour <valoare>" (tabele / blocuri)
    m = re.search(r"\bColour\b\s*[:\t ]+\s*([^\n\r\t]+)", text, flags=re.IGNORECASE)
    if m:
        val = _normalize_spaces(m.group(1))
        # taie daca e prea lung
        val = re.split(r"\s{2,}|\t|•|\|", val)[0].strip()
        if 1 <= len(val) <= 40:
            return val

    # 2) dupa "Item no. P705.709" urmeaza adesea culoarea pe linia urmatoare
    m = re.search(r"Item no\.\s*[A-Z0-9.]+\s*\n([A-Za-z][A-Za-z \-]{2,40})\n", text)
    if m:
        return _normalize_spaces(m.group(1))

    return None


def _specs_from_product_details_text(text: str) -> Tuple[str, Dict[str, str]]:
    """
    Din textul complet (body textContent + innerText), incearca sa extraga:
      - Description: ...
      - key/value din sectiunile Product details / Primary specifications
    Returneaza (descriere, specs_dict)
    """
    desc = ""

    # Description: ... (uneori e "Description\t....")
    m = re.search(r"\bDescription\b\s*[:\t]+\s*(.+?)(?:\n[A-Z][^\n]{0,40}\n|$)", text, flags=re.IGNORECASE | re.DOTALL)
    if m:
        d = m.group(1)
        # curata pana la urmatoarea eticheta comuna
        d = re.split(r"\n(?:Product USPs|Primary specifications|CO2|Documentation)\b", d, flags=re.IGNORECASE)[0]
        desc = _normalize_spaces(d)

    specs: Dict[str, str] = {}

    # Extrage perechi tip tabel: "Key\tValue"
    for line in (text or "").splitlines():
        ln = line.strip()
        if not ln:
            continue
        # multe pagini au tabel ca "Key\tValue" (tabs) sau "Key: Value"
        if "\t" in ln:
            parts = [p.strip() for p in ln.split("\t") if p.strip()]
            if len(parts) >= 2:
                k, v = parts[0], " ".join(parts[1:])
                if k and v:
                    specs[k] = _normalize_spaces(v)
        elif ":" in ln:
            k, v = ln.split(":", 1)
            k = k.strip()
            v = v.strip()
            if k and v and len(k) <= 40:
                # evita linii gen "https://"
                if k.lower().startswith("http"):
                    continue
                specs[k] = _normalize_spaces(v)

    # Filtrare: scoate ce NU te intereseaza
    drop_keys = {
        "Quantity", "Cantitate",
        "Printed*", "Printed", "Imprimat*", "Imprimat",
        "Plain", "Simplu",
        "Recommended sales price", "Pret de vanzare recomandat",
        "From", "Price", "Pret",
    }
    specs = {k: v for k, v in specs.items() if k.strip() not in drop_keys}

    # daca n-am prins descriere din bloc, incearca din specs
    if not desc:
        for k in list(specs.keys()):
            if k.lower() in ("description", "descriere"):
                desc = specs[k]
                # lasa si in specs daca vrei; eu o scot ca sa nu dubleze
                specs.pop(k, None)
                break

    return desc, specs


def _extract_images_from_html(html: str) -> List[str]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    urls: List[str] = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy")
        if not src:
            continue
        src = src.strip()
        if src.startswith("//"):
            src = "https:" + src
        if src.startswith("/"):
            src = "https://www.xdconnects.com" + src
        # filtreaza iconite evidente
        if "languages" in src and src.lower().endswith(".gif"):
            continue
        if src not in urls:
            urls.append(src)
    return urls


def _extract_variant_ids(html: str, current_variant: Optional[str]) -> List[str]:
    """
    Cauta variantId-uri in html (href + JSON). Returneaza lista unica.
    """
    if not html:
        return [current_variant] if current_variant else []

    ids = set()

    if current_variant:
        ids.add(current_variant)

    # href variantId=
    for m in re.finditer(r"variantId=([A-Z0-9.]+)", html):
        ids.add(m.group(1))

    # JSON "variantId":"P705.709"
    for m in re.finditer(r'"variantId"\s*:\s*"([A-Z0-9.]+)"', html):
        ids.add(m.group(1))

    # uneori apare ca VariantId=P...
    for m in re.finditer(r"\bVariantId\b\s*=\s*([A-Z0-9.]+)", html):
        ids.add(m.group(1))

    out = [x for x in ids if x]
    out.sort()
    return out


class XDConnectsScraper(BaseScraper):
    name = "xdconnects"

    def scrape(self, url: str) -> dict:
        # IMPORTANT: NU returna None niciodata
        result = {
            "name": "",
            "sku": "",
            "price_eur": 0.0,
            "description": "",
            "specs": {},
            "colors": [],
            "images": [],
            "url": url,
            "source": "xdconnects",
        }

        driver = self.get_driver()
        try:
            driver.get(url)
            time.sleep(1.2)

            # uneori cookie banner poate acoperi; nu facem click agresiv, doar scroll top
            try:
                driver.execute_script("window.scrollTo(0,0);")
            except Exception:
                pass

            # luam si text vizibil si textContent (include ascuns)
            try:
                visible_text = driver.find_element("tag name", "body").text or ""
            except Exception:
                visible_text = ""

            try:
                # textContent include si content ascuns in taburi (spre deosebire de innerText)
                text_content = driver.execute_script("return document.body ? document.body.textContent : '';") or ""
            except Exception:
                text_content = ""

            # HTML complet
            try:
                html = driver.page_source or ""
            except Exception:
                html = ""

            # TITLE: prefera h1
            title = ""
            try:
                h1 = driver.find_elements("css selector", "h1")
                if h1:
                    title = _normalize_spaces(h1[0].text)
            except Exception:
                pass
            if not title:
                # fallback din title tag
                m = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
                title = _normalize_spaces(m.group(1)) if m else ""

            # SKU: variantId din URL, altfel Item no.
            variant = None
            m = re.search(r"[?&]variantId=([^&]+)", url)
            if m:
                variant = m.group(1).strip()
            item_no = _extract_item_no(visible_text) or _extract_item_no(text_content)
            sku = variant or item_no or ""
            result["sku"] = sku

            # PRICE
            price_eur = _parse_eur_from_text(visible_text)
            if price_eur == 0.0:
                price_eur = _parse_eur_from_text(text_content)
            if price_eur == 0.0:
                # uneori e in html ca "€ 73,80" doar
                soup = BeautifulSoup(html, "html.parser")
                txt = soup.get_text("\n", strip=True)
                price_eur = _parse_eur_from_text(txt)

            result["price_eur"] = float(price_eur or 0.0)

            # DESCRIPTION + SPECS (din textContent ca sa prinda Product details chiar daca e ascuns)
            combined_text = (text_content or "") if len(text_content) > len(visible_text) else (visible_text or "")
            desc, specs = _specs_from_product_details_text(combined_text)

            # Daca n-am prins nimic, incearca direct din HTML: cauta randul Description in tabel
            if not desc:
                soup = BeautifulSoup(html, "html.parser")
                # cauta "Description" urmat de text in acelasi container
                # ex: <td>Description</td><td>...</td>
                for td in soup.find_all(["td", "th"]):
                    if _normalize_spaces(td.get_text(" ", strip=True)).lower() == "description":
                        sib = td.find_next("td")
                        if sib:
                            desc = _normalize_spaces(sib.get_text(" ", strip=True))
                            break

            result["description"] = desc
            # specs filtrate
            result["specs"] = specs or {}

            # COLORS
            color = None
            # prefera din specs daca exista
            for key in ("Colour", "Color", "Culoare"):
                if key in result["specs"] and result["specs"][key]:
                    color = result["specs"][key]
                    break
            if not color:
                color = _extract_colour_from_text(visible_text) or _extract_colour_from_text(text_content)
            colors = [color] if color else []

            # VARIANTS (best effort): daca in html exista mai multe variantId, colecteaza culori
            variant_ids = _extract_variant_ids(html, variant)
            # limita ca sa nu dureze mult pe Streamlit Cloud
            if len(variant_ids) > 1:
                collected = []
                # construim base url fara variantId
                base = re.sub(r"([?&])variantId=[^&]+", r"\1", url)
                base = re.sub(r"[?&]$", "", base)
                sep = "&" if "?" in base else "?"
                for vid in variant_ids[:10]:
                    vurl = f"{base}{sep}variantId={vid}"
                    try:
                        driver.get(vurl)
                        time.sleep(0.9)
                        vt = driver.find_element("tag name", "body").text or ""
                        vc = _extract_colour_from_text(vt)
                        if not vc:
                            vc = _extract_colour_from_text(driver.execute_script("return document.body.textContent || '';") or "")
                        if vc:
                            collected.append(vc)
                    except Exception:
                        continue
                # daca am colectat >1, foloseste lista unica
                uniq = []
                for c in collected:
                    c = _normalize_spaces(c)
                    if c and c not in uniq:
                        uniq.append(c)
                if uniq:
                    colors = uniq

            result["colors"] = colors

            # IMAGES
            images = _extract_images_from_html(html)
            result["images"] = images

            # NAME: in proiectul tau pare ca faci "Rucsac antifurt" etc; aici dau titlul curat
            result["name"] = title or result["name"] or "Produs XD"

            return result

        except Exception as e:
            # returneaza tot dict-ul, dar cu error
            result["error"] = str(e)
            return result
        finally:
            # driver lifecycle e gestionat in BaseScraper (probabil singleton); nu inchidem aici
            pass
