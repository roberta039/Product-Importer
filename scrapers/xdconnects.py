# scrapers/xdconnects.py
# XD Connects scraper (Pasul 1: Extract)
# - robust pentru headless (nu depinde de click pe tab-uri)
# - extrage Description + Specifications din "Product details" din text/page_source
# - extrage pretul din "Price €.." sau "€ .."
# - extrage culoarea curenta din text + optional listeaza variantele (variantId) si culorile lor
#   (best-effort, cu limita ca sa nu dureze prea mult)

from __future__ import annotations

import re
import time
from typing import Dict, List, Tuple, Optional

import streamlit as st

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from scrapers.base import BaseScraper
from utils.selenium_driver import get_driver


XD_SCRAPER_VERSION = "2026-02-18-xd-v5.6-text-parse-variants"
# print apare in Streamlit logs
print("XD SCRAPER VERSION:", XD_SCRAPER_VERSION)


def _norm_spaces(s: str) -> str:
    return re.sub(r"[ \t]+", " ", (s or "")).strip()


def _parse_money_eur(text: str) -> Optional[float]:
    """
    Accepta formate:
    - 'Price €73.8'
    - '€ 73,80'
    - '€73,80'
    """
    if not text:
        return None

    # 1) "Price €73.8"
    m = re.search(r"\bPrice\b\s*€\s*([0-9]+(?:[.,][0-9]+)?)", text, flags=re.IGNORECASE)
    if m:
        val = m.group(1).replace(",", ".")
        try:
            return float(val)
        except:
            pass

    # 2) "€ 73,80" (cu 1-2 zecimale)
    m = re.search(r"€\s*([0-9]+(?:[.,][0-9]{1,2})?)", text)
    if m:
        val = m.group(1).replace(",", ".")
        try:
            return float(val)
        except:
            pass

    return None


def _extract_between(text: str, start_markers: List[str], end_markers: List[str]) -> str:
    """
    Intoarce substring-ul dintre primul marker start gasit si primul marker end gasit dupa el.
    """
    if not text:
        return ""
    start_idx = -1
    for sm in start_markers:
        i = text.lower().find(sm.lower())
        if i != -1:
            start_idx = i + len(sm)
            break
    if start_idx == -1:
        return ""

    tail = text[start_idx:]
    end_idx = len(tail)
    for em in end_markers:
        j = tail.lower().find(em.lower())
        if j != -1:
            end_idx = min(end_idx, j)
    return tail[:end_idx].strip()


def _extract_colour_from_text(raw_text: str) -> Optional[str]:
    if not raw_text:
        return None

    # 1) dupa Item no. ... apare culoarea pe linia urmatoare
    m = re.search(r"Item no\.\s*[A-Z0-9\.]+\s*\n([A-Za-z][A-Za-z \-]{2,40})\n", raw_text)
    if m:
        return _norm_spaces(m.group(1))

    # 2) in primary specs: "Colour    light blue"
    m = re.search(r"\bColour\b\s*[:\t ]+\s*([^\n\r\t]+)", raw_text, flags=re.IGNORECASE)
    if m:
        val = _norm_spaces(m.group(1))
        val = re.split(r"\s{2,}|\t|•|\|", val)[0].strip()
        if 1 <= len(val) <= 40:
            return val

    return None


def _filter_specs(specs: Dict[str, str]) -> Dict[str, str]:
    """
    Elimina campuri care nu te intereseaza (Cantitate, Imprimat, Simplu, etc.)
    """
    drop_keys = {
        "quantity", "cantitate", "printed*", "printed", "imprimat*", "imprimat",
        "plain", "simplu", "recommended sales price", "pret de vanzare recomandat",
        "from", "price"
    }
    out = {}
    for k, v in (specs or {}).items():
        ks = _norm_spaces(k)
        if not ks:
            continue
        if ks.lower() in drop_keys:
            continue
        vs = (v or "").strip()
        if not vs:
            continue
        out[ks] = vs
    return out


