"""scrapers/xdconnects.py

XD Connects scraper – v5.4 (2026-02-18)

Goals for project Step 1 (extract):
- Extract: name, sku, price (EUR/RON), description, specs, images, colours/variants.

Fixes included:
- Price parsing supports formats like: "Price €73.8" and "€ 73,80".
- Avoid risky tab/menu clicks (headless can navigate away).
- Description/specs: pull from Product details content using textContent (works even if
  content is in hidden tabs).
- Colour variants: tries to list all colours by opening the Colour selector (when present)
  and collecting option elements / links that carry variantId; falls back to current colour.
- Specs cleanup: drops price-table rows like Quantity / Printed / Plain.

"""

from __future__ import annotations

import re
import time
from bs4 import BeautifulSoup
import streamlit as st

from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from scrapers.base_scraper import BaseScraper
from utils.helpers import clean_price
from utils.image_handler import make_absolute_url


XD_SCRAPER_VERSION = "2026-02-18-xd-v5.4"
print("XD SCRAPER VERSION:", XD_SCRAPER_VERSION)


class XDConnectsScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.name = "xdconnects"
        self.base_url = "https://www.xdconnects.com"
        self._logged_in = False

    # ─────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────
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
        # Hard remove
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
        try:
            xd_user = st.secrets.get("SOURCES", {}).get("XD_USER", "")
            xd_pass = st.secrets.get("SOURCES", {}).get("XD_PASS", "")
            if not xd_user or not xd_pass:
                self._logged_in = True
                return

            self._init_driver()
            if not self.driver:
                return

            st.info("🔐 XD: Mă conectez...")
            self.driver.get(self.base_url + "/en-gb/profile/login")
            time.sleep(5)
            self._dismiss_cookie_banner()
            time.sleep(1)

            # email
            for sel in [
                "input[type='email'][name='email']",
                "input[name='email']",
                "input[type='email']",
            ]:
                try:
                    fields = self.driver.find_elements(By.CSS_SELECTOR, sel)
                    for f in fields:
                        if f.is_displayed() and f.is_enabled():
                            f.clear()
                            f.send_keys(xd_user)
                            raise StopIteration
                except StopIteration:
                    break
                except Exception:
                    continue

            # password
            try:
                pw_fields = self.driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
                for f in pw_fields:
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
                        if btn.is_displayed():
                            self.driver.execute_script("arguments[0].click();", btn)
                            raise StopIteration
                except StopIteration:
                    break
                except Exception:
                    continue

            time.sleep(6)
            self._logged_in = True
            st.success("✅ XD: Login reușit!")
        except Exception as e:
            st.warning(f"⚠️ XD login: {str(e)[:100]}")
            self._logged_in = True

    @staticmethod
    def _is_bad_color_name(txt: str) -> bool:
        t = (txt or "").strip().lower()
        if not t:
            return True
        bad_contains = [
            "recommended", "sales", "price", "pret", "vanzare",
            "quantity", "printed", "plain",
            "compare", "product details", "product", "details",
        ]
        if any(b in t for b in bad_contains):
            return True
        if len(t) > 40:
            return True
        return False

    # ─────────────────────────────────────────────────────────────
    # Main scrape
    # ─────────────────────────────────────────────────────────────
    def scrape(self, url: str) -> dict | None:
        try:
            self._login_if_needed()
            self._init_driver()
            if not self.driver:
                return None

            st.info(f"📦 XD v5.4: {url[:70]}...")
            self.driver.get(url)
            time.sleep(7)
            self._dismiss_cookie_banner()
            time.sleep(1.5)

            # gentle scroll to trigger lazy content
            for frac in [0.3, 0.6, 0.9, 1.0, 0.0]:
                self.driver.execute_script(
                    "window.scrollTo(0, document.body.scrollHeight * arguments[0]);",
                    frac,
                )
                time.sleep(0.7)

            # Debug screenshot (optional)
            try:
                ss = self.driver.get_screenshot_as_png()
                st.image(ss, caption="XD pagina produs", width=700)
            except Exception:
                pass

            page_source = self.driver.page_source
            soup = BeautifulSoup(page_source, "html.parser")

            # Debug text area (first 2000 chars)
            try:
                visible_text = self.driver.execute_script(
                    "return (document.body && document.body.innerText ? document.body.innerText : '').substring(0, 2000);"
                )
                st.text_area("DEBUG: Text vizibil pe pagină", visible_text, height=200)
            except Exception:
                pass

            # ── name
            name = ""
            h1 = soup.select_one("h1")
            if h1:
                name = h1.get_text(strip=True)
            if not name:
                name = "Produs XD Connects"

            # ── sku
            sku = ""
            im = re.search(r"Item\s*no\.?\s*: ?\s*([A-Z0-9.]+)", page_source, re.IGNORECASE)
            if im:
                sku = im.group(1).upper()
            if not sku:
                sm = re.search(r"([pP]\d{3}\.\d{2,3})", url)
                if sm:
                    sku = sm.group(1).upper()

            # ── price
            price = 0.0
            currency = "EUR"
            try:
                price_info = self.driver.execute_script(
                    """
                    var body = (document.body && document.body.innerText) ? document.body.innerText : '';
                    var result = {price: '', currency: ''};

                    // RON
                    var ronMatch = body.match(/(?:From\s+)?(\d{1,6}(?:[.,]\d{1,2})?)\s*RON/i);
                    if (ronMatch) { result.price = ronMatch[1]; result.currency = 'RON'; return result; }

                    // EUR (Price €73.8, € 73,80)
                    var eurMatch = body.match(/(?:From\s+)?(?:Price\s*)?[€]\s*(\d{1,6}(?:[.,]\d{1,2})?)/i);
                    if (eurMatch) { result.price = eurMatch[1]; result.currency = 'EUR'; return result; }

                    // EUR text
                    var eurMatch2 = body.match(/(?:From\s+)?(\d{1,6}(?:[.,]\d{1,2})?)\s*EUR/i);
                    if (eurMatch2) { result.price = eurMatch2[1]; result.currency = 'EUR'; return result; }

                    return result;
                    """
                )
                if price_info:
                    ps = (price_info.get("price") or "").strip()
                    if ps:
                        price = clean_price(ps)
                    currency = (price_info.get("currency") or "EUR").strip() or "EUR"
            except Exception as e:
                st.warning(f"⚠️ PREȚ JS err: {str(e)[:80]}")

            if price <= 0:
                for pattern in [
                    r"(\d{1,6}(?:[.,]\d{1,2})?)\s*RON",
                    r"(?:Price\s*)?[€]\s*(\d{1,6}(?:[.,]\d{1,2})?)",
                    r"(\d{1,6}(?:[.,]\d{1,2})?)\s*EUR",
                ]:
                    pm = re.search(pattern, page_source, re.IGNORECASE)
                    if pm:
                        price = clean_price(pm.group(1))
                        currency = "RON" if "RON" in pattern else "EUR"
                        break

            st.info(f"💰 PREȚ: {price} {currency}")

            # ── description & specs from Product details
            description = ""
            specifications: dict[str, str] = {}

            try:
                extracted = self.driver.execute_script(
                    """
                    function text(x){return (x && x.textContent) ? x.textContent.trim() : '';}

                    var out = {desc: '', specs: {}};

                    // Scan all tables, prefer one that contains a 'Description' row
                    var tables = Array.from(document.querySelectorAll('table'));
                    for (var t=0; t<tables.length; t++) {
                      var tb = tables[t];
                      var rows = Array.from(tb.querySelectorAll('tr'));
                      var local = {};
                      var foundDesc = '';
                      for (var r=0; r<rows.length; r++) {
                        var cells = rows[r].querySelectorAll('th,td');
                        if (cells.length >= 2) {
                          var k = text(cells[0]);
                          var v = text(cells[1]);
                          if (!k || !v) continue;
                          // keep row
                          local[k] = v;
                          if (k.toLowerCase() === 'description' && v.length > 40) {
                            foundDesc = v;
                          }
                        }
                      }
                      if (Object.keys(local).length >= 3) {
                        out.specs = local;
                        if (foundDesc) out.desc = foundDesc;
                        break;
                      }
                    }

                    // If no desc row, fallback to a long paragraph block
                    if (!out.desc) {
                      var blocks = Array.from(document.querySelectorAll('p, li'))
                        .map(e => text(e))
                        .filter(t => t.length > 60 && t.length < 4000);
                      blocks.sort((a,b)=>b.length-a.length);
                      if (blocks.length) out.desc = blocks[0];
                    }

                    return out;
                    """
                )

                if extracted:
                    raw_desc = (extracted.get("desc") or "").strip()
                    if raw_desc and len(raw_desc) > 60:
                        # convert to paragraphs
                        lines = [x.strip() for x in raw_desc.split("\n") if x.strip()]
                        # filter UI noise
                        cleaned = []
                        for ln in lines:
                            low = ln.lower()
                            if any(bad in low for bad in ["cookie", "accept", "login"]):
                                continue
                            cleaned.append(ln)
                        description = "<p>" + "</p><p>".join(cleaned[:20]) + "</p>" if cleaned else ""

                    sp = extracted.get("specs") or {}
                    if isinstance(sp, dict):
                        specifications = {str(k).strip(): str(v).strip() for k, v in sp.items() if str(k).strip()}

            except Exception as e:
                st.warning(f"⚠️ DESC/SPEC err: {str(e)[:80]}")

            # specs cleanup: remove price-table like rows
            drop_keys = {"quantity", "printed*", "plain", "recommended sales price"}
            for k in list(specifications.keys()):
                lk = k.strip().lower()
                if lk in drop_keys:
                    specifications.pop(k, None)

            st.info(f"📝 DESC: {len(description)} car")
            st.info(f"📋 SPECS: {len(specifications)} = {list(specifications.items())[:3]}")

            # ── colours / variants
            colors: list[str] = []
            color_variants: list[dict] = []

            # Try to open Colour dropdown (if present)
            try:
                xpath_candidates = [
                    "//*[normalize-space()='Colour:' or normalize-space()='Color:']/following::*[self::button or self::div][1]",
                    "//*[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'colour') and contains(.,':')]/following::*[1]",
                ]
                for xp in xpath_candidates:
                    try:
                        el = self.driver.find_element(By.XPATH, xp)
                        if el and el.is_displayed():
                            self.driver.execute_script("arguments[0].click();", el)
                            time.sleep(1.0)
                            break
                    except Exception:
                        continue

                js_variants = self.driver.execute_script(
                    """
                    var out=[];
                    function add(name, vid, href){
                      name=(name||'').trim();
                      vid=(vid||'').trim().toUpperCase();
                      href=href||'';
                      if(!vid){
                        var m = href.match(/variantId=([A-Z0-9.]+)/i);
                        if(m) vid=m[1].toUpperCase();
                      }
                      if(!name && vid) name = vid;
                      if(!name) return;
                      out.push({name:name, vid:vid, href:href});
                    }

                    // Links
                    document.querySelectorAll("a[href*='variantId']").forEach(a=>{
                      add(a.getAttribute('title')||a.getAttribute('aria-label')||a.textContent||'', '', a.getAttribute('href')||'');
                    });

                    // data-variant-id
                    document.querySelectorAll("[data-variant-id]").forEach(e=>{
                      add(e.getAttribute('aria-label')||e.getAttribute('title')||e.textContent||'', e.getAttribute('data-variant-id')||'', '');
                    });

                    // de-dup by vid+name
                    var seen={};
                    var uniq=[];
                    out.forEach(o=>{
                      var k=(o.vid||'')+'|'+(o.name||'');
                      if(!seen[k]){seen[k]=1; uniq.push(o);} 
                    });
                    return uniq;
                    """
                )

                if js_variants:
                    for it in js_variants:
                        nm = (it.get("name") or "").strip()
                        vid = (it.get("vid") or "").strip().upper()
                        href = it.get("href") or ""
                        if self._is_bad_color_name(nm):
                            continue
                        if nm not in colors:
                            colors.append(nm)
                        if vid or href:
                            color_variants.append(
                                {
                                    "name": nm,
                                    "url": make_absolute_url(href, self.base_url) if href else "",
                                    "image": "",
                                    "color_code": vid,
                                    "variant_id": vid,
                                }
                            )
            except Exception as e:
                st.warning(f"⚠️ VARIANTE: {str(e)[:80]}")

            # Fallback: current colour from specs
            if not colors:
                for key in ["Colour", "Color", "Culoare"]:
                    v = specifications.get(key)
                    if v and not self._is_bad_color_name(v):
                        colors = [v.strip()]
                        break

            # Fallback: from visible text near Item no.
            if not colors:
                try:
                    raw_text = self.driver.execute_script(
                        "return (document.body && document.body.innerText) ? document.body.innerText : '';"
                    )
                    m = re.search(
                        r"Item\s*no\.?\s*[A-Z0-9\.]+\s*\n([A-Za-z][A-Za-z \-]{2,40})\n",
                        raw_text,
                    )
                    if m:
                        c = m.group(1).strip()
                        if not self._is_bad_color_name(c):
                            colors = [c]
                except Exception:
                    pass

            st.info(f"🎨 CULORI: {len(colors)} = {colors}")

            # ── images
            images: list[str] = []
            try:
                ir = self.driver.execute_script(
                    """
                    var results = [];

                    function push(u){
                      if(!u) return;
                      if(u.indexOf('data:')===0) return;
                      if(u.indexOf('svg')>-1) return;
                      if(results.indexOf(u)===-1) results.push(u);
                    }

                    // img tags
                    var imgs = document.querySelectorAll('img');
                    for (var i = 0; i < imgs.length; i++) {
                      var src = imgs[i].getAttribute('data-src') || imgs[i].getAttribute('src') || imgs[i].getAttribute('data-lazy') || '';
                      if (src.length < 10) continue;

                      var isBad = (src.indexOf('icon')>-1 || src.indexOf('logo')>-1 || src.indexOf('flag')>-1 || src.indexOf('co2')>-1 || src.indexOf('badge')>-1 || src.indexOf('pixel')>-1);
                      if (isBad) continue;

                      // keep product-ish images
                      var isProduct = (src.toLowerCase().indexOf('product')>-1 || src.toLowerCase().indexOf('static.xd')>-1 || src.toLowerCase().indexOf('image')>-1);
                      if (!isProduct) continue;

                      var large = src.replace('/Small/', '/Large/').replace('/Thumb/', '/Large/').replace('/Medium/', '/Large/');
                      push(large);
                    }

                    // background-image
                    var allEls = document.querySelectorAll('[style*="background"]');
                    for (var j = 0; j < allEls.length; j++) {
                      var style = allEls[j].getAttribute('style') || '';
                      var bgMatch = style.match(/url\\(['\"]?([^'\"\\)]+).*/);
                      if (bgMatch) {
                        var bgSrc = bgMatch[1];
                        if (bgSrc.length>10 && (bgSrc.indexOf('Product')>-1 || bgSrc.indexOf('product')>-1)) {
                          push(bgSrc.replace('/Small/', '/Large/').replace('/Thumb/', '/Large/'));
                        }
                      }
                    }

                    return {images: results, totalImgs: imgs.length};
                    """
                )
                if ir:
                    images = ir.get("images", []) or []
                    total_imgs = ir.get("totalImgs", 0)
                    st.info(f"📸 Total img pe pagină: {total_imgs}, extrase: {len(images)}")
            except Exception as e:
                st.warning(f"⚠️ IMG: {str(e)[:80]}")

            st.info(f"📸 IMG: {len(images)}" + (f" ex: {images[0][:60]}..." if images else " GOLE"))

            # ── build product
            product = self._build_product(
                name=name,
                sku=sku,
                price=price,
                description=description,
                images=images,
                colors=colors,
                specifications=specifications,
                source_url=url,
                source_site=self.name,
                category="Rucsacuri Anti-Furt",
                currency=currency,
            )
            product["color_variants"] = color_variants
            product["variant_images"] = {}

            st.success(
                f"✅ {name[:30]} | P:{price}{currency} | D:{len(description)} | "
                f"S:{len(specifications)} | C:{len(colors)} | I:{len(images)}"
            )

            return product

        except Exception as e:
            st.error(f"❌ XD: {str(e)}")
            return None
