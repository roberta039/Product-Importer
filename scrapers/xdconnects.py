# scrapers/xdconnects.py
"""
Scraper pentru xdconnects.com (Bobby, Swiss Peak, Urban, etc.)
Structură pagină produs:
- Culori: pătrate colorate în secțiunea "Colour:"
- Item no: P705.709
- Preț: 375,00 RON
- Imagini: carousel lateral
"""
import re
import time
import json as json_lib
from scrapers.base_scraper import BaseScraper
from utils.helpers import clean_price
from utils.image_handler import make_absolute_url
import streamlit as st
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import (
    NoSuchElementException, StaleElementReferenceException,
    TimeoutException
)


class XDConnectsScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.name = "xdconnects"
        self.base_url = "https://www.xdconnects.com"
        self._logged_in = False

    def _dismiss_cookie_banner(self):
        """Închide cookie banner pe XD Connects (Cookiebot)."""
        if not self.driver:
            return

        selectors = [
            "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
            "#CybotCookiebotDialogBodyButtonAccept",
            "#CybotCookiebotDialogBodyLevelButtonAccept",
        ]
        for selector in selectors:
            try:
                btn = self.driver.find_element(
                    By.CSS_SELECTOR, selector
                )
                if btn.is_displayed():
                    self.driver.execute_script(
                        "arguments[0].click();", btn
                    )
                    time.sleep(2)
                    st.info("🍪 XD: Cookie banner închis")
                    return
            except NoSuchElementException:
                continue

        # Eliminare forțată
        try:
            self.driver.execute_script("""
                var sels = [
                    '#CybotCookiebotDialog',
                    '#CybotCookiebotDialogBody',
                    '#CybotCookiebotDialogBodyUnderlay'
                ];
                sels.forEach(function(s) {
                    document.querySelectorAll(s).forEach(function(el) {
                        el.remove();
                    });
                });
                document.body.style.overflow = 'auto';
            """)
            time.sleep(1)
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
                st.info("ℹ️ XD: fără credențiale, continui fără login")
                return

            self._init_driver()
            if not self.driver:
                return

            st.info("🔐 XD: Mă conectez...")
            self.driver.get(f"{self.base_url}/en-gb/")
            time.sleep(5)

            self._dismiss_cookie_banner()
            time.sleep(1)

            # Căutăm butonul de Login
            login_link = None
            for selector in [
                "a[href*='/profile/login']",
                "a[href*='/login']",
                "a[href*='/account/login']",
            ]:
                try:
                    elements = self.driver.find_elements(
                        By.CSS_SELECTOR, selector
                    )
                    for el in elements:
                        try:
                            if el.is_displayed():
                                el_href = (
                                    el.get_attribute('href') or ''
                                ).lower()
                                if (
                                    'search' not in el_href
                                    and 'cart' not in el_href
                                ):
                                    login_link = el
                                    break
                        except StaleElementReferenceException:
                            continue
                    if login_link:
                        break
                except Exception:
                    continue

            if login_link:
                href = login_link.get_attribute('href')
                if href:
                    self.driver.get(href)
                else:
                    self.driver.execute_script(
                        "arguments[0].click();", login_link
                    )
                time.sleep(4)
            else:
                self.driver.get(
                    f"{self.base_url}/en-gb/profile/login"
                )
                time.sleep(4)

            self._dismiss_cookie_banner()
            time.sleep(1)

            # Completăm email
            email_field = None
            for selector in [
                "input[type='email'][name='email']",
                "input[name='email']",
                "input[type='email']",
            ]:
                try:
                    fields = self.driver.find_elements(
                        By.CSS_SELECTOR, selector
                    )
                    for field in fields:
                        try:
                            if (
                                field.is_displayed()
                                and field.is_enabled()
                            ):
                                email_field = field
                                break
                        except StaleElementReferenceException:
                            continue
                    if email_field:
                        break
                except Exception:
                    continue

            if not email_field:
                st.error("❌ XD: Nu găsesc câmpul de email!")
                return

            self.driver.execute_script(
                "arguments[0].focus();", email_field
            )
            time.sleep(0.3)
            email_field.clear()
            email_field.send_keys(Keys.CONTROL, 'a')
            email_field.send_keys(Keys.DELETE)
            time.sleep(0.2)
            email_field.send_keys(xd_user)
            time.sleep(0.5)

            # Completăm parola
            pass_field = None
            try:
                for field in self.driver.find_elements(
                    By.CSS_SELECTOR, "input[type='password']"
                ):
                    if field.is_displayed() and field.is_enabled():
                        pass_field = field
                        break
            except Exception:
                pass

            if not pass_field:
                st.error("❌ XD: Nu găsesc câmpul de parolă!")
                return

            self.driver.execute_script(
                "arguments[0].focus();", pass_field
            )
            time.sleep(0.3)
            pass_field.clear()
            pass_field.send_keys(Keys.CONTROL, 'a')
            pass_field.send_keys(Keys.DELETE)
            time.sleep(0.2)
            pass_field.send_keys(xd_pass)
            time.sleep(0.5)

            # Submit
            self._dismiss_cookie_banner()
            time.sleep(0.5)

            submitted = False
            for selector in [
                "form button[type='submit']",
                "button[type='submit']",
            ]:
                try:
                    for btn in self.driver.find_elements(
                        By.CSS_SELECTOR, selector
                    ):
                        if btn.is_displayed():
                            self.driver.execute_script(
                                "arguments[0].click();", btn
                            )
                            submitted = True
                            break
                    if submitted:
                        break
                except Exception:
                    continue

            if not submitted:
                pass_field.send_keys(Keys.RETURN)

            time.sleep(6)

            current_url = self.driver.current_url.lower()
            page_source = self.driver.page_source.lower()

            if (
                'login' not in current_url
                or 'logout' in page_source
                or 'account' in page_source
            ):
                self._logged_in = True
                st.success("✅ XD: Login reușit!")
            else:
                st.warning(
                    "⚠️ XD: Status login neclar, continui..."
                )
                self._logged_in = True

        except Exception as e:
            st.error(f"❌ XD login error: {str(e)[:150]}")

    def _extract_colors_with_selenium(self, url: str) -> list:
        """
        Extrage culorile direct cu Selenium din pagina live.
        XD Connects folosește pătrate colorate (swatches)
        generate cu JS.
        """
        variants = []

        if not self.driver:
            return variants

        try:
            # Așteptăm să se încarce culorile
            time.sleep(2)

            # ═══ METODA 1: Elementele de culoare vizibile ═══
            # Căutăm toate elementele care ar putea fi swatches
            color_selectors = [
                # Selectori specifici XD Connects
                "[class*='colour'] a",
                "[class*='color'] a",
                "[class*='Colour'] a",
                "[class*='Color'] a",
                "[class*='colour'] button",
                "[class*='color'] button",
                "[class*='colour'] div[style]",
                "[class*='color'] div[style]",
                "[class*='colour'] span[style]",
                "[class*='color'] span[style]",
                # Variant selectors
                "[class*='variant'] a",
                "[class*='swatch'] a",
                "[class*='swatch']",
                "a[class*='swatch']",
                # Data attributes
                "[data-color]",
                "[data-colour]",
                "[data-variant-color]",
                # Link-uri cu variantId
                "a[href*='variantId']",
                # Pătrate colorate generice
                "[class*='color-box']",
                "[class*='colour-box']",
                "[class*='color-square']",
                "[class*='colour-square']",
                "[class*='color-circle']",
                "[class*='colour-circle']",
                "[class*='color-item']",
                "[class*='colour-item']",
                "[class*='color-option']",
                "[class*='colour-option']",
            ]

            found_elements = []

            for selector in color_selectors:
                try:
                    elements = self.driver.find_elements(
                        By.CSS_SELECTOR, selector
                    )
                    visible_elements = []
                    for el in elements:
                        try:
                            if el.is_displayed():
                                visible_elements.append(el)
                        except StaleElementReferenceException:
                            continue

                    if visible_elements:
                        found_elements = visible_elements
                        st.info(
                            f"🎨 XD: {len(visible_elements)} "
                            f"culori găsite cu [{selector}]"
                        )
                        break
                except Exception:
                    continue

            # ═══ METODA 2: Căutare prin JavaScript ═══
            if not found_elements:
                try:
                    js_result = self.driver.execute_script("""
                        var results = [];

                        // Căutăm secțiunea Colour
                        var allElements = document.querySelectorAll('*');
                        var colourSection = null;

                        for (var i = 0; i < allElements.length; i++) {
                            var text = allElements[i].textContent.trim();
                            if (text === 'Colour:' || text === 'Color:' ||
                                text === 'Colour' || text === 'Color') {
                                colourSection = allElements[i].parentElement;
                                break;
                            }
                        }

                        if (colourSection) {
                            // Găsim elementele clickabile din secțiunea
                            // de culori (pătrate, linkuri, etc.)
                            var clickables = colourSection.querySelectorAll(
                                'a, button, [role="button"], ' +
                                'div[style*="background"], ' +
                                'span[style*="background"]'
                            );

                            clickables.forEach(function(el) {
                                var info = {
                                    tag: el.tagName,
                                    title: el.getAttribute('title') || '',
                                    ariaLabel: el.getAttribute('aria-label') || '',
                                    dataColor: el.getAttribute('data-color') || '',
                                    href: el.getAttribute('href') || '',
                                    style: el.getAttribute('style') || '',
                                    text: el.textContent.trim().substring(0, 30),
                                    className: el.className || '',
                                    bgColor: window.getComputedStyle(el).backgroundColor
                                };
                                results.push(info);
                            });
                        }

                        // Fallback: căutăm orice cu background-color
                        // care pare un swatch
                        if (results.length === 0) {
                            var allA = document.querySelectorAll(
                                'a[href*="variantId"]'
                            );
                            allA.forEach(function(el) {
                                var info = {
                                    tag: 'A',
                                    title: el.getAttribute('title') || '',
                                    ariaLabel: el.getAttribute('aria-label') || '',
                                    dataColor: el.getAttribute('data-color') || '',
                                    href: el.getAttribute('href') || '',
                                    style: el.getAttribute('style') || '',
                                    text: el.textContent.trim().substring(0, 30),
                                    className: el.className || '',
                                    bgColor: window.getComputedStyle(el).backgroundColor
                                };
                                results.push(info);
                            });
                        }

                        return results;
                    """)

                    if js_result:
                        st.info(
                            f"🎨 XD JS: {len(js_result)} elemente "
                            f"de culoare găsite"
                        )

                        for item in js_result:
                            color_name = (
                                item.get('title')
                                or item.get('ariaLabel')
                                or item.get('dataColor')
                                or item.get('text')
                                or ''
                            ).strip()

                            color_url = item.get('href', '')

                            # Dacă nu are nume, încercăm să
                            # extragem din background-color
                            if not color_name:
                                bg = item.get('bgColor', '')
                                if bg and bg != 'rgba(0, 0, 0, 0)':
                                    color_name = f"Color ({bg})"

                            if (
                                color_name
                                and color_name not in [
                                    v['name'] for v in variants
                                ]
                            ):
                                variants.append({
                                    'name': color_name,
                                    'url': make_absolute_url(
                                        color_url, self.base_url
                                    ) if color_url else '',
                                    'image': '',
                                    'color_code': (
                                        item.get('dataColor', '')
                                    ),
                                })

                except Exception as e:
                    st.warning(
                        f"⚠️ XD JS color extract: {str(e)[:80]}"
                    )

            # ═══ METODA 3: Procesăm elementele găsite cu Selenium ═══
            if found_elements and not variants:
                for el in found_elements:
                    try:
                        color_name = ''
                        color_url = ''
                        color_img = ''

                        # Nume culoare
                        color_name = (
                            el.get_attribute('title')
                            or el.get_attribute('aria-label')
                            or el.get_attribute('data-color')
                            or el.get_attribute('data-colour')
                            or el.get_attribute('data-name')
                            or ''
                        ).strip()

                        # URL
                        color_url = (
                            el.get_attribute('href') or ''
                        ).strip()

                        # Imagine
                        try:
                            img = el.find_element(
                                By.CSS_SELECTOR, 'img'
                            )
                            color_img = (
                                img.get_attribute('data-src')
                                or img.get_attribute('src')
                                or ''
                            )
                        except NoSuchElementException:
                            pass

                        # Dacă nu avem nume, luăm background-color
                        if not color_name:
                            try:
                                bg_color = el.value_of_css_property(
                                    'background-color'
                                )
                                if (
                                    bg_color
                                    and bg_color != 'rgba(0, 0, 0, 0)'
                                    and bg_color != 'transparent'
                                ):
                                    color_name = f"Color ({bg_color})"
                            except Exception:
                                pass

                        # Dacă nu avem nume, luăm din text
                        if not color_name:
                            try:
                                color_name = el.text.strip()[:30]
                            except Exception:
                                pass

                        if (
                            color_name
                            and color_name not in [
                                v['name'] for v in variants
                            ]
                        ):
                            variants.append({
                                'name': color_name,
                                'url': make_absolute_url(
                                    color_url, self.base_url
                                ) if color_url else '',
                                'image': color_img,
                                'color_code': '',
                            })

                    except StaleElementReferenceException:
                        continue
                    except Exception:
                        continue

            # ═══ METODA 4: Extragem din URL-urile variantelor ═══
            if not variants:
                try:
                    variant_links = self.driver.find_elements(
                        By.CSS_SELECTOR,
                        "a[href*='variantId']"
                    )
                    for link in variant_links:
                        try:
                            if not link.is_displayed():
                                continue

                            v_name = (
                                link.get_attribute('title')
                                or link.get_attribute('aria-label')
                                or ''
                            ).strip()

                            v_href = (
                                link.get_attribute('href') or ''
                            )

                            if not v_name:
                                # Extragem variantId din href
                                vid_match = re.search(
                                    r'variantId=([^&]+)', v_href
                                )
                                if vid_match:
                                    v_name = vid_match.group(1)

                            if (
                                v_name
                                and v_name not in [
                                    v['name'] for v in variants
                                ]
                            ):
                                variants.append({
                                    'name': v_name,
                                    'url': v_href,
                                    'image': '',
                                    'color_code': '',
                                })

                        except StaleElementReferenceException:
                            continue
                except Exception:
                    pass

            # ═══ METODA 5: Extragem din page source cu regex ═══
            if not variants:
                try:
                    page_source = self.driver.page_source

                    # Căutăm JSON cu variante
                    variant_patterns = [
                        r'"variants?":\s*\[(.*?)\]',
                        r'"colors?":\s*\[(.*?)\]',
                        r'"colours?":\s*\[(.*?)\]',
                    ]

                    for pattern in variant_patterns:
                        matches = re.findall(
                            pattern, page_source, re.DOTALL
                        )
                        for match in matches:
                            # Extragem name/label din JSON
                            names = re.findall(
                                r'"(?:name|label|color|colour)"'
                                r'\s*:\s*"([^"]+)"',
                                match
                            )
                            for name in names:
                                if (
                                    name
                                    and name not in [
                                        v['name'] for v in variants
                                    ]
                                    and len(name) < 30
                                ):
                                    variants.append({
                                        'name': name,
                                        'url': '',
                                        'image': '',
                                        'color_code': '',
                                    })
                        if variants:
                            break

                    # Căutăm variantId-uri unice în linkuri
                    if not variants:
                        variant_ids = re.findall(
                            r'variantId=([A-Z0-9.]+)',
                            page_source
                        )
                        unique_ids = list(dict.fromkeys(variant_ids))
                        for vid in unique_ids:
                            if vid not in [
                                v['name'] for v in variants
                            ]:
                                variants.append({
                                    'name': vid,
                                    'url': '',
                                    'image': '',
                                    'color_code': vid,
                                })

                except Exception:
                    pass

        except Exception as e:
            st.warning(
                f"⚠️ XD color extraction error: {str(e)[:80]}"
            )

        return variants

    def scrape(self, url: str) -> dict | None:
        """Scrape produs de pe xdconnects.com."""
        try:
            self._login_if_needed()

            # Navigăm la produs cu Selenium
            self._init_driver()
            if not self.driver:
                return None

            st.info(f"📦 XD: Scrapez {url[:70]}...")
            self.driver.get(url)
            time.sleep(5)

            self._dismiss_cookie_banner()
            time.sleep(1)

            # Scroll complet pentru lazy loading
            self.driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight/3);"
            )
            time.sleep(1)
            self.driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight/2);"
            )
            time.sleep(1)
            self.driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);"
            )
            time.sleep(1)
            self.driver.execute_script(
                "window.scrollTo(0, 0);"
            )
            time.sleep(1)

            # Parsăm cu BeautifulSoup
            from bs4 import BeautifulSoup
            page_source = self.driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')

            if not soup:
                return None

            # ═══ NUME ═══
            name = ""
            for sel in [
                'h1', 'h1.product-detail-name',
                'h1.product-name',
                '.product-detail h1',
            ]:
                el = soup.select_one(sel)
                if el and el.get_text(strip=True):
                    name = el.get_text(strip=True)
                    break

            if not name:
                name = "Produs XD Connects"

            # ═══ SKU / Item no. ═══
            sku = ""

            # Din pagină - "Item no. P705.709"
            item_no_pattern = re.search(
                r'Item\s*no\.?\s*:?\s*([A-Z0-9.]+)',
                page_source, re.IGNORECASE
            )
            if item_no_pattern:
                sku = item_no_pattern.group(1).upper()

            # Din URL
            if not sku:
                sku_match = re.search(
                    r'([pP]\d{3}\.\d{2,3})', url
                )
                if sku_match:
                    sku = sku_match.group(1).upper()

            # Din HTML
            if not sku:
                for sel in [
                    '.product-detail-sku', '.product-sku',
                    '[class*="sku"]', '[class*="article"]',
                    '[class*="item-no"]',
                ]:
                    el = soup.select_one(sel)
                    if el:
                        sku_text = el.get_text(strip=True)
                        if sku_text:
                            # Extragem doar codul
                            code = re.search(
                                r'([A-Z]\d{3}[\d.]+)',
                                sku_text, re.IGNORECASE
                            )
                            sku = (
                                code.group(1).upper()
                                if code
                                else sku_text
                            )
                        break

            # ═══ PREȚ ═══
            price = 0.0

            # Din pagină - "375,00 RON" sau "From 375,00 RON"
            price_pattern = re.search(
                r'(?:From\s+)?(\d+[.,]\d{2})\s*RON',
                page_source, re.IGNORECASE
            )
            if price_pattern:
                price = clean_price(price_pattern.group(1))

            if price <= 0:
                for sel in [
                    '.product-detail-price', '.product-price',
                    '[class*="price"]', '.price',
                ]:
                    el = soup.select_one(sel)
                    if el:
                        price = clean_price(
                            el.get_text(strip=True)
                        )
                        if price > 0:
                            break

            # ═══ DESCRIERE ═══
            description = ""

            # Extrage descrierea scurtă (ex: "rPET • Volume 10.5L • ...")
            short_desc_pattern = re.search(
                r'((?:rPET|PVC|recycled|anti-theft)[^<]{10,200})',
                page_source, re.IGNORECASE
            )
            if short_desc_pattern:
                description = short_desc_pattern.group(1).strip()

            for sel in [
                '.product-detail-description',
                '.product-description',
                '[class*="description"]',
                '.product-detail-body',
            ]:
                el = soup.select_one(sel)
                if el:
                    desc_text = str(el)
                    if len(desc_text) > len(description):
                        description = desc_text
                    break

            # ═══ SPECIFICAȚII ═══
            specifications = {}
            for sel in [
                '.product-detail-properties',
                '.product-properties',
                '.product-specifications',
                'table',
                '[class*="specification"]',
                '[class*="properties"]',
            ]:
                container = soup.select_one(sel)
                if container:
                    rows = container.select('tr')
                    for row in rows:
                        cells = row.select('td, th')
                        if len(cells) >= 2:
                            key = cells[0].get_text(strip=True)
                            val = cells[1].get_text(strip=True)
                            if key and val:
                                specifications[key] = val
                    if not specifications:
                        dts = container.select('dt')
                        dds = container.select('dd')
                        for dt, dd in zip(dts, dds):
                            key = dt.get_text(strip=True)
                            val = dd.get_text(strip=True)
                            if key and val:
                                specifications[key] = val
                    if specifications:
                        break

            # Extrage din "Recommended sales price" table
            price_table = re.findall(
                r'(\d+)\s+(\d+[.,]\d{2})\s*RON',
                page_source
            )
            if price_table:
                specifications['Preț recomandat'] = (
                    f"{price_table[0][1]} RON "
                    f"(cantitate: {price_table[0][0]})"
                )

            # ═══ IMAGINI ═══
            images = []

            # Metoda 1: Selenium - imagini vizibile
            try:
                img_elements = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    "img[src*='product'], img[src*='media'], "
                    "img[src*='image'], img[data-src*='product'], "
                    "img[data-src*='media']"
                )
                for img_el in img_elements:
                    try:
                        src = (
                            img_el.get_attribute('data-src')
                            or img_el.get_attribute('src')
                            or ''
                        )
                        if (
                            src
                            and 'placeholder' not in src.lower()
                            and 'icon' not in src.lower()
                            and 'logo' not in src.lower()
                            and 'flag' not in src.lower()
                            and 'co2' not in src.lower()
                        ):
                            abs_url = make_absolute_url(
                                src, self.base_url
                            )
                            if abs_url not in images:
                                images.append(abs_url)
                    except StaleElementReferenceException:
                        continue
            except Exception:
                pass

            # Metoda 2: BeautifulSoup
            if not images:
                for sel in [
                    '.product-detail-images img',
                    '.product-gallery img',
                    '.product-images img',
                    '[class*="gallery"] img',
                    '[class*="product-image"] img',
                    '.product-detail img',
                    '.product-media img',
                ]:
                    imgs = soup.select(sel)
                    if imgs:
                        for img in imgs:
                            src = (
                                img.get('data-src')
                                or img.get('src')
                                or img.get('data-lazy')
                                or ''
                            )
                            if (
                                src
                                and 'placeholder' not in src.lower()
                                and 'icon' not in src.lower()
                                and 'logo' not in src.lower()
                                and 'co2' not in src.lower()
                            ):
                                abs_url = make_absolute_url(
                                    src, self.base_url
                                )
                                if abs_url not in images:
                                    images.append(abs_url)
                        if images:
                            break

            # Fallback imagini
            if not images:
                for img in soup.select('img'):
                    src = (
                        img.get('src', '')
                        or img.get('data-src', '')
                    )
                    if src and any(
                        kw in src.lower()
                        for kw in ['product', 'media', 'upload']
                    ):
                        abs_url = make_absolute_url(
                            src, self.base_url
                        )
                        if (
                            abs_url not in images
                            and 'icon' not in abs_url.lower()
                            and 'logo' not in abs_url.lower()
                        ):
                            images.append(abs_url)

            # ═══ VARIANTE DE CULOARE (cu Selenium) ═══
            color_variants = self._extract_colors_with_selenium(url)

            colors = []
            variant_images = {}

            if color_variants:
                st.info(
                    f"🎨 XD: {len(color_variants)} culori: "
                    + ", ".join(
                        [v['name'] for v in color_variants[:5]]
                    )
                    + (
                        "..."
                        if len(color_variants) > 5
                        else ""
                    )
                )
                for v in color_variants:
                    if v['name']:
                        colors.append(v['name'])
                    if v.get('image'):
                        abs_img = make_absolute_url(
                            v['image'], self.base_url
                        )
                        variant_images[v['name']] = abs_img
                        if abs_img not in images:
                            images.append(abs_img)

            # ═══ CONSTRUIM PRODUSUL ═══
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
            product['variant_images'] = variant_images

            st.info(
                f"📦 XD: {name[:40]} | SKU: {sku} | "
                f"Preț: {price} RON | "
                f"Culori: {len(colors)} | "
                f"Imagini: {len(images)}"
            )

            return product

        except Exception as e:
            st.error(
                f"❌ Eroare scraping XD Connects: {str(e)}"
            )
            return None
