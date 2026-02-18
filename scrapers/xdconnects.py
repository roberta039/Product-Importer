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

            # Click tab-uri
            try:
                tabs = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    "[role='tab'], .nav-tabs a, "
                    "[class*='tab'] a, "
                    "[class*='tab'] button"
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
                    // RON (1-2 zecimale)
                    var ronMatch = body.match(
                        /(?:From\\s+)?(\\d{1,6}(?:[.,]\\d{1,2})?)\\s*RON/i
                    );
                    if (ronMatch) {
                        result.price = ronMatch[1];
                        result.currency = 'RON';
                        return result;
                    }

                    // EUR cu simbol € (permite 73.8 / 73,80 / 73)
                    var eurMatch = body.match(
                        /(?:From\\s+)?[€]\\s*(\\d{1,6}(?:[.,]\\d{1,2})?)/
                    );
                    if (eurMatch) {
                        result.price = eurMatch[1];
                        result.currency = 'EUR';
                        return result;
                    }

                    // EUR text (1-2 zecimale)
                    var eurMatch2 = body.match(
                        /(?:From\\s+)?(\\d{1,6}(?:[.,]\\d{1,2})?)\\s*EUR/i
                    );
                    if (eurMatch2) {
                        result.price = eurMatch2[1];
                        result.currency = 'EUR';
                        return result;
                    }

                    // Orice preț (1-2 zecimale)
                    var anyMatch = body.match(
                        /(?:From\\s+)?(\\d{1,6}(?:[.,]\\d{1,2})?)/
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
                    r'(\d{1,6}(?:[.,]\d{1,2})?)\s*RON',
                    r'[€]\s*(\d{1,6}(?:[.,]\d{1,2})?)',
                    r'(\d{1,6}(?:[.,]\d{1,2})?)\s*EUR',
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
                dr = self.driver.execute_script("""
                    var result = '';
                    var sels = [
                        '[class*="description"]',
                        '[class*="detail-desc"]',
                        '#description',
                        '.tab-pane',
                        '[class*="product-info"]',
                        '[class*="content"]',
                        'article'
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
                                t.indexOf('Cookie') === -1 &&
                                t.indexOf('cookie') === -1) {
                                result = t;
                            }
                        }
                        if (result.length > 100) break;
                    }
                    if (result.length < 30) {
                        var ps = document.querySelectorAll('p');
                        var arr = [];
                        for (var k = 0; k < ps.length; k++) {
                            var pt = ps[k].innerText.trim();
                            if (pt.length > 15 &&
                                pt.length < 500 &&
                                pt.indexOf('Cookie') === -1 &&
                                pt.indexOf('cookie') === -1 &&
                                pt.indexOf('Login') === -1) {
                                arr.push(pt);
                            }
                        }
                        if (arr.length > 0)
                            result = arr.join(' | ');
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
                            '</p><p>'.join(clean[:15]) +
                            '</p>'
                        )
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

            # Fallback: descrierea din tabel (Product details -> Description)
            if not description or len(description) < 30:
                try:
                    for row in soup.select('table tr'):
                        cells = row.select('th,td')
                        if len(cells) >= 2:
                            k = cells[0].get_text(' ', strip=True)
                            if k.strip().lower() == 'description':
                                v = cells[1].get_text(' ', strip=True)
                                if v and len(v) > 30:
                                    description = '<p>' + v + '</p>'
                                    break
                except Exception:
                    pass

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
                        var rows = tables[t]
                            .querySelectorAll('tr');
                        var isPrice = false;
                        for (var r = 0;
                             r < rows.length; r++) {
                            var cells = rows[r]
                                .querySelectorAll('td, th');
                            if (cells.length >= 2) {
                                var k = cells[0]
                                    .innerText.trim();
                                var v = cells[1]
                                    .innerText.trim();
                                // Skip price tables
                                if (k === 'Quantity' ||
                                    k === 'Printed*' ||
                                    k === 'Plain' ||
                                    v.indexOf('RON') > -1 ||
                                    v.indexOf('EUR') > -1 ||
                                    v.indexOf('€') > -1) {
                                    isPrice = true;
                                    continue;
                                }
                                if (!isPrice && k && v &&
                                    k.length < 50 &&
                                    v.length < 300) {
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
                            if (dk && dv && dk.length < 50 &&
                                dv.indexOf('€') === -1 &&
                                dv.indexOf('RON') === -1) {
                                specs[dk] = dv;
                            }
                        }
                    }
                    return specs;
                """)
                if sp and isinstance(sp, dict):
                    specifications = sp
            except Exception as e:
                st.warning(f"⚠️ SPEC: {str(e)[:50]}")

            # Fallback: parse tabele din HTML (page_source) chiar dacă sunt ascunse în tab
            if not specifications:
                try:
                    for table in soup.select('table'):
                        for row in table.select('tr'):
                            cells = row.select('th,td')
                            if len(cells) >= 2:
                                k = cells[0].get_text(' ', strip=True)
                                v = cells[1].get_text(' ', strip=True)
                                if not k or not v:
                                    continue
                                lk = k.lower()
                                if lk in ['quantity', 'cantitate', 'printed*', 'printed', 'plain', 'pret', 'price']:
                                    continue
                                # ignorăm tabele de preț
                                if any(x in v for x in ['€', 'RON', 'EUR']):
                                    continue
                                if len(k) < 60 and len(v) < 250:
                                    specifications[k] = v
                        if len(specifications) >= 8:
                            break
                except Exception:
                    pass

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

            # Fallback culoare curentă: linia imediat după "Item no."
            if not colors:
                try:
                    full_text = self.driver.execute_script(
                        "return document.body.innerText;"
                    )
                    cm = re.search(
                        r"Item no\.\s*[A-Z0-9\.]+\s*\n([A-Za-z][A-Za-z \-]{2,40})\n",
                        full_text
                    )
                    if cm:
                        colors = [cm.group(1).strip()]
                except Exception:
                    pass

            # Best-effort: listăm variantele din HTML (variantId=...) și colectăm culorile (max 10)
            try:
                variant_ids = set(
                    m.group(1).upper()
                    for m in re.finditer(r"variantId=([A-Za-z0-9\.]+)", page_source)
                )
                # păstrăm doar coduri de tip P705.709
                variant_ids = [v for v in variant_ids if re.match(r"^[A-Z]\d{3}\.\d{2,4}$", v)]
                variant_ids = sorted(variant_ids)
                if len(variant_ids) > 1:
                    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
                    parsed = urlparse(url)
                    q = parse_qs(parsed.query)
                    current_url = self.driver.current_url
                    collected = []
                    for vid in variant_ids[:10]:
                        q['variantId'] = [vid]
                        new_query = urlencode(q, doseq=True)
                        vurl = urlunparse(parsed._replace(query=new_query))
                        color_variants.append({'variant_id': vid, 'url': vurl})
                        try:
                            self.driver.get(vurl)
                            time.sleep(2.5)
                            txt = self.driver.execute_script("return document.body.innerText;")
                            cm2 = re.search(
                                r"Item no\.\s*[A-Z0-9\.]+\s*\n([A-Za-z][A-Za-z \-]{2,40})\n",
                                txt
                            )
                            if cm2:
                                c = cm2.group(1).strip()
                                if c and c not in collected:
                                    collected.append(c)
                        except Exception:
                            continue
                    # revenim la pagina inițială
                    try:
                        self.driver.get(current_url)
                        time.sleep(2)
                    except Exception:
                        pass
                    if collected:
                        colors = collected
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