def _parse_product_details_block(block: str) -> Tuple[str, Dict[str, str]]:
    """
    Parseaza textul din zona Product details intr-un (description, specs).
    Pe XD, blocul contine linii gen:
      Item no.    P705.709
      Description The Bobby Hero...
      Product USPs
      Integrated...
      Primary specifications
      CO2-eq 6.28 kg   Colour light blue
    """
    if not block:
        return "", {}

    # normalizeaza linii
    lines = [ln.strip() for ln in block.splitlines()]
    lines = [ln for ln in lines if ln]

    specs: Dict[str, str] = {}
    description = ""

    # 1) cauta linia "Description" (EN) sau "Descriere"
    # Uneori e in format: "Description\ttext..."
    for i, ln in enumerate(lines):
        if re.match(r"^(Description|Descriere)\b", ln, flags=re.IGNORECASE):
            # poate fi "Description  text"
            parts = re.split(r"\s{2,}|\t", ln, maxsplit=1)
            if len(parts) == 2:
                description = parts[1].strip()
            else:
                # textul poate fi pe urmatoarea linie
                if i + 1 < len(lines):
                    description = lines[i + 1].strip()
            break

    # 2) parseaza perechi cheie/valoare pe linii (tab / spatii multiple)
    i = 0
    while i < len(lines):
        ln = lines[i]
        # skip headings
        if ln.lower() in {"product details", "primary specifications", "product usps"}:
            i += 1
            continue

        # daca linia e "Product USPs" atunci urmatoarele linii pana la alt heading sunt lista
        if ln.lower() == "product usps":
            usp = []
            i += 1
            while i < len(lines) and lines[i].lower() not in {"primary specifications", "esg features", "documentation"}:
                if lines[i]:
                    usp.append(lines[i])
                i += 1
            if usp:
                specs["Product USPs"] = " ".join(usp).strip()
            continue

        # linii cu 2 coloane separate prin tab/spatii multiple
        parts = re.split(r"\t+|\s{2,}", ln, maxsplit=1)
        if len(parts) == 2:
            k, v = parts[0].strip(), parts[1].strip()
            # evita capturi inutile
            if k and v and len(k) <= 60 and len(v) <= 2000:
                # nu suprascrie descrierea daca deja e mai completa
                if re.match(r"^(Description|Descriere)$", k, flags=re.IGNORECASE):
                    if not description:
                        description = v
                else:
                    specs[k] = v
        i += 1

    return description, specs


def _extract_all_variant_ids(page_source: str, current_variant: str) -> List[str]:
    if not page_source:
        return [current_variant] if current_variant else []

    # prinde variantId=... si "variantId":"..."
    found = set()
    for m in re.finditer(r"variantId(?:=|%3D|\"?\s*:\s*\")([A-Z0-9\.]+)", page_source, flags=re.IGNORECASE):
        vid = m.group(1).strip()
        if vid:
            found.add(vid)

    # in unele cazuri apare ca P705.709 cu punct
    # asigura curent
    if current_variant:
        found.add(current_variant)

    # returneaza sortat, dar cu current primul
    out = sorted(found)
    if current_variant and current_variant in out:
        out.remove(current_variant)
        out.insert(0, current_variant)
    return out


