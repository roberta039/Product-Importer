# scrapers/xdconnects.py
# VERSIUNE 5.0.1 - stabil (fara get_driver), pret robust, product-details specs+desc, culori best-effort
"""XD Connects scraper (pasul 1: extractie)

Fix-uri fata de v5.0:
- Pret: prinde si formate de tip "Price €73.8" / "€ 73,80" / "€73" (1-2 zecimale, punct/virgula)
- URL: setat intotdeauna in produs
- Culori: incearca sa deschida selectorul "Colour:" si sa citeasca optiunile (best-effort), altfel fallback la culoarea curenta
- NU foloseste get_driver (compatibil cu BaseScraper din proiect)
"""

import re
import time
from bs4 import BeautifulSoup
import streamlit as st
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from scrapers.base_scraper import BaseScraper
from utils.helpers import clean_price
from utils.image_handler import make_absolute_url


class XDConnectsScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.name = "xdconnects"
        self.base_url = "https://www.xdconnects.com"
        self._logged_in = False

    # ------------------------- helpers -------------------------
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
                    time.sleep(1.5)
                    return
            except Exception:
                continue
        # fallback: remove overlays
        try:
            self.driver.execute_script(
                "var s=['#CybotCookiebotDialog','#CybotCookiebotDialogBodyUnderlay',"
                "'#onetrust-banner-sdk'];"
                "s.forEach(function(x){document.querySelectorAll(x).forEach(function(e){e.remove();});});"
                "document.body.style.overflow='auto';"
            )
        except Exception:
            pass

    def _login_if_needed(self):
        if self._logged_in:
            return
        try:
            xd_user = st.secrets.get("SOURCES", {}).get("XD_USER", "")
            xd_pass = st.secrets.get("SOURCES", {}).get("XD_PASS", "")
            # daca nu ai user/pass, site-ul tot permite vizualizare partiala; nu blocam
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
                for f in self.driver.find_elements(By.CSS_SELECTOR, "input[type='password']"):
                    if f.is_displayed() and f.is_enabled():
                        f.clear()
                        f.send_keys(xd_pass)
                        break
            except Exception:
                pass

            self._dismiss_cookie_banner()

            # submit
            for sel in ["form button[type='submit']", "button[type='submit']"]:
                try:
                    for btn in self.driver.find_elements(By.CSS_SELECTOR, sel):
                        if btn.is_displayed() and btn.is_enabled():
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

    def _extract_current_colour_from_text(self, text: str) -> str | None:
        if not text:
            return None
        # Primary specifications: "Colour\t light blue"
        m = re.search(r"\bColour\b\s*[:\t ]+\s*([^\n\r\t]+)", text, flags=re.I)
        if m:
            val = m.group(1).strip()
            val = re.split(r"\s{2,}|\t|•|\|", val)[0].strip()
            if 1 <= len(val) <= 40:
                return val
        # After "Item no. P705.709" next line is colour
        m = re.search(r"Item no\.\s*[A-Z0-9\.]+\s*\n([A-Za-z][A-Za-z \-]{2,40})\n", text)
        if m:
            return m.group(1).strip()
        return None

    def _extract_colour_options_best_effort(self) -> list[str]:
        """Incearca sa deschida selectorul "Colour:" si sa citeasca optiunile.
        Daca nu reuseste, returneaza []."""
        if not self.driver:
            return []

        # click pe label "Colour" (best-effort)
        try:
            # element care contine text exact "Colour:" sau "Colour"
            label_candidates = self.driver.find_elements(
                By.XPATH,
                "//*[normalize-space()='Colour:' or normalize-space()='Colour' or contains(normalize-space(),'Colour')]",
            )
            for el in label_candidates[:5]:
                try:
                    if el.is_displayed():
                        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                        time.sleep(0.2)
                        self.driver.execute_script("arguments[0].click();", el)
                        time.sleep(0.8)
                        break
                except Exception:
                    continue
        except Exception:
            pass

        # dupa click, cautam optiuni in dropdown/lista
        texts = set()
        try:
            # optiuni comune: role=option / li / button in apropiere
            option_els = self.driver.find_elements(
                By.CSS_SELECTOR,
                "[role='option'], [class*='option'], [class*='dropdown'] li, [class*='select'] li, [class*='select'] button",
            )
            for opt in option_els:
                try:
                    t = (opt.text or "").strip()
                    if 1 <= len(t) <= 40 and "recommended" not in t.lower() and "sales" not in t.lower():
                        # exclude numere pure
                        if not re.fullmatch(r"\d+", t):
                            texts.add(t)
                except Exception:
                    continue
        except Exception:
            pass

        # fallback: cauta in HTML attribute aria-label/title pentru culori
        if not texts:
            try:
                sw = self.driver.find_elements(By.CSS_SELECTOR, "[aria-label*='colour' i], [title*='colour' i]")
                for el in sw:
                    for attr in ("aria-label", "title"):
                        try:
                            v = (el.get_attribute(attr) or "").strip()
                            if v and len(v) <= 40:
                                texts.add(v)
                        except Exception:
                            pass
            except Exception:
                pass

        # curata: elimina duplicari care includ "Colour" in text
        cleaned = []
        for t in sorted(texts):
            t2 = re.sub(r"(?i)colour\s*:?\s*", "", t).strip()
            if t2 and t2.lower() not in {c.lower() for c in cleaned}:
                cleaned.append(t2)
        return cleaned

    # ------------------------- main -------------------------
    def scrape(self, url: str) -> dict | None:
        self._login_if_needed()
        self._init_driver()
        if not self.driver:
            return None

        st.info(f"📦 XD v5.0.1: {url[:70]}...")

        try:
            self.driver.get(url)
        except Exception:
            # retry once
            time.sleep(2)
            self.driver.get(url)

        time.sleep(5)
        self._dismiss_cookie_banner()

        # scroll pentru lazy-load
        try:
            for frac in (0.2, 0.5, 0.8, 1.0, 0.0):
                self.driver.execute_script(
                    "window.scrollTo(0, document.body.scrollHeight*arguments[0]);",
                    frac,
                )
                time.sleep(0.6)
        except Exception:
            pass

        # debug screenshot optional (nu sparge)
        try:
            ss = self.driver.get_screenshot_as_png()
            st.image(ss, caption="XD pagina produs", width=700)
        except Exception:
            pass

        # text vizibil + html
        try:
            visible_text = self.driver.execute_script("return document.body.innerText || '';")
            st.text_area("DEBUG: Text vizibil pe pagină", visible_text[:2000], height=200)
        except Exception:
            visible_text = ""

        page_source = self.driver.page_source or ""
        soup = BeautifulSoup(page_source, "html.parser")

        # nume
        name = ""
        h1 = soup.select_one("h1")
        if h1:
            name = h1.get_text(strip=True)
        if not name:
            name = "Produs XD Connects"

        # sku
        sku = ""
        m = re.search(r"variantId=([A-Z0-9\.]+)", url)
        if m:
            sku = m.group(1).upper()
        if not sku:
            im = re.search(r"Item\s*no\.?\s*:?\s*([A-Z0-9\.]+)", page_source, re.I)
            if im:
                sku = im.group(1).upper()

        # price (EUR)
        price_eur = 0.0
        try:
            price_info = self.driver.execute_script(
                """
                var body = (document.body && (document.body.innerText || document.body.textContent)) || '';
                function pick(re){ var m = body.match(re); return m ? m[1] : null; }
                var p = null;
                // Prefer explicit 'Price €..'
                p = pick(/Price\s*[€]\s*(\d{1,6}(?:[\.,]\d{1,2})?)/i);
                if(!p) p = pick(/(?:From\s+)?[€]\s*(\d{1,6}(?:[\.,]\d{1,2})?)/i);
                if(!p) p = pick(/(?:From\s+)?(\d{1,6}(?:[\.,]\d{1,2})?)\s*EUR/i);
                return p || '';
                """
            )
            if price_info:
                price_eur = clean_price(str(price_info))
        except Exception:
            price_eur = 0.0

        if price_eur <= 0:
            # regex in html
            for pat in [
                r"Price\s*[€]\s*(\d{1,6}(?:[\.,]\d{1,2})?)",
                r"[€]\s*(\d{1,6}(?:[\.,]\d{1,2})?)",
                r"(\d{1,6}(?:[\.,]\d{1,2})?)\s*EUR",
            ]:
                mm = re.search(pat, page_source, re.I)
                if mm:
                    price_eur = clean_price(mm.group(1))
                    break

        st.info(f"💰 PREȚ: {price_eur} EUR")

        # description + specs from Product details table (no clicks)
        description_text = ""
        specifications: dict[str, str] = {}

        # parse tables: look for key/value rows, prioritize ones containing 'Description'
        for table in soup.select("table"):
            rows = table.select("tr")
            for row in rows:
                cells = row.select("th,td")
                if len(cells) < 2:
                    continue
                k = cells[0].get_text(" ", strip=True)
                v = cells[1].get_text(" ", strip=True)
                if not k or not v:
                    continue

                k_norm = k.strip()
                v_norm = re.sub(r"\s+", " ", v).strip()

                # skip price/qty tables
                if k_norm.lower() in {"quantity", "printed*", "plain"}:
                    continue

                if k_norm.lower() in {"description", "descriere"}:
                    description_text = v_norm
                else:
                    specifications[k_norm] = v_norm

        # fallback description from visible_text pattern
        if not description_text:
            mdesc = re.search(r"\bDescription\b\s*\t\s*(.+)", visible_text, flags=re.I)
            if mdesc:
                description_text = mdesc.group(1).strip()

        description_html = ""
        if description_text:
            # split in sentences/lines for nicer html
            parts = [p.strip() for p in re.split(r"\n+", description_text) if p.strip()]
            if len(parts) == 1:
                description_html = f"<p>{parts[0]}</p>"
            else:
                description_html = "<p>" + "</p><p>".join(parts[:15]) + "</p>"

        # colours
        colors: list[str] = []
        current_color = self._extract_current_colour_from_text(visible_text) or ""
        if current_color:
            colors = [current_color]

        # best-effort options from dropdown; keep current first
        try:
            opts = self._extract_colour_options_best_effort()
            if opts:
                merged = []
                if current_color:
                    merged.append(current_color)
                for o in opts:
                    if o and o.lower() not in {m.lower() for m in merged}:
                        merged.append(o)
                colors = merged
        except Exception:
            pass

        # images
        images = []
        try:
            # src-based
            for img in soup.select("img"):
                src = img.get("src") or img.get("data-src") or ""
                if not src:
                    continue
                if any(x in src.lower() for x in ["logo", "icon", "sprite", "gif"]):
                    continue
                absu = make_absolute_url(src, self.base_url)
                if absu and absu not in images:
                    images.append(absu)

            # background-image
            for el in soup.select("[style*='background-image']"):
                style = el.get("style", "")
                m = re.search(r"background-image\s*:\s*url\(['\"]?([^'\")]+)", style, re.I)
                if m:
                    absu = make_absolute_url(m.group(1), self.base_url)
                    if absu and absu not in images:
                        images.append(absu)
        except Exception:
            pass

        # build product
        product = {
            "name": name,
            "sku": sku,
            "price_original": float(price_eur) if price_eur else 0.0,
            "currency": "EUR",
            "description": description_html,
            "specifications": specifications,
            "colors": colors,
            "images": images,
            "stock": 1,
            "url": url,
            "source": "xdconnects",
        }
        return product
