# scrapers/xdconnects.py
# VERSIUNE 4.0 - fix regex JS, culori, imagini
"""
Scraper XD Connects v4.0
Fix: regex JS, culori Images, imagini 0
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
                "document.querySelectorAll(x)"
                ".forEach(function(e){e.remove();});"
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

    def scrape(self, url: str) -> dict | None:
        try:
            self._login_if_needed()
            self._init_driver()
            if not self.driver:
                return None

            st.info(f"📦 XD v4.0: {url[:70]}...")
            self.driver.get(url)
            time.sleep(6)
            self._dismiss_cookie_banner()
            time.sleep(2)

            # Scroll
            for frac in ['0.3', '0.5', '0.8', '1', '0']:
                self.driver.execute_script(
                    "window.scrollTo(0, "
                    "document.body.scrollHeight * "
                    + frac + ");"
                )
                time.sleep(0.8)

            # Click tab-uri
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
            st.info(f"📋 NUME: {name}")

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

            # ═══ PREȚ ═══
            price = 0.0
            try:
                pr = self.driver.execute_script(
                    "var b=document.body.innerText;"
                    "var m=b.match("
                    "/(?:From\\\\s+)?(\\\\d{1,5}[.,]\\\\d{2})"
                    "\\\\s*RON/i);"
                    "if(m)return m[1];"
                    "var e=document.querySelectorAll("
                    "'[class*=\"price\"]');"
                    "for(var i=0;i<e.length;i++){"
                    "var t=e[i].innerText;"
                    "var p=t.match(/(\\\\d{1,5}[.,]\\\\d{2})/);"
                    "if(p)return p[1];}"
                    "return '';"
                )
                if pr:
                    price = clean_price(str(pr))
            except Exception:
                pass
            if price <= 0:
                pm = re.search(
                    r'(\d{1,5}[.,]\d{2})\s*RON',
                    page_source
                )
                if pm:
                    price = clean_price(pm.group(1))
            st.info(f"💰 PREȚ: {price} RON")

            # ═══ DESCRIERE ═══
            description = ""
            try:
                dr = self.driver.execute_script("""
                    var result = '';
                    var sels = [
                        '[class*="description"]',
                        '[class*="detail-desc"]',
                        '#description',
                        '.tab-pane.active',
                        '[class*="product-info"]'
                    ];
                    for (var i = 0; i < sels.length; i++) {
                        var els = document.querySelectorAll(
                            sels[i]
                        );
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
                    if (result.length < 30) {
                        var ps = document.querySelectorAll('p');
                        var arr = [];
                        for (var k = 0; k < ps.length; k++) {
                            var pt = ps[k].innerText.trim();
                            if (pt.length > 20 &&
                                pt.length < 500 &&
                                pt.indexOf('Cookie') === -1 &&
                                pt.indexOf('Login') === -1) {
                                arr.push(pt);
                            }
                        }
                        if (arr.length > 0) {
                            result = arr.join(' ');
                        }
                    }
                    return result;
                """)
                if dr and len(str(dr)) > 15:
                    raw = str(dr).strip()
                    lines = raw.split('\n')
                    clean = []
                    for line in lines:
                        line = line.strip()
                        if (
                            line and len(line) > 5
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
                            '<p>' +
                            '</p><p>'.join(clean[:10]) +
                            '</p>'
                        )
            except Exception as e:
                st.warning(f"⚠️ DESC err: {str(e)[:50]}")

            if not description or len(description) < 30:
                meta = soup.select_one(
                    'meta[name="description"]'
                )
                if meta:
                    mc = meta.get('content', '')
                    if mc and len(mc) > 15:
                        description = '<p>' + mc + '</p>'

            if not description or len(description) < 30:
                tm = re.search(
                    r'((?:rPET|PVC|recycled|anti.?theft|'
                    r'volume|laptop|RFID|water)'
                    r'[^<\n]{10,500})',
                    page_source, re.IGNORECASE
                )
                if tm:
                    description = (
                        '<p>' + tm.group(1).strip() + '</p>'
                    )

            st.info(f"📝 DESC: {len(description)} car")

            # ═══ SPECIFICAȚII ═══
            specifications = {}
            try:
                sp = self.driver.execute_script("""
                    var specs = {};
                    var tables = document.querySelectorAll(
                        'table'
                    );
                    for (var t = 0; t < tables.length; t++) {
                        var rows = tables[t].querySelectorAll(
                            'tr'
                        );
                        for (var r = 0; r < rows.length; r++) {
                            var cells = rows[r]
                                .querySelectorAll('td, th');
                            if (cells.length >= 2) {
                                var k = cells[0]
                                    .innerText.trim();
                                var v = cells[1]
                                    .innerText.trim();
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
                        if (Object.keys(specs).length > 0)
                            break;
                    }
                    if (Object.keys(specs).length === 0) {
                        var dts = document.querySelectorAll(
                            'dt'
                        );
                        var dds = document.querySelectorAll(
                            'dd'
                        );
                        var n = Math.min(
                            dts.length, dds.length
                        );
                        for (var i = 0; i < n; i++) {
                            var dk = dts[i].innerText.trim();
                            var dv = dds[i].innerText.trim();
                            if (dk && dv && dk.length < 50) {
                                specs[dk] = dv;
                            }
                        }
                    }
                    return specs;
                """)
                if sp and isinstance(sp, dict):
                    specifications = sp
            except Exception as e:
                st.warning(f"⚠️ SPEC err: {str(e)[:50]}")

            # Fallback: regex pe bullet text
            if not specifications:
                bm = re.search(
                    r'((?:rPET|PVC|recycled|anti.?theft|'
                    r'polyester)\s*'
                    + r'[\u2022\u25CF•●]'
                    + r'\s*[^\n<]{10,300})',
                    page_source, re.IGNORECASE
                )
                if bm:
                    parts = re.split(
                        r'[\u2022\u25CF•●]', bm.group(1)
                    )
                    for i, p in enumerate(parts):
                        p = p.strip()
                        if p and len(p) > 2:
                            specifications[
                                'Feature ' + str(i+1)
                            ] = p

            st.info(
                f"📋 SPECS: {len(specifications)} "
                f"= {list(specifications.items())[:3]}"
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

                        // Dimensiunea elementului
                        var rect = el.getBoundingClientRect();
                        var isSmall = (
                            rect.width < 80 &&
                            rect.height < 80 &&
                            rect.width > 5 &&
                            rect.height > 5
                        );

                        // Filtrare strictă
                        var bad = [
                            'Add', 'add', 'cart', 'Cart',
                            'ORDER', 'order', 'Images',
                            'images', 'coș', 'Adăugați',
                            'rucsac', 'Rucsac', 'Bobby',
                            'bobby', 'backpack', 'Backpack',
                            'Hero', 'hero', 'Small', 'small',
                            'Anti', 'anti', 'theft', 'MORE',
                            'more', 'MEDIA', 'media',
                            'Download', 'download'
                        ];

                        var isBad = false;
                        for (var b = 0; b < bad.length; b++) {
                            if (name.indexOf(bad[b]) !== -1) {
                                isBad = true;
                                break;
                            }
                        }

                        // Acceptăm doar elementele mici
                        // (swatches de culoare) SAU cu nume
                        // scurt de culoare
                        var isColor = (
                            !isBad &&
                            name.length > 0 &&
                            name.length < 25 &&
                            (isSmall || name.length < 15)
                        );

                        if (isColor) {
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
                                    vid: vid,
                                    w: rect.width,
                                    h: rect.height
                                });
                            }
                        }
                    });

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
                st.warning(
                    f"⚠️ CULORI err: {str(e)[:50]}"
                )

            st.info(
                f"🎨 CULORI: {len(colors)} = {colors[:6]}"
            )

            # ═══ IMAGINI ═══
            images = []
            try:
                ir = self.driver.execute_script("""
                    var results = [];
                    var imgs = document.querySelectorAll(
                        'img'
                    );
                    for (var i = 0; i < imgs.length; i++) {
                        var src =
                            imgs[i].getAttribute('data-src') ||
                            imgs[i].getAttribute('src') || '';

                        // Verificăm dimensiunea
                        var rect = imgs[i]
                            .getBoundingClientRect();
                        var isBig = (
                            rect.width > 50 ||
                            rect.height > 50
                        );

                        if (src.length > 10 && isBig &&
                            src.indexOf('ProductImages') > -1 &&
                            src.indexOf('icon') === -1 &&
                            src.indexOf('logo') === -1 &&
                            src.indexOf('flag') === -1 &&
                            src.indexOf('co2') === -1 &&
                            src.indexOf('badge') === -1 &&
                            src.indexOf('pixel') === -1) {

                            var large = src
                                .replace('/Small/', '/Large/')
                                .replace('/Thumb/', '/Large/')
                                .replace('/Medium/', '/Large/');

                            if (results.indexOf(large) === -1) {
                                results.push(large);
                            }
                        }
                    }

                    // Fallback: orice img mare cu xdconnects
                    if (results.length === 0) {
                        for (var i = 0; i < imgs.length; i++) {
                            var src =
                                imgs[i].getAttribute('data-src') ||
                                imgs[i].getAttribute('src') || '';
                            var rect = imgs[i]
                                .getBoundingClientRect();

                            if (src.length > 10 &&
                                rect.width > 30 &&
                                rect.height > 30 &&
                                (src.indexOf('xdconnects') > -1 ||
                                 src.indexOf('static') > -1) &&
                                src.indexOf('icon') === -1 &&
                                src.indexOf('logo') === -1) {
                                if (results.indexOf(src) === -1) {
                                    results.push(src);
                                }
                            }
                        }
                    }

                    return results;
                """)
                if ir:
                    images = ir
            except Exception as e:
                st.warning(f"⚠️ IMG err: {str(e)[:50]}")

            # Fallback imagini din soup
            if not images:
                for img in soup.select('img'):
                    src = (
                        img.get('data-src')
                        or img.get('src')
                        or ''
                    )
                    if src and len(src) > 10:
                        if (
                            'xdconnects' in src
                            or 'static' in src
                        ):
                            if (
                                'icon' not in src.lower()
                                and 'logo' not in src.lower()
                                and 'co2' not in src.lower()
                            ):
                                large = (
                                    src.replace(
                                        '/Small/', '/Large/'
                                    ).replace(
                                        '/Thumb/', '/Large/'
                                    )
                                )
                                abs_url = make_absolute_url(
                                    large, self.base_url
                                )
                                if abs_url not in images:
                                    images.append(abs_url)

            st.info(f"📸 IMG: {len(images)} imagini")

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
                currency='RON',
            )
            product['color_variants'] = color_variants
            product['variant_images'] = {}

            st.success(
                f"✅ {name[:30]} | P:{price} | "
                f"D:{len(description)} | "
                f"S:{len(specifications)} | "
                f"C:{len(colors)} | I:{len(images)}"
            )

            return product

        except Exception as e:
            st.error(f"❌ XD: {str(e)}")
            return None
