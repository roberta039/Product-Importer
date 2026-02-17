# scrapers/xdconnects.py
"""
Scraper pentru xdconnects.com (Bobby, Swiss Peak, Urban, etc.)
Testat pe: https://www.xdconnects.com/en-gb/bags-travel/anti-theft-backpacks/
bobby-hero-small-anti-theft-backpack-p705.70?variantId=P705.709

Structura paginii:
- Nume: h1
- Item no: text "Item no. P705.709"
- Preț: text "From 375,00 RON" sau "375,00 RON"
- Culori: pătrate colorate în secțiunea "Colour:"
- Descriere: sub secțiunea "Description" sau text sub produs
- Specificații: tabel cu proprietăți
- Imagini: din /en-gb/imgdtbs sau din pagină
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
        """Închide cookie banner (Cookiebot)."""
        if not self.driver:
            return
        for sel in [
            "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
            "#CybotCookiebotDialogBodyButtonAccept",
        ]:
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, sel)
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
                ].forEach(s => {
                    document.querySelectorAll(s).forEach(el => el.remove());
                });
                document.body.style.overflow = 'auto';
            """)
        except Exception:
            pass

    def _login_if_needed(self):
        """Login pe XD Connects."""
        if self._logged_in:
            return
        try:
            xd_user = st.secrets.get("SOURCES", {}).get("XD_USER", "")
            xd_pass = st.secrets.get("SOURCES", {}).get("XD_PASS", "")
            if not xd_user or not xd_pass:
                return

            self._init_driver()
            if not self.driver:
                return

            st.info("🔐 XD: Mă conectez...")
            self.driver.get(f"{self.base_url}/en-gb/profile/login")
            time.sleep(5)
            self._dismiss_cookie_banner()
            time.sleep(1)

            # Email
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
                            break
                    else:
                        continue
                    break
                except Exception:
                    continue

            # Parolă
            for f in self.driver.find_elements(
                By.CSS_SELECTOR, "input[type='password']"
            ):
                if f.is_displayed() and f.is_enabled():
                    f.clear()
                    f.send_keys(xd_pass)
                    break

            # Submit
            self._dismiss_cookie_banner()
            for sel in [
                "form button[type='submit']",
                "button[type='submit']",
            ]:
                try:
                    for btn in self.driver.find_elements(By.CSS_SELECTOR, sel):
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

    def _extract_product_variant_ids(self, url: str) -> tuple:
        """Extrage productId și variantId din URL."""
        product_id = ""
        variant_id = ""

        vm = re.search(r'variantId=([A-Z0-9.]+)', url, re.IGNORECASE)
        if vm:
            variant_id = vm.group(1).upper()

        pm = re.search(r'([pP]\d{3}\.\d{2})', url)
        if pm:
            product_id = pm.group(1).upper()

        if variant_id and not product_id:
            parts = variant_id.rsplit('.', 1)
            if len(parts) == 2 and len(parts[1]) > 2:
                product_id = f"{parts[0]}.{parts[1][:2]}"

        return product_id, variant_id

    def scrape(self, url: str) -> dict | None:
        """Scrape produs XD Connects."""
        try:
            self._login_if_needed()
            self._init_driver()
            if not self.driver:
                return None

            st.info(f"📦 XD: Scrapez {url[:70]}...")
            self.driver.get(url)
            time.sleep(6)
            self._dismiss_cookie_banner()
            time.sleep(2)

            # Scroll complet
            for pos in ['document.body.scrollHeight/3',
                        'document.body.scrollHeight/2',
                        'document.body.scrollHeight', '0']:
                self.driver.execute_script(
                    f"window.scrollTo(0, {pos});"
                )
                time.sleep(0.8)

            # Click pe tab-uri Description / Specifications
            try:
                tabs = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    "[role='tab'], .nav-tabs a, .tab-nav a, "
                    "[class*='tab'] a, [class*='tab'] button"
                )
                for tab in tabs:
                    try:
                        text = tab.text.lower().strip()
                        if any(kw in text for kw in [
                            'descri', 'specifi', 'detail',
                            'feature', 'info', 'propert',
                        ]):
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

            # ═══════════════════════════════
            # NUME
            # ═══════════════════════════════
            name = ""
            h1 = soup.select_one('h1')
            if h1:
                name = h1.get_text(strip=True)
            if not name:
                name = "Produs XD Connects"

            # ═══════════════════════════════
            # SKU / ITEM NO
            # ═══════════════════════════════
            sku = ""
            item_match = re.search(
                r'Item\s*no\.?\s*:?\s*([A-Z0-9.]+)',
                page_source, re.IGNORECASE
            )
            if item_match:
                sku = item_match.group(1).upper()
            if not sku:
                sku_match = re.search(r'([pP]\d{3}\.\d{2,3})', url)
                if sku_match:
                    sku = sku_match.group(1).upper()

            product_id, variant_id = (
                self._extract_product_variant_ids(url)
            )

            # ═══════════════════════════════
            # PREȚ - cu Selenium direct
            # ═══════════════════════════════
            price = 0.0
            try:
                price_text = self.driver.execute_script("""
                    // Căutăm textul cu preț RON
                    var allText = document.body.innerText;
                    var match = allText.match(
                        /(?:From\\s+)?(\\d+[.,]\\d{2})\\s*RON/i
                    );
                    if (match) return match[1];

                    // Fallback: căutăm elemente cu "price"
                    var priceEls = document.querySelectorAll(
                        '[class*="price"], .price'
                    );
                    for (var i = 0; i < priceEls.length; i++) {
                        var t = priceEls[i].innerText.trim();
                        var m = t.match(/(\\d+[.,]\\d{2})/);
                        if (m) return m[1];
                    }

                    return '';
                """)
                if price_text:
                    price = clean_price(price_text)
                    st.info(f"💰 XD: Preț extras: {price} RON")
            except Exception:
                pass

            if price <= 0:
                # Regex pe page source
                price_match = re.search(
                    r'(?:From\s+)?(\d+[.,]\d{2})\s*RON',
                    page_source, re.IGNORECASE
                )
                if price_match:
                    price = clean_price(price_match.group(1))

            # ═══════════════════════════════
            # DESCRIERE - cu Selenium
            # ═══════════════════════════════
            description = ""
            try:
                desc_text = self.driver.execute_script("""
                    var result = '';

                    // Metoda 1: Căutăm container description
                    var descSels = [
                        '[class*="description"]',
                        '[class*="detail-description"]',
                        '[class*="product-description"]',
                        '#description', '#tab-description',
                        '[data-tab="description"]',
                        '.tab-pane',
                    ];
                    for (var i = 0; i < descSels.length; i++) {
                        var els = document.querySelectorAll(
                            descSels[i]
                        );
                        for (var j = 0; j < els.length; j++) {
                            var text = els[j].innerText.trim();
                            if (text.length > 30 &&
                                text.length > result.length &&
                                text.length < 5000) {
                                result = text;
                            }
                        }
                        if (result.length > 100) break;
                    }

                    // Metoda 2: Textul de sub titlu/preț
                    if (result.length < 30) {
                        var h1 = document.querySelector('h1');
                        if (h1) {
                            var parent = h1.closest('div') ||
                                         h1.parentElement;
                            if (parent) {
                                var sibs = parent.parentElement
                                    .querySelectorAll('div, p, section');
                                for (var k = 0; k < sibs.length; k++) {
                                    var t = sibs[k].innerText.trim();
                                    if (t.length > 50 &&
                                        t.length < 3000 &&
                                        !t.includes('Add to cart') &&
                                        !t.includes('ORDER') &&
                                        t.length > result.length) {
                                        result = t;
                                    }
                                }
                            }
                        }
                    }

                    // Metoda 3: Bullet points / features
                    if (result.length < 30) {
                        var bullets = document.querySelectorAll(
                            'ul li, .feature, [class*="bullet"]'
                        );
                        var bulletTexts = [];
                        for (var b = 0; b < bullets.length; b++) {
                            var bt = bullets[b].innerText.trim();
                            if (bt.length > 10 && bt.length < 200 &&
                                !bt.includes('Login') &&
                                !bt.includes('Cart')) {
                                bulletTexts.push('• ' + bt);
                            }
                        }
                        if (bulletTexts.length >= 2) {
                            result = bulletTexts.join('\\n');
                        }
                    }

                    return result;
                """)

                if desc_text and len(desc_text) > 20:
                    # Curățăm și formatăm
                    lines = desc_text.split('\n')
                    clean_lines = []
                    for line in lines:
                        line = line.strip()
                        if (
                            line
                            and len(line) > 5
                            and 'cookie' not in line.lower()
                            and 'login' not in line.lower()
                            and 'cart' not in line.lower()
                            and 'ORDER' not in line
                            and 'Add to' not in line
                        ):
                            clean_lines.append(line)

                    if clean_lines:
                        description = '<p>' + '</p>\n<p>'.join(
                            clean_lines[:15]
                        ) + '</p>'
                        st.info(
                            f"📝 XD: Descriere: "
                            f"{len(description)} car"
                        )

            except Exception as e:
                st.warning(f"⚠️ XD desc: {str(e)[:60]}")

            # Fallback descriere din meta
            if not description or len(description) < 30:
                meta = soup.select_one('meta[name="description"]')
                if meta:
                    content = meta.get('content', '')
                    if content:
                        description = f"<p>{content}</p>"

            # Fallback din text scurt pe pagină
            if not description or len(description) < 30:
                short_match = re.search(
                    r'((?:rPET|PVC|recycled|anti-theft|volume|laptop|'
                    r'RFID|waterproof|water.?resistant)'
                    r'[^<]{10,500})',
                    page_source, re.IGNORECASE
                )
                if short_match:
                    description = f"<p>{short_match.group(1).strip()}</p>"

            # ═══════════════════════════════
            # SPECIFICAȚII - cu Selenium
            # ═══════════════════════════════
            specifications = {}
            try:
                js_specs = self.driver.execute_script("""
                    var specs = {};

                    // Metoda 1: Tabele
                    var tables = document.querySelectorAll('table');
                    for (var t = 0; t < tables.length; t++) {
                        var rows = tables[t].querySelectorAll('tr');
                        for (var r = 0; r < rows.length; r++) {
                            var cells = rows[r]
                                .querySelectorAll('td, th');
                            if (cells.length >= 2) {
                                var key = cells[0].innerText.trim();
                                var val = cells[1].innerText.trim();
                                if (key && val &&
                                    key.length < 50 &&
                                    val.length < 300 &&
                                    key !== 'Quantity' &&
                                    key !== 'Printed*' &&
                                    !key.includes('RON')) {
                                    specs[key] = val;
                                }
                            }
                        }
                        if (Object.keys(specs).length > 0) break;
                    }

                    // Metoda 2: dt/dd
                    if (Object.keys(specs).length === 0) {
                        var dts = document.querySelectorAll('dt');
                        var dds = document.querySelectorAll('dd');
                        for (var i = 0;
                             i < Math.min(dts.length, dds.length);
                             i++) {
                            var k = dts[i].innerText.trim();
                            var v = dds[i].innerText.trim();
                            if (k && v && k.length < 50) {
                                specs[k] = v;
                            }
                        }
                    }

                    // Metoda 3: Textul cu bullet points
                    if (Object.keys(specs).length === 0) {
                        var allText = document.body.innerText;
                        var bulletMatch = allText.match(
                            /[•●]\s*(.+)/g
                        );
                        if (bulletMatch) {
                            for (var b = 0;
                                 b < bulletMatch.length; b++) {
                                var bt = bulletMatch[b]
                                    .replace(/[•●]\s*/, '').trim();
                                if (bt.indexOf(':') > 0) {
                                    var parts = bt.split(':');
                                    specs[parts[0].trim()] =
                                        parts.slice(1).join(':')
                                        .trim();
                                } else if (bt.length > 5 &&
                                           bt.length < 100) {
                                    specs['Feature ' +
                                        (Object.keys(specs)
                                        .length + 1)] = bt;
                                }
                            }
                        }
                    }

                    // Metoda 4: Text sub produs
                    // "rPET • Volume 10.5L • Laptop..."
                    if (Object.keys(specs).length === 0) {
                        var allText = document.body.innerText;
                        var dotMatch = allText.match(
                            /([A-Za-z]+\\s*•\\s*[^\\n]+)/
                        );
                        if (dotMatch) {
                            var items = dotMatch[1].split('•');
                            for (var d = 0;
                                 d < items.length; d++) {
                                var item = items[d].trim();
                                if (item) {
                                    specs['Caracteristică ' +
                                        (d + 1)] = item;
                                }
                            }
                        }
                    }

                    return specs;
                """)

                if js_specs and isinstance(js_specs, dict):
                    specifications = js_specs
                    if specifications:
                        st.info(
                            f"📋 XD: {len(specifications)} specificații"
                        )

            except Exception as e:
                st.warning(f"⚠️ XD specs: {str(e)[:60]}")

            # Extrage "rPET • Volume 10.5L • Laptop..." ca specs
            if not specifications:
                dot_match = re.search(
                    r'((?:rPET|PVC|recycled|anti.?theft|polyester)'
                    r'\s*[•●]\s*[^<\n]{10,300})',
                    page_source, re.IGNORECASE
                )
                if dot_match:
                    items = dot_match.group(1).split('•')
                    for i, item in enumerate(items):
                        item = item.strip()
                        if item:
                            if ':' in item:
                                parts = item.split(':', 1)
                                specifications[
                                    parts[0].strip()
                                ] = parts[1].strip()
                            else:
                                specifications[
                                    f'Caracteristică {i+1}'
                                ] = item

            # ═══════════════════════════════
            # CULORI - cu Selenium
            # ═══════════════════════════════
            colors = []
            color_variants = []
            try:
                js_colors = self.driver.execute_script("""
                    var results = [];

                    // Căutăm secțiunea "Colour:"
                    var allEls = document.querySelectorAll('*');
                    var colourSection = null;
                    for (var i = 0; i < allEls.length; i++) {
                        var t = allEls[i].textContent.trim();
                        if (t === 'Colour:' || t === 'Color:') {
                            colourSection =
                                allEls[i].parentElement;
                            break;
                        }
                    }

                    if (colourSection) {
                        // Luăm elementele clickabile
                        var items = colourSection.querySelectorAll(
                            'a[href*="variantId"], a, button'
                        );
                        items.forEach(function(el) {
                            var name = (
                                el.getAttribute('title') ||
                                el.getAttribute('aria-label') ||
                                el.getAttribute('data-color') ||
                                ''
                            ).trim();

                            var href = (
                                el.getAttribute('href') || ''
                            );

                            // Extragem variantId
                            var vidMatch = href.match(
                                /variantId=([A-Z0-9.]+)/i
                            );
                            var vid = vidMatch ?
                                vidMatch[1].toUpperCase() : '';

                            // Dacă nu are nume, verificăm
                            // background-color
                            if (!name) {
                                var bg = window.getComputedStyle(el)
                                    .backgroundColor;
                                if (bg &&
                                    bg !== 'rgba(0, 0, 0, 0)' &&
                                    bg !== 'transparent') {
                                    name = vid || bg;
                                }
                            }

                            // Excludem butoanele care NU sunt
                            // de culoare
                            if (name &&
                                !name.includes('Add') &&
                                !name.includes('cart') &&
                                !name.includes('ORDER') &&
                                !name.includes('Adăugați') &&
                                name.length < 30) {
                                results.push({
                                    name: name,
                                    href: href,
                                    variantId: vid
                                });
                            }
                        });
                    }

                    // Fallback: linkuri cu variantId
                    if (results.length === 0) {
                        var links = document.querySelectorAll(
                            'a[href*="variantId"]'
                        );
                        links.forEach(function(el) {
                            var name = (
                                el.getAttribute('title') ||
                                el.getAttribute('aria-label') ||
                                ''
                            ).trim();
                            var href = el.getAttribute('href') || '';
                            var vidMatch = href.match(
                                /variantId=([A-Z0-9.]+)/i
                            );
                            var vid = vidMatch ?
                                vidMatch[1].toUpperCase() : '';

                            if (!name) name = vid;

                            if (name &&
                                !name.includes('Add') &&
                                !name.includes('cart') &&
                                name.length < 30 &&
                                !results.some(
                                    r => r.name === name
                                )) {
                                results.push({
                                    name: name,
                                    href: href,
                                    variantId: vid
                                });
                            }
                        });
                    }

                    return results;
                """)

                if js_colors:
                    for item in js_colors:
                        c_name = item.get('name', '').strip()
                        if c_name and c_name not in colors:
                            colors.append(c_name)
                            color_variants.append({
                                'name': c_name,
                                'url': make_absolute_url(
                                    item.get('href', ''),
                                    self.base_url
                                ),
                                'image': '',
                                'color_code': item.get(
                                    'variantId', ''
                                ),
                                'variant_id': item.get(
                                    'variantId', ''
                                ),
                            })

                if colors:
                    st.info(
                        f"🎨 XD: {len(colors)} culori: "
                        f"{', '.join(colors[:5])}"
                        + ("..." if len(colors) > 5 else "")
                    )

            except Exception as e:
                st.warning(f"⚠️ XD colors: {str(e)[:60]}")

            # ═══════════════════════════════
            # IMAGINI - din pagină (rezoluție mare)
            # ═══════════════════════════════
            images = []
            try:
                js_images = self.driver.execute_script("""
                    var results = [];
                    var imgs = document.querySelectorAll('img');

                    imgs.forEach(function(img) {
                        var src = img.getAttribute('data-src') ||
                                  img.getAttribute('src') ||
                                  img.getAttribute('data-lazy') || '';

                        if (src &&
                            src.includes('xdconnects.com') &&
                            src.includes('ProductImages') &&
                            !src.includes('icon') &&
                            !src.includes('logo') &&
                            !src.includes('flag') &&
                            !src.includes('co2') &&
                            !src.includes('badge')) {

                            // Convertim la rezoluție mare
                            // Small → Large sau Original
                            var largeSrc = src
                                .replace('/Small/', '/Large/')
                                .replace('/Thumb/', '/Large/')
                                .replace('/Medium/', '/Large/');

                            if (!results.includes(largeSrc)) {
                                results.push(largeSrc);
                            }
                        }
                    });

                    return results;
                """)

                if js_images:
                    images = js_images
                    st.info(f"📸 XD: {len(images)} imagini (Large)")

            except Exception:
                pass

            # Fallback: imagini din soup
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
                        and 'co2' not in src.lower()
                    ):
                        large_src = (
                            src.replace('/Small/', '/Large/')
                            .replace('/Thumb/', '/Large/')
                            .replace('/Medium/', '/Large/')
                        )
                        abs_url = make_absolute_url(
                            large_src, self.base_url
                        )
                        if abs_url not in images:
                            images.append(abs_url)

            # ═══════════════════════════════
            # CONSTRUIM PRODUSUL
            # ═══════════════════════════════
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
            product['product_id'] = product_id
            product['variant_id'] = variant_id

            st.success(
                f"📦 XD: {name[:40]} | SKU: {sku} | "
                f"Preț: {price} RON | "
                f"Desc: {len(description)} car | "
                f"Specs: {len(specifications)} | "
                f"Culori: {len(colors)} | "
                f"Img: {len(images)}"
            )

            return product

        except Exception as e:
            st.error(f"❌ XD scrape error: {str(e)}")
            return None
