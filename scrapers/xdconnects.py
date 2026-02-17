# scrapers/xdconnects.py
# VERSIUNE 5.0 - fix EUR, imagini, culori, screenshot debug
"""
Scraper XD Connects v5.0
- Preț: EUR și RON
- Imagini: src direct + background-image
- Culori: swatch mic
- Screenshot debug
"""
import re
import time
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper
from utils.helpers import clean_price
from utils.image_handler import make_absolute_url
import streamlit as st
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import (
    NoSuchElementException, StaleElementReferenceException,
)


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
                btn = self.driver.find_element(
                    By.CSS_SELECTOR, sel
                )
                if btn.is_displayed():
                    self.driver.execute_script(
                        "arguments[0].click();", btn
                    )
                    time.sleep(2)
                    return
            except NoSuchElementException:
                continue
        try:
            self.driver.execute_script(
                "var s=['#CybotCookiebotDialog',"
                "'#CybotCookiebotDialogBodyUnderlay'];"
                "s.forEach(function(x){"
                "document.querySelectorAll(x).forEach("
                "function(e){e.remove();});"
                "});"
                "document.body.style.overflow='auto';"
            )
        except Exception:
            pass

    def _login_if_needed(self):
        if self._logged_in:
            return
        try:
            xd_user = st.secrets.get("SOURCES", {}).get(
                "XD_USER", ""
            )
            xd_pass = st.secrets.get("SOURCES", {}).get(
                "XD_PASS", ""
            )
            if not xd_user or not xd_pass:
                return
            self._init_driver()
            if not self.driver:
                return
            st.info("🔐 XD: Mă conectez...")
            self.driver.get(
                self.base_url + "/en-gb/profile/login"
            )
            time.sleep(5)
            self._dismiss_cookie_banner()
            time.sleep(1)
            for sel in [
                "input[type='email'][name='email']",
                "input[name='email']",
                "input[type='email']",
            ]:
                try:
                    for f in self.driver.find_elements(
                        By.CSS_SELECTOR, sel
                    ):
                        if f.is_displayed() and f.is_enabled():
                            f.clear()
                            f.send_keys(xd_user)
                            break
                    else:
                        continue
                    break
                except Exception:
                    continue
            for f in self.driver.find_elements(
                By.CSS_SELECTOR, "input[type='password']"
            ):
                if f.is_displayed() and f.is_enabled():
                    f.clear()
                    f.send_keys(xd_pass)
                    break
            self._dismiss_cookie_banner()
            for sel in [
                "form button[type='submit']",
                "button[type='submit']",
            ]:
                try:
                    for btn in self.driver.find_elements(
                        By.CSS_SELECTOR, sel
                    ):
                        if btn.is_displayed():
                            self.driver.execute_script(
                                "arguments[0].click();", btn
                            )
                            break
                    break
                except Exception:
                    continue
            time.sleep(6)
            self._logged_in = True
            st.success("✅ XD: Login reușit!")
        except Exception as e:
            st.warning(f"⚠️ XD login: {str(e)[:100]}")
            self._logged_in = True

    def _click_by_text(self, texts: list[str]) -> bool:
        """Click first visible element (button/link/tab) matching any text."""
        if not self.driver:
            return False

        # 1) XPath tries (exact then contains, case-insensitive)
        for t in texts:
            t = (t or "").strip()
            if not t:
                continue
            try:
                els = self.driver.find_elements(
                    By.XPATH,
                    f"//*[self::button or self::a or @role='tab'][normalize-space(.)='{t}']"
                )
                for el in els:
                    if el.is_displayed() and el.is_enabled():
                        self.driver.execute_script("arguments[0].click();", el)
                        time.sleep(1)
                        return True
            except Exception:
                pass

            try:
                els = self.driver.find_elements(
                    By.XPATH,
                    "//*[self::button or self::a or @role='tab']"
                    "[contains(translate(normalize-space(.),"
                    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),"
                    f"'{t.lower()}')]"
                )
                for el in els:
                    if el.is_displayed() and el.is_enabled():
                        self.driver.execute_script("arguments[0].click();", el)
                        time.sleep(1)
                        return True
            except Exception:
                pass

        # 2) JS fallback (handles nested spans)
        try:
            clicked = self.driver.execute_script(
                """
                const targets = arguments[0];
                const norm = (s) => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
                const all = Array.from(document.querySelectorAll(
                  'button,a,[role="tab"],[role="button"]'
                ));
                for (const t of targets){
                  const tt = norm(t);
                  if (!tt) continue;
                  for (const el of all){
                    const txt = norm(el.innerText);
                    if (!txt) continue;
                    if (txt === tt || txt.includes(tt)){
                      const r = el.getBoundingClientRect();
                      if (r.width>0 && r.height>0){ el.click(); return true; }
                    }
                  }
                }
                return false;
                """,
                texts,
            )
            if clicked:
                time.sleep(1)
                return True
        except Exception:
            pass
        return False

    def _get_product_details_html(self) -> str:
        """Best-effort: open Product details and return its HTML.
        On XD, description/specs are usually rendered inside a JS tab/accordion.
        """
        if not self.driver:
            return ""

        # Open section (multiple locales)
        self._click_by_text([
            "Product details", "Product Details",
            "Details", "Productinformatie", "Produktdetails",
            "Detalii produs", "Detalii",
        ])

        # Expand likely accordions within details
        try:
            self.driver.execute_script(
                """
                const btns = Array.from(document.querySelectorAll('button[aria-expanded="false"]'));
                for (const b of btns){
                  const t=(b.innerText||'').toLowerCase();
                  if (t.includes('product') || t.includes('detail') || t.includes('spec') || t.includes('details')){
                    try{ b.click(); }catch(e){}
                  }
                }
                """
            )
            time.sleep(1)
        except Exception:
            pass

        # Grab the most plausible container
        try:
            html = self.driver.execute_script(
                """
                function textLen(el){return (el && el.innerText ? el.innerText.trim().length : 0);}
                // 1) visible tabpanel
                let el = document.querySelector('[role="tabpanel"]:not([hidden])');
                if (el && textLen(el) > 80) return el.innerHTML;
                el = document.querySelector('[role="tabpanel"].active');
                if (el && textLen(el) > 80) return el.innerHTML;
                // 2) IDs/classes that hint product details
                el = document.querySelector('[id*="product-details" i], [class*="product-details" i], [data-testid*="product-details" i]');
                if (el && textLen(el) > 80) return el.innerHTML;
                // 3) container around the label
                const nodes = Array.from(document.querySelectorAll('h2,h3,h4,button,a,span,div'))
                  .filter(n => /product\s+details/i.test((n.innerText||'').trim()));
                for (const n of nodes){
                  const c = n.closest('section, article, div');
                  if (c && textLen(c) > 120) return c.innerHTML;
                }
                return '';
                """
            )
            return html or ""
        except Exception:
            return ""

    def scrape(self, url: str) -> dict | None:
        try:
            self._login_if_needed()
            self._init_driver()
            if not self.driver:
                return None

            st.info(f"📦 XD v5.0: {url[:70]}...")
            self.driver.get(url)
            time.sleep(7)
            self._dismiss_cookie_banner()
            time.sleep(2)

            # Scroll
            for frac in ['0.3', '0.5', '0.8', '1', '0']:
                self.driver.execute_script(
                    "window.scrollTo(0,"
                    "document.body.scrollHeight*"
                    + frac + ");"
                )
                time.sleep(0.8)

            # XD: open Product details tab early (where description/specs live)
            try:
                self._click_by_text([
                    "Product details", "Product Details",
                    "Productinformatie", "Produktdetails",
                    "Detalii produs",
                ])
            except Exception:
                pass

            # ═══ SCREENSHOT DEBUG ═══
            try:
                ss = self.driver.get_screenshot_as_png()
                st.image(ss, caption="XD pagina produs", width=700)
            except Exception:
                pass

            page_source = self.driver.page_source

            # ═══ DEBUG: primul 2000 caractere text vizibil ═══
            try:
                visible_text = self.driver.execute_script(
                    "return document.body.innerText"
                    ".substring(0, 2000);"
                )
                st.text_area(
                    "DEBUG: Text vizibil pe pagină",
                    visible_text,
                    height=200
                )
            except Exception:
                pass

            soup = BeautifulSoup(page_source, 'html.parser')

            # ═══ NUME ═══
            name = ""
            h1 = soup.select_one('h1')
            if h1:
                name = h1.get_text(strip=True)
            if not name:
                name = "Produs XD Connects"

            # ═══ SKU ═══
            sku = ""
            im = re.search(
                r'Item\s*no\.?\s*:?\s*([A-Z0-9.]+)',
                page_source, re.IGNORECASE
            )
            if im:
                sku = im.group(1).upper()
            if not sku:
                sm = re.search(
                    r'([pP]\d{3}\.\d{2,3})', url
                )
                if sm:
                    sku = sm.group(1).upper()

            # ═══ PREȚ (EUR + RON) ═══
            price = 0.0
            currency = 'EUR'
            try:
                price_info = self.driver.execute_script("""
                    var body = document.body.innerText;
                    var result = {price: '', currency: ''};

                    // RON
                    var ronMatch = body.match(
                        /(?:From\\s+)?(\\d{1,6}[.,]\\d{2})\\s*RON/i
                    );
                    if (ronMatch) {
                        result.price = ronMatch[1];
                        result.currency = 'RON';
                        return result;
                    }

                    // EUR cu simbol €
                    var eurMatch = body.match(
                        /(?:From\\s+)?[€]\\s*(\\d{1,6}[.,]\\d{2})/
                    );
                    if (eurMatch) {
                        result.price = eurMatch[1];
                        result.currency = 'EUR';
                        return result;
                    }

                    // EUR text
                    var eurMatch2 = body.match(
                        /(?:From\\s+)?(\\d{1,6}[.,]\\d{2})\\s*EUR/i
                    );
                    if (eurMatch2) {
                        result.price = eurMatch2[1];
                        result.currency = 'EUR';
                        return result;
                    }

                    // Orice preț cu .XX sau ,XX
                    var anyMatch = body.match(
                        /(?:From\\s+)?(\\d{1,6}[.,]\\d{2})/
                    );
                    if (anyMatch) {
                        result.price = anyMatch[1];
                        result.currency = 'EUR';
                        return result;
                    }

                    return result;
                """)
                if price_info:
                    price_str = price_info.get('price', '')
                    if price_str:
                        price = clean_price(str(price_str))
                    currency = price_info.get(
                        'currency', 'EUR'
                    )
            except Exception as e:
                st.warning(f"⚠️ PREȚ err: {str(e)[:50]}")

            if price <= 0:
                for pattern in [
                    r'(\d{1,6}[.,]\d{2})\s*RON',
                    r'[€]\s*(\d{1,6}[.,]\d{2})',
                    r'(\d{1,6}[.,]\d{2})\s*EUR',
                ]:
                    pm = re.search(
                        pattern, page_source, re.IGNORECASE
                    )
                    if pm:
                        price = clean_price(pm.group(1))
                        if 'RON' in pattern:
                            currency = 'RON'
                        else:
                            currency = 'EUR'
                        break

            st.info(f"💰 PREȚ: {price} {currency}")

            # ═══ DESCRIERE ═══
            description = ""
            try:
                # Primary: Product details HTML
                details_html = self._get_product_details_html()
                if details_html and len(details_html) > 50:
                    dsoup = BeautifulSoup(details_html, 'html.parser')
                    # Gather paragraphs or meaningful list items
                    paras = []
                    for el in dsoup.select('p'):
                        t = el.get_text(' ', strip=True)
                        if 30 <= len(t) <= 900 and 'cookie' not in t.lower():
                            paras.append(t)
                    if not paras:
                        for el in dsoup.select('li'):
                            t = el.get_text(' ', strip=True)
                            if 30 <= len(t) <= 250 and 'cookie' not in t.lower():
                                paras.append(t)
                    if paras:
                        description = '<p>' + '</p><p>'.join(paras[:6]) + '</p>'

                # Fallback: short summary near the title
                if not description or len(description) < 30:
                    dr = self.driver.execute_script("""
                        var h1 = document.querySelector('h1');
                        if (!h1) return '';
                        // search nearby blocks for a bullet summary line
                        var root = h1.closest('main, section, article, div') || document.body;
                        var txt = (root.innerText || '').replace(/\s+/g,' ').trim();
                        // line often contains material/volume/laptop size
                        var m = txt.match(/\b(rPET|polyester|PU)\b[\s\S]{0,140}/i);
                        return m ? m[0] : '';
                    """)
                    if dr and len(str(dr).strip()) > 20:
                        description = '<p>' + str(dr).strip() + '</p>'
            except Exception as e:
                st.warning(f"⚠️ DESC: {str(e)[:50]}")

            if not description or len(description) < 30:
                meta = soup.select_one(
                    'meta[name="description"]'
                )
                if meta:
                    mc = meta.get('content', '')
                    if mc and len(mc) > 15:
                        description = '<p>' + mc + '</p>'

            st.info(f"📝 DESC: {len(description)} car")

            # ═══ SPECIFICAȚII ═══
            specifications = {}
            try:
                details_html = self._get_product_details_html()
                if details_html and len(details_html) > 50:
                    dsoup = BeautifulSoup(details_html, 'html.parser')
                    # Tables
                    for row in dsoup.select('table tr'):
                        cells = row.find_all(['th', 'td'])
                        if len(cells) >= 2:
                            k = cells[0].get_text(' ', strip=True)
                            v = cells[1].get_text(' ', strip=True)
                            if not k or not v:
                                continue
                            if any(x in v for x in ['€', 'EUR', 'RON']):
                                continue
                            if len(k) <= 60 and len(v) <= 400:
                                specifications[k] = v
                    # Definition lists
                    dts = dsoup.select('dt')
                    dds = dsoup.select('dd')
                    for i in range(min(len(dts), len(dds))):
                        k = dts[i].get_text(' ', strip=True)
                        v = dds[i].get_text(' ', strip=True)
                        if k and v and len(k) <= 60 and len(v) <= 400:
                            if any(x in v for x in ['€', 'EUR', 'RON']):
                                continue
                            specifications[k] = v
                    # Key: value lines
                    if not specifications:
                        txt = dsoup.get_text('\n', strip=True)
                        for line in txt.split('\n'):
                            if ':' in line and 6 <= len(line) <= 140:
                                k, v = line.split(':', 1)
                                k = k.strip(); v = v.strip()
                                if k and v and len(k) <= 60 and len(v) <= 400:
                                    if any(x in v for x in ['€', 'EUR', 'RON']):
                                        continue
                                    specifications[k] = v

                # Final fallback (minimal)
                if not specifications:
                    sp = self.driver.execute_script("""
                        var specs = {};
                        var body = document.body.innerText || '';
                        var m = body.match(/Item\s*no\.?\s*([A-Z0-9.]+)/i);
                        if (m) specs['Item no.'] = m[1];
                        // Capture the USP line block if present
                        var uspIdx = body.toLowerCase().indexOf('integrated usb');
                        if (uspIdx > -1) {
                          specs['Product USPs'] = body.substring(uspIdx, uspIdx+220).replace(/\s+/g,' ').trim();
                        }
                        return specs;
                    """)
                    if sp and isinstance(sp, dict):
                        specifications = sp
            except Exception as e:
                st.warning(f"⚠️ SPEC: {str(e)[:50]}")

            # Fallback specs din bullet text
            if not specifications:
                bm = re.findall(
                    r'([\w\s]+)\s*[•●]\s*',
                    page_source
                )
                if bm and len(bm) >= 2:
                    for i, item in enumerate(bm[:6]):
                        item = item.strip()
                        if (
                            item and len(item) > 2
                            and len(item) < 50
                        ):
                            specifications[
                                f'Feature {i+1}'
                            ] = item

            st.info(
                f"📋 SPECS: {len(specifications)} = "
                f"{list(specifications.items())[:3]}"
            )

            # ═══ CULORI ═══
            colors = []
            color_variants = []
            try:
                cr = self.driver.execute_script("""
                    var results = [];
                    var links = document.querySelectorAll(
                        'a[href*="variantId"]'
                    );

                    for (var i = 0; i < links.length; i++) {
                        var el = links[i];
                        var name = (
                            el.getAttribute('title') ||
                            el.getAttribute('aria-label') ||
                            ''
                        ).trim();

                        var href =
                            el.getAttribute('href') || '';
                        var vm = href.match(
                            /variantId=([A-Z0-9.]+)/i
                        );
                        var vid = vm ?
                            vm[1].toUpperCase() : '';

                        if (!name && vid) name = vid;

                        var rect = el.getBoundingClientRect();

                        // Swatch = element MIC (<100px)
                        // cu background-color
                        var isSwatch = (
                            rect.width > 5 &&
                            rect.width < 100 &&
                            rect.height > 5 &&
                            rect.height < 100
                        );

                        // Excludem orice text lung sau
                        // cu cuvinte produse
                        var nameLen = name.length;
                        var isShort = nameLen > 0 && nameLen < 20;

                        if (isSwatch && isShort) {
                            var exists = false;
                            for (var r = 0;
                                 r < results.length; r++) {
                                if (results[r].name === name) {
                                    exists = true;
                                    break;
                                }
                            }
                            if (!exists) {
                                results.push({
                                    name: name,
                                    href: href,
                                    vid: vid
                                });
                            }
                        }
                    }
                    return results;
                """)
                if cr:
                    for item in cr:
                        c = item.get('name', '').strip()
                        if c and c not in colors:
                            colors.append(c)
                            color_variants.append({
                                'name': c,
                                'url': make_absolute_url(
                                    item.get('href', ''),
                                    self.base_url
                                ),
                                'image': '',
                                'color_code': item.get(
                                    'vid', ''
                                ),
                                'variant_id': item.get(
                                    'vid', ''
                                ),
                            })
            except Exception as e:
                st.warning(f"⚠️ CULORI: {str(e)[:50]}")

            # Fallback 1: current colour from specifications (Primary specifications)
            if not colors and specifications:
                for k in [
                    'Colour', 'Color', 'Culoare', 'Farbe',
                    'Primary specifications Colour',
                ]:
                    v = specifications.get(k)
                    if v:
                        c = str(v).strip()
                        if c and c not in colors:
                            colors.append(c)
                            color_variants.append({
                                'name': c,
                                'url': url,
                                'image': '',
                                'color_code': '',
                                'variant_id': '',
                            })
                        break

            # Fallback 2: try read selected colour from the UI near the "Colour:" label
            if not colors:
                try:
                    csel = self.driver.execute_script(
                        """
                        function norm(s){return (s||'').replace(/\s+/g,' ').trim();}
                        const body = document.body;
                        if (!body) return '';
                        // Find the label node that contains 'Colour:'
                        const nodes = Array.from(body.querySelectorAll('span,div,label,p'))
                          .filter(n => /\bcolour\b\s*:?/i.test(norm(n.innerText)));
                        for (const n of nodes){
                          // Common pattern: label then a value near it
                          const p = n.parentElement;
                          if (!p) continue;
                          const txt = norm(p.innerText);
                          // e.g. "Colour: light blue" or "Colour:\nlight blue"
                          const m = txt.match(/\bcolour\b\s*:?(?:\s|\n)+([a-z0-9\- ]{2,40})/i);
                          if (m) return norm(m[1]);
                          // Or a selected swatch button with aria-label
                          const sel = p.querySelector('[aria-current=\"true\"],[aria-selected=\"true\"],button.selected,.selected');
                          if (sel){
                            const a = norm(sel.getAttribute('aria-label')||sel.getAttribute('title')||sel.innerText);
                            if (a) return a;
                          }
                        }
                        return '';
                        """
                    )
                    if csel:
                        csel = str(csel).strip()
                        if csel and csel not in colors:
                            colors.append(csel)
                            color_variants.append({
                                'name': csel,
                                'url': url,
                                'image': '',
                                'color_code': '',
                                'variant_id': '',
                            })
                except Exception:
                    pass

            st.info(f"🎨 CULORI: {len(colors)} = {colors}")

            # ═══ IMAGINI ═══
            images = []
            try:
                ir = self.driver.execute_script("""
                    var results = [];

                    // Metoda 1: img tags
                    var imgs = document.querySelectorAll('img');
                    for (var i = 0; i < imgs.length; i++) {
                        var src =
                            imgs[i].getAttribute('data-src') ||
                            imgs[i].getAttribute('src') ||
                            imgs[i].getAttribute('data-lazy') ||
                            '';
                        if (src.length < 10) continue;

                        // Orice imagine mare de produs
                        var isProduct = (
                            src.indexOf('ProductImages') > -1 ||
                            src.indexOf('product') > -1 ||
                            src.indexOf('static.xd') > -1
                        );
                        var isBad = (
                            src.indexOf('icon') > -1 ||
                            src.indexOf('logo') > -1 ||
                            src.indexOf('flag') > -1 ||
                            src.indexOf('co2') > -1 ||
                            src.indexOf('badge') > -1 ||
                            src.indexOf('pixel') > -1 ||
                            src.indexOf('svg') > -1 ||
                            src.indexOf('data:') > -1
                        );

                        if (isProduct && !isBad) {
                            var large = src
                                .replace('/Small/', '/Large/')
                                .replace('/Thumb/', '/Large/')
                                .replace('/Medium/', '/Large/');
                            if (results.indexOf(large) === -1) {
                                results.push(large);
                            }
                        }
                    }

                    // Metoda 2: background-image
                    if (results.length === 0) {
                        var allEls = document.querySelectorAll(
                            '[style*="background"]'
                        );
                        for (var j = 0;
                             j < allEls.length; j++) {
                            var style =
                                allEls[j].getAttribute('style')
                                || '';
                            var bgMatch = style.match(
                                /url\\(['"]?([^'"\\)]+)/
                            );
                            if (bgMatch) {
                                var bgSrc = bgMatch[1];
                                if (bgSrc.indexOf(
                                        'ProductImages') > -1 ||
                                    bgSrc.indexOf(
                                        'static.xd') > -1) {
                                    var lg = bgSrc
                                        .replace(
                                            '/Small/', '/Large/'
                                        )
                                        .replace(
                                            '/Thumb/', '/Large/'
                                        );
                                    if (results.indexOf(
                                            lg) === -1) {
                                        results.push(lg);
                                    }
                                }
                            }
                        }
                    }

                    // Metoda 3: srcset
                    if (results.length === 0) {
                        var imgs2 = document.querySelectorAll(
                            'img[srcset]'
                        );
                        for (var k = 0;
                             k < imgs2.length; k++) {
                            var srcset =
                                imgs2[k].getAttribute('srcset')
                                || '';
                            var parts = srcset.split(',');
                            for (var p = parts.length - 1;
                                 p >= 0; p--) {
                                var u = parts[p].trim()
                                    .split(' ')[0];
                                if (u &&
                                    u.indexOf('Product') > -1) {
                                    if (results.indexOf(
                                            u) === -1) {
                                        results.push(u);
                                    }
                                    break;
                                }
                            }
                        }
                    }

                    // Debug: raportăm câte img am găsit total
                    var totalImgs = document
                        .querySelectorAll('img').length;
                    if (results.length === 0) {
                        // Ultima încercare: ORICE imagine
                        for (var z = 0; z < imgs.length; z++) {
                            var s =
                                imgs[z].getAttribute('src') ||
                                '';
                            var rect = imgs[z]
                                .getBoundingClientRect();
                            if (s.length > 10 &&
                                rect.width > 50 &&
                                rect.height > 50 &&
                                s.indexOf('data:') === -1 &&
                                s.indexOf('svg') === -1) {
                                results.push(s);
                                if (results.length >= 10)
                                    break;
                            }
                        }
                    }

                    return {
                        images: results,
                        totalImgs: totalImgs
                    };
                """)
                if ir:
                    images = ir.get('images', [])
                    total_imgs = ir.get('totalImgs', 0)
                    st.info(
                        f"📸 Total img pe pagină: "
                        f"{total_imgs}, "
                        f"extrase: {len(images)}"
                    )
            except Exception as e:
                st.warning(f"⚠️ IMG: {str(e)[:50]}")

            st.info(
                f"📸 IMG: {len(images)}"
                + (
                    f" ex: {images[0][:60]}..."
                    if images else " GOLE"
                )
            )

            # ═══ BUILD ═══
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
                category='Rucsacuri Anti-Furt',
                currency=currency,
            )
            product['color_variants'] = color_variants
            product['variant_images'] = {}

            st.success(
                f"✅ {name[:30]} | P:{price}{currency} | "
                f"D:{len(description)} | "
                f"S:{len(specifications)} | "
                f"C:{len(colors)} | I:{len(images)}"
            )

            return product

        except Exception as e:
            st.error(f"❌ XD: {str(e)}")
            return None