class XDConnectsScraper(BaseScraper):
    site_name = "xdconnects"

    def __init__(self):
        super().__init__()

    def _login(self, driver) -> None:
        # Login o singura data / sesiune, daca ai deja implementat in BaseScraper, poti ignora
        try:
            if st.session_state.get("xd_logged_in"):
                return
        except Exception:
            pass

        user = st.secrets.get("SOURCES", {}).get("XD_USER", "")
        pwd = st.secrets.get("SOURCES", {}).get("XD_PASS", "")

        if not user or not pwd:
            st.warning("⚠️ XD: lipsesc XD_USER / XD_PASS în Secrets.")
            return

        st.info("🔐 XD: Mă conectez...")
        driver.get("https://www.xdconnects.com/en-gb/login")
        wait = WebDriverWait(driver, 20)

        # accept cookies daca apare
        try:
            btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(.,'Accept') or contains(.,'Agree') or contains(.,'I agree')]")))
            btn.click()
            time.sleep(0.5)
        except Exception:
            pass

        # campuri login
        try:
            email_in = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='email'], input[name*='email' i]")))
            pass_in = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password']")))
            email_in.clear()
            email_in.send_keys(user)
            pass_in.clear()
            pass_in.send_keys(pwd)

            # submit
            try:
                submit = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
                submit.click()
            except Exception:
                pass_in.submit()

            # asteapta sa dispara form / sa apara account
            time.sleep(2.0)
            st.success("✅ XD: Login reușit!")
            try:
                st.session_state["xd_logged_in"] = True
            except Exception:
                pass
        except Exception as e:
            st.warning(f"⚠️ XD login failed: {str(e)[:150]}")

    def scrape(self, url: str) -> Dict:
        # Always return dict (never None)
        driver = None
        try:
            driver = get_driver(headless=True)
            self._login(driver)

            st.write(f"📦 XD v5.6: {url[:80]}...")

            driver.get(url)
            WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            time.sleep(1.2)

            # text vizibil + textContent (include si ascuns)
            raw_text = driver.find_element(By.TAG_NAME, "body").text or ""
            try:
                text_content = driver.execute_script("return document.body ? document.body.textContent : ''") or ""
            except Exception:
                text_content = raw_text

            # page_source pentru variante
            try:
                page_source = driver.page_source or ""
            except Exception:
                page_source = ""

            # NAME (H1)
            name = ""
            try:
                h1 = driver.find_element(By.CSS_SELECTOR, "h1")
                name = _norm_spaces(h1.text)
            except Exception:
                # fallback: prima linie care contine "Anti-theft"
                m = re.search(r"\n([^\n]{5,120}backpack[^\n]{0,60})\n", raw_text, flags=re.IGNORECASE)
                if m:
                    name = _norm_spaces(m.group(1))
            if not name:
                # evita sa devina "About XD Connects"
                m = re.search(r"\n([^\n]{5,120})\n", raw_text)
                name = _norm_spaces(m.group(1)) if m else "Produs XD"

            # SKU / variantId din URL
            sku = ""
            m = re.search(r"variantId=([A-Z0-9\.]+)", url, flags=re.IGNORECASE)
            if m:
                sku = m.group(1).strip()
            else:
                # fallback: Item no. P705.709
                m = re.search(r"Item no\.\s*([A-Z0-9\.]+)", raw_text)
                if m:
                    sku = m.group(1).strip()

            # PRET EUR
            price_eur = _parse_money_eur(raw_text) or _parse_money_eur(text_content) or 0.0
            currency = "EUR"

            # PRODUCT DETAILS: din textContent (include hidden)
            details_block = _extract_between(
                text_content,
                start_markers=["Product details"],
                end_markers=["ESG Features", "Documentation", "Login", "Register", "About Us", "© Copyright"]
            )
            description, specs = _parse_product_details_block(details_block)

            # fallback daca nu a prins: incearca din raw_text
            if not description or len(specs) < 3:
                details_block2 = _extract_between(
                    raw_text,
                    start_markers=["Product details"],
                    end_markers=["ESG Features", "Documentation", "Login", "Register", "About Us", "© Copyright"]
                )
                d2, s2 = _parse_product_details_block(details_block2)
                if not description:
                    description = d2
                if len(specs) < len(s2):
                    specs = s2

            specs = _filter_specs(specs)

            # CULOARE curenta
            color_current = _extract_colour_from_text(raw_text) or _extract_colour_from_text(text_content)
            colors = [color_current] if color_current else []

            # VARIANTE (best-effort): lista de variantId + culorile lor (max 15)
            variant_ids = _extract_all_variant_ids(page_source, sku)
            variant_ids = [v for v in variant_ids if v]
            variant_ids = variant_ids[:15]  # limita

            variants = []
            if len(variant_ids) > 1:
                base = url.split("?")[0]
                for vid in variant_ids:
                    vurl = f"{base}?variantId={vid}"
                    # foloseste aceeasi sesiune browser, dar fara sa strice pagina curenta prea mult
                    driver.get(vurl)
                    time.sleep(0.9)
                    rt = driver.find_element(By.TAG_NAME, "body").text or ""
                    c = _extract_colour_from_text(rt) or ""
                    variants.append({"variantId": vid, "color": c})
                # revino la url original
                driver.get(url)
                time.sleep(0.5)
                # compileaza lista culori unica
                all_cols = [v["color"] for v in variants if v.get("color")]
                if all_cols:
                    uniq = []
                    for c in all_cols:
                        if c not in uniq:
                            uniq.append(c)
                    colors = uniq

            # IMAGINI: ia toate URL-urile mari /product/image/large/
            images = []
            try:
                imgs = driver.find_elements(By.CSS_SELECTOR, "img")
                for im in imgs:
                    src = im.get_attribute("src") or ""
                    if not src:
                        continue
                    if "/product/image/" in src or "/product/image/large/" in src:
                        if src.startswith("/"):
                            src = "https://www.xdconnects.com" + src
                        if src not in images:
                            images.append(src)
            except Exception:
                pass

            # fallback imagini: regex din page_source
            if len(images) < 2 and page_source:
                for m in re.finditer(r"(\/product\/image\/large\/[^\"']+)", page_source):
                    s = m.group(1)
                    full = "https://www.xdconnects.com" + s
                    if full not in images:
                        images.append(full)

            # descriere HTML simpla
            description_html = f"<p>{(description or '').strip()}</p>" if description else ""

            result = {
                "name": name,
                "sku": sku or "",
                "price": float(price_eur or 0.0),
                "currency": currency,
                "description": description_html,          # HTML pentru import
                "specifications": specs,                 # dict filtrat
                "colors": colors,                        # lista culori
                "variants": variants,                    # optional
                "images": images,
                "source_url": url,
                "source_site": self.site_name,
            }

            # debug scurt
            print("XD DEBUG price_eur=", result["price"], "desc_len=", len(description or ""), "specs=", len(specs), "colors=", len(colors), "variants=", len(variants))
            return result

        except Exception as e:
            err = str(e)
            st.warning(f"⚠️ XD scrape error: {err[:180]}")
            return {
                "name": "Eroare XD",
                "sku": "",
                "price": 0.0,
                "currency": "EUR",
                "description": "",
                "specifications": {},
                "colors": [],
                "variants": [],
                "images": [],
                "source_url": url,
                "source_site": self.site_name,
                "error": err,
            }
        finally:
            try:
                if driver:
                    driver.quit()
            except Exception:
                pass
