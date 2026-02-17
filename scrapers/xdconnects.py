# scrapers/xdconnects.py
# VERSIUNE 3.0 - cu debug fortat
# Ultima actualizare: fix pret, descriere, culori, imagini Large
"""
Scraper pentru xdconnects.com
Fix: pret, descriere, specificatii, culori, imagini Large
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
            self.driver.execute_script("""
                ['#CybotCookiebotDialog',
                 '#CybotCookiebotDialogBodyUnderlay'
                ].forEach(function(s){
                    document.querySelectorAll(s).forEach(
                        function(el){el.remove();}
                    );
                });
                document.body.style.overflow='auto';
            """)
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

    def scrape(self, url: str) -> dict | None:
        try:
            self._login_if_needed()
            self._init_driver()
            if not self.driver:
                return None

            # ═══ VERSIUNE 3.0 DEBUG ═══
            st.info(f"📦 XD v3.0: Scrapez {url[:70]}...")
            self.driver.get(url)
            time.sleep(6)
            self._dismiss_cookie_banner()
            time.sleep(2)

            # Scroll complet
            self.driver.execute_script(
                "window.scrollTo(0, "
                "document.body.scrollHeight/3);"
            )
            time.sleep(1)
            self.driver.execute_script(
                "window.scrollTo(0, "
                "document.body.scrollHeight/2);"
            )
            time.sleep(1)
            self.driver.execute_script(
                "window.scrollTo(0, "
                "document.body.scrollHeight);"
            )
            time.sleep(1)
            self.driver.execute_script(
                "window.scrollTo(0, 0);"
            )
            time.sleep(1)

            # Click pe tab-uri description/specifications
            try:
                tabs = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    "[role='tab'], .nav-tabs a, "
                    "[class*='tab'] a, [class*='tab'] button"
                )
                for tab in tabs:
                    try:
                        txt = tab.text.lower().strip()
                        if any(
                            kw in txt
                            for kw in [
                                'descri', 'specifi',
                                'detail', 'feature',
                            ]
                        ):
                            self.driver.execute_script(
                                "arguments[0].click();", tab
                            )
                            time.sleep(1)
                    except Exception:
                        continue
            except Exception:
                pass

            page_source = self.driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')

            # ═══ NUME ═══
            name = ""
            h1 = soup.select_one('h1')
            if h1:
                name = h1.get_text(strip=True)
            if not name:
                name = "Produs XD Connects"
            st.info(f"📋 XD NUME: {name}")

            # ═══ SKU ═══
            sku = ""
            item_match = re.search(
                r'Item\s*no\.?\s*:?\s*([A-Z0-9.]+)',
                page_source, re.IGNORECASE
            )
            if item_match:
                sku = item_match.group(1).upper()
            if not sku:
                sm = re.search(r'([pP]\d{3}\.\d{2,3})', url)
                if sm:
                    sku = sm.group(1).upper()
            st.info(f"📋 XD SKU: {sku}")

            # ═══ PREȚ ═══
            price = 0.0
            try:
                price_result = self.driver.execute_script("""
                    var body = document.body.innerText;
                    var m = body.match(
                        /(?:From\\s+)?(\\d{1,5}[.,]\\d{2})\\s*RON/i
                    );
                    if (m) return m[1];

                    var els = document.querySelectorAll(
                        '[class*="price"], .price'
                    );
                    for (var i = 0; i < els.length; i++) {
                        var t = els[i].innerText.trim();
                        var pm = t.match(/(\\d{1,5}[.,]\\d{2})/);
                        if (pm) return pm[1];
                    }
                    return '';
                """)
                if price_result:
                    price = clean_price(str(price_result))
            except Exception as e:
                st.warning(f"⚠️ XD PREȚ JS err: {str(e)[:50]}")

            if price <= 0:
                pm = re.search(
                    r'(\d{1,5}[.,]\d{2})\s*RON',
                    page_source, re.IGNORECASE
                )
                if pm:
                    price = clean_price(pm.group(1))
            st.info(f"💰 XD PREȚ: {price} RON")

            # ═══ DESCRIERE ═══
            description = ""
            try:
                desc_result = self.driver.execute_script("""
                    var result = '';

                    // 1. Container description
                    var sels = [
                        '[class*="description"]',
                        '[class*="detail-desc"]',
                        '#description',
                        '.tab-pane.active',
                        '[class*="product-info"]',
                    ];
                    for (var i = 0; i < sels.length; i++) {
                        var els = document.querySelectorAll(sels[i]);
                        for (var j = 0; j < els.length; j++) {
                            var t = els[j].innerText.trim();
                            if (t.length > 30 &&
                                t.length < 5000 &&
                                t.length > result.length &&
                                t.indexOf('Accept') === -1 &&
                                t.indexOf('Cookie') === -1) {
                                result = t;
                            }
                        }
                        if (result.length > 80) break;
                    }

                    // 2. Bullet points sub produs
                    if (result.length < 30) {
                        var body = document.body.innerText;
                        var bm = body.match(
                            /([\\w]+\\s*[•●]\\s*[^\\n]{10,500})/
                        );
                        if (bm) result = bm[1];
                    }

                    // 3. Paragrafele
                    if (result.length < 30) {
                        var ps = document.querySelectorAll('p');
                        var texts = [];
                        for (var k = 0; k < ps.length; k++) {
                            var pt = ps[k].innerText.trim();
                            if (pt.length > 20 &&
                                pt.length < 500 &&
                                pt.indexOf('Cookie') === -1 &&
                                pt.indexOf('Accept') === -1 &&
                                pt.indexOf('Login') === -1) {
                                texts.push(pt);
                            }
                        }
                        if (texts.length > 0) {
                            result = texts.join(' ');
                        }
                    }

                    return result;
                """)
                if desc_result and len(str(desc_result)) > 15:
                    raw = str(desc_result).strip()
                    lines = raw.split('\n')
                    clean = []
                    for line in lines:
                        line = line.strip()
                        if (
                            line
                            and len(line) > 5
                            and 'cookie' not in line.lower()
                            and 'accept' not in line.lower()
                            and 'login' not in line.lower()
                            and 'ORDER' not in line
                            and 'Add to' not in line
                            and 'Adăugați' not in line
                        ):
                            clean.append(line)
                    if clean:
                        description = (
                            '<p>'
                            + '</p>\n<p>'.join(clean[:10])
                            + '</p>'
                        )
            except Exception as e:
                st.warning(
                    f"⚠️ XD DESC JS err: {str(e)[:50]}"
                )

            # Fallback meta description
            if not description or len(description) < 30:
                meta = soup.select_one(
                    'meta[name="description"]'
                )
                if meta:
                    mc = meta.get('content', '')
                    if mc and len(mc) > 15:
                        description = f"<p>{mc}</p>"

            # Fallback text produs
            if not description or len(description) < 30:
                tm = re.search(
                    r'((?:rPET|PVC|recycled|anti.?theft|'
                    r'volume|laptop|RFID|water)'
                    r'[^<\n]{10,500})',
                    page_source, re.IGNORECASE
                )
                if tm:
                    description = (
                        f"<p>{tm.group(1).strip()}</p>"
                    )

            st.info(
                f"📝 XD DESC: {len(description)} caractere"
            )

            # ═══ SPECIFICAȚII ═══
            specifications = {}
            try:
                spec_result = self.driver.execute_script("""
                    var specs = {};

                    // 1. Tabele
                    var tables = document.querySelectorAll('table');
                    for (var t = 0; t < tables.length; t++) {
                        var rows = tables[t].querySelectorAll('tr');
                        for (var r = 0; r < rows.length; r++) {
                            var cells = rows[r].querySelectorAll(
                                'td, th'
                            );
                            if (cells.length >= 2) {
                                var k = cells[0].innerText.trim();
                                var v = cells[1].innerText.trim();
                                if (k && v &&
                                    k.length < 50 &&
                                    v.length < 300 &&
                                    k !== 'Quantity' &&
                                    k !== 'Printed*' &&
                                    k.indexOf('RON') === -1) {
                                    specs[k] = v;
                                }
                            }
                        }
                        if (Object.keys(specs).length > 0) break;
                    }

                    // 2. dt/dd
                    if (Object.keys(specs).length === 0) {
                        var dts = document.querySelectorAll('dt');
                        var dds = document.querySelectorAll('dd');
                        var len = Math.min(
                            dts.length, dds.length
                        );
                        for (var i = 0; i < len; i++) {
                            var k = dts[i].innerText.trim();
                            var v = dds[i].innerText.trim();
                            if (k && v && k.length < 50) {
                                specs[k] = v;
                            }
                        }
                    }

                    // 3. Text "rPET • Volume 10.5L • ..."
                    if (Object.keys(specs).length === 0) {
                        var body = document.body.innerText;
                        var dm = body.match(
                            /((?:rPET|PVC|recycled|polyester)' +
                            '\\s*[•●][^\\n]{10,300})/i
                        );
                        if (dm) {
                            var items = dm[1].split(/[•●]/);
                            for (var d = 0;
                                 d < items.length; d++) {
                                var item = items[d].trim();
                                if (item && item.length > 2) {
                                    specs['Feature ' +
                                        (d+1)] = item;
                                }
                            }
                        }
                    }

                    return specs;
                """)
                if (
                    spec_result
                    and isinstance(spec_result, dict)
                ):
                    specifications = spec_result
            except Exception as e:
                st.warning(
                    f"⚠️ XD SPEC JS err: {str(e)[:50]}"
                )

            # Fallback specs din regex
            if not specifications:
                dm = re.search(
                    r'((?:rPET|PVC|recycled|anti.?theft|'
                    r'polyester)\s*[•●]\s*[^<\n]{10,300})',
                    page_source, re.IGNORECASE
                )
                if dm:
                    items = re.split(r'[•●]', dm.group(1))
                    for i, item in enumerate(items):
                        item = item.strip()
                        if item and len(item) > 2:
                            specifications[
                                f'Caracteristică {i+1}'
                            ] = item

            st.info(
                f"📋 XD SPECS: {len(specifications)} "
                f"({list(specifications.keys())[:3]})"
            )

            # ═══ CULORI ═══
            colors = []
            color_variants = []
            try:
                color_result = self.driver.execute_script("""
                    var results = [];

                    // Căutăm "Colour:" section
                    var all = document.querySelectorAll('*');
                    var section = null;
                    for (var i = 0; i < all.length; i++) {
                        var t = all[i].childNodes;
                        for (var c = 0; c < t.length; c++) {
                            if (t[c].nodeType === 3 &&
                                t[c].textContent.trim()
                                    .match(/^Colou?r:?$/i)) {
                                section = all[i].parentElement;
                                break;
                            }
                        }
                        if (section) break;
                    }

                    // Fallback: căutăm label-ul
                    if (!section) {
                        var labels = document.querySelectorAll(
                            'label, span, div'
                        );
                        for (var i = 0; i < labels.length; i++) {
                            var lt = labels[i].textContent.trim();
                            if (lt.match(/^Colou?r:?$/i)) {
                                section =
                                    labels[i].parentElement;
                                break;
                            }
                        }
                    }

                    if (section) {
                        var links = section.querySelectorAll(
                            'a[href*="variantId"]'
                        );
                        links.forEach(function(el) {
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

                            if (name && name.length < 25 &&
                                name.indexOf('Add') === -1 &&
                                name.indexOf('Adăugați') === -1 &&
                                name.indexOf('cart') === -1 &&
                                name.indexOf('coș') === -1) {
                                results.push({
                                    name: name,
                                    href: href,
                                    vid: vid
                                });
                            }
                        });
                    }

                    // Fallback: toate linkurile variantId
                    if (results.length === 0) {
                        var allLinks = document.querySelectorAll(
                            'a[href*="variantId"]'
                        );
                        allLinks.forEach(function(el) {
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

                            // FILTRU STRICT:
                            // exclus butoane add to cart
                            var isColorSwatch = (
                                name.length < 25 &&
                                name.indexOf('Add') === -1 &&
                                name.indexOf('Adăugați') === -1 &&
                                name.indexOf('cart') === -1 &&
                                name.indexOf('coș') === -1 &&
                                name.indexOf('ORDER') === -1 &&
                                name.indexOf('rucsac') === -1 &&
                                name.indexOf('Bobby') === -1 &&
                                name.indexOf('backpack') === -1
                            );

                            if (name && isColorSwatch &&
                                !results.some(
                                    function(r){
                                        return r.name === name;
                                    }
                                )) {
                                results.push({
                                    name: name,
                                    href: href,
                                    vid: vid
                                });
                            }
                        });
                    }

                    return results;
                """)

                if color_result:
                    for item in color_result:
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
                st.warning(
                    f"⚠️ XD CULORI err: {str(e)[:50]}"
                )

            st.info(
                f"🎨 XD CULORI: {len(colors)} = "
                f"{colors[:5]}"
            )

            # ═══ IMAGINI (Large) ═══
            images = []
            try:
                img_result = self.driver.execute_script("""
                    var results = [];
                    var imgs = document.querySelectorAll('img');
                    imgs.forEach(function(img) {
                        var src =
                            img.getAttribute('data-src') ||
                            img.getAttribute('src') || '';
                        if (src &&
                            src.indexOf('xdconnects.com') > -1 &&
                            src.indexOf('ProductImages') > -1 &&
                            src.indexOf('icon') === -1 &&
                            src.indexOf('logo') === -1 &&
                            src.indexOf('flag') === -1 &&
                            src.indexOf('co2') === -1 &&
                            src.indexOf('badge') === -1) {
                            // Small -> Large
                            var large = src
                                .replace('/Small/', '/Large/')
                                .replace('/Thumb/', '/Large/')
                                .replace('/Medium/', '/Large/');
                            if (results.indexOf(large) === -1) {
                                results.push(large);
                            }
                        }
                    });
                    return results;
                """)
                if img_result:
                    images = img_result
            except Exception:
                pass

            if not images:
                for img in soup.select('img'):
                    src = (
                        img.get('data-src')
                        or img.get('src')
                        or ''
                    )
                    if (
                        src
                        and 'ProductImages' in src
                        and 'icon' not in src.lower()
                        and 'logo' not in src.lower()
                    ):
                        large = (
                            src.replace('/Small/', '/Large/')
                            .replace('/Thumb/', '/Large/')
                        )
                        abs_url = make_absolute_url(
                            large, self.base_url
                        )
                        if abs_url not in images:
                            images.append(abs_url)

            st.info(f"📸 XD IMG: {len(images)} imagini")

            # ═══ BUILD PRODUCT ═══
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
                currency='RON',
            )
            product['color_variants'] = color_variants
            product['variant_images'] = {}

            st.success(
                f"✅ XD: {name[:30]} | "
                f"Preț:{price} | "
                f"Desc:{len(description)}c | "
                f"Spec:{len(specifications)} | "
                f"Cul:{len(colors)} | "
                f"Img:{len(images)}"
            )

            return product

        except Exception as e:
            st.error(f"❌ XD error: {str(e)}")
            return None
