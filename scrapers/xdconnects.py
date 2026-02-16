# scrapers/xdconnects.py
"""
Scraper pentru xdconnects.com (Bobby, Swiss Peak, Urban, etc.)
Extrage variante de culoare ca produse separate sau ca opțiuni.
"""
import re
import time
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
        """Închide cookie banner pe XD Connects."""
        if not self.driver:
            return

        cookie_selectors = [
            "#onetrust-accept-btn-handler",
            "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
            "#CybotCookiebotDialogBodyButtonAccept",
            "button[data-action='accept']",
            ".cc-accept",
            ".cc-allow",
            ".cc-dismiss",
            "button.accept-cookies",
            "#accept-cookies",
            "button[class*='cookie']",
            "button[class*='accept']",
            "button[class*='consent']",
            ".cookie-banner button",
            ".cookie-notice button",
        ]

        for selector in cookie_selectors:
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, selector)
                if btn.is_displayed():
                    self.driver.execute_script(
                        "arguments[0].click();", btn
                    )
                    time.sleep(2)
                    st.info(f"🍪 XD: Cookie banner închis [{selector}]")
                    return
            except NoSuchElementException:
                continue

        # XPath fallback
        accept_texts = [
            "Accept", "Accept All", "Allow All", "OK",
            "Agree", "I agree", "Got it",
        ]
        for text in accept_texts:
            try:
                btn = self.driver.find_element(
                    By.XPATH,
                    f"//button[contains(text(), '{text}')]"
                )
                if btn.is_displayed():
                    self.driver.execute_script(
                        "arguments[0].click();", btn
                    )
                    time.sleep(2)
                    st.info(f"🍪 XD: Cookie banner închis (text: {text})")
                    return
            except NoSuchElementException:
                continue

        # Eliminare forțată JS
        try:
            self.driver.execute_script("""
                var selectors = [
                    '#onetrust-banner-sdk', '#onetrust-consent-sdk',
                    '.onetrust-pc-dark-filter',
                    '#CybotCookiebotDialog', '#CybotCookiebotDialogBody',
                    '.cookie-banner', '.cookie-notice', '.cookie-consent',
                    '[class*="cookie"]', '[id*="cookie"]',
                    '[class*="consent"]', '[id*="consent"]'
                ];
                selectors.forEach(function(sel) {
                    document.querySelectorAll(sel).forEach(function(el) {
                        el.remove();
                    });
                });
                document.body.style.overflow = 'auto';
                document.documentElement.style.overflow = 'auto';
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

            # Navigăm la login
            st.info("🔐 XD: Mă conectez...")
            self.driver.get(f"{self.base_url}/en-gb/login")
            time.sleep(5)

            # Cookie banner
            self._dismiss_cookie_banner()
            time.sleep(1)

            # Debug: listăm input-urile vizibile
            try:
                all_inputs = self.driver.find_elements(
                    By.CSS_SELECTOR, "input:not([type='hidden'])"
                )
                visible_inputs = []
                for inp in all_inputs:
                    try:
                        if inp.is_displayed():
                            inp_type = inp.get_attribute('type') or 'text'
                            inp_name = inp.get_attribute('name') or ''
                            inp_id = inp.get_attribute('id') or ''
                            inp_ph = inp.get_attribute('placeholder') or ''
                            visible_inputs.append(
                                f"type={inp_type}, name={inp_name}, "
                                f"id={inp_id}, ph={inp_ph}"
                            )
                    except StaleElementReferenceException:
                        continue
                st.info(
                    f"📋 XD: {len(visible_inputs)} inputs: "
                    f"{visible_inputs[:5]}"
                )
            except Exception:
                pass

            # ═══ Completăm email/username ═══
            email_field = None
            email_selectors = [
                "input[name='username']",
                "input[name='email']",
                "input[name='_username']",
                "input[type='email']",
                "input[id='loginMail']",
                "input[id='email']",
                "input[id='username']",
                "input[autocomplete='email']",
                "input[autocomplete='username']",
                "input[placeholder*='mail']",
                "input[placeholder*='Mail']",
                "input[placeholder*='email']",
                "input[placeholder*='Email']",
                "input[placeholder*='user']",
                "input[placeholder*='User']",
                ".login-form input[type='email']",
                ".login-form input[type='text']",
                "form input[type='email']",
                "form input[type='text']",
            ]

            for selector in email_selectors:
                try:
                    fields = self.driver.find_elements(
                        By.CSS_SELECTOR, selector
                    )
                    for field in fields:
                        try:
                            if field.is_displayed() and field.is_enabled():
                                email_field = field
                                st.info(
                                    f"✅ XD: Email field: {selector}"
                                )
                                break
                        except StaleElementReferenceException:
                            continue
                    if email_field:
                        break
                except Exception:
                    continue

            # Fallback: primul input din form
            if not email_field:
                try:
                    forms = self.driver.find_elements(
                        By.CSS_SELECTOR, "form"
                    )
                    for form in forms:
                        inputs = form.find_elements(
                            By.CSS_SELECTOR,
                            "input[type='text'], input[type='email']"
                        )
                        for inp in inputs:
                            if inp.is_displayed() and inp.is_enabled():
                                email_field = inp
                                st.info(
                                    "✅ XD: Email field (form fallback)"
                                )
                                break
                        if email_field:
                            break
                except Exception:
                    pass

            if not email_field:
                st.error("❌ XD: Nu găsesc câmpul de email!")
                # Screenshot debug
                try:
                    screenshot = self.driver.get_screenshot_as_png()
                    st.image(screenshot, caption="XD Login Page", width=700)
                except Exception:
                    pass
                return

            # Completăm email
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

            # ═══ Completăm parola ═══
            pass_field = None
            try:
                pass_fields = self.driver.find_elements(
                    By.CSS_SELECTOR, "input[type='password']"
                )
                for field in pass_fields:
                    try:
                        if field.is_displayed() and field.is_enabled():
                            pass_field = field
                            break
                    except StaleElementReferenceException:
                        continue
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

            # ═══ Eliminăm overlay-uri ═══
            self._dismiss_cookie_banner()
            time.sleep(0.5)

            # ═══ Submit ═══
            submitted = False

            submit_selectors = [
                "form button[type='submit']",
                "button[type='submit']",
                "input[type='submit']",
                ".login-form button[type='submit']",
                "button.btn-primary",
                "button.login-btn",
                "button[class*='login']",
                "button[class*='submit']",
            ]

            for selector in submit_selectors:
                try:
                    buttons = self.driver.find_elements(
                        By.CSS_SELECTOR, selector
                    )
                    for btn in buttons:
                        try:
                            if btn.is_displayed():
                                self.driver.execute_script(
                                    "arguments[0].click();", btn
                                )
                                submitted = True
                                st.info(f"✅ XD: Submit [{selector}]")
                                break
                        except StaleElementReferenceException:
                            continue
                    if submitted:
                        break
                except Exception:
                    continue

            if not submitted:
                try:
                    pass_field.send_keys(Keys.RETURN)
                    submitted = True
                    st.info("✅ XD: Submit cu ENTER")
                except Exception:
                    pass

            if not submitted:
                try:
                    self.driver.execute_script(
                        "document.querySelector('form').submit();"
                    )
                    submitted = True
                    st.info("✅ XD: Submit cu form.submit()")
                except Exception:
                    pass

            time.sleep(6)

            # Verificăm login
            current_url = self.driver.current_url.lower()
            page_source = self.driver.page_source.lower()

            if (
                'login' not in current_url
                or 'logout' in page_source
                or 'account' in page_source
                or 'dashboard' in current_url
                or 'my-account' in page_source
            ):
                self._logged_in = True
                st.success("✅ XD: Login reușit!")
            else:
                if any(
                    err in page_source
                    for err in ['invalid', 'incorrect', 'error', 'wrong']
                ):
                    st.error("❌ XD: Credențiale incorecte!")
                else:
                    st.warning(
                        "⚠️ XD: Status login neclar, continui..."
                    )
                    self._logged_in = True

        except Exception as e:
            st.error(f"❌ XD login error: {str(e)[:150]}")

    def _extract_color_variants(self, soup) -> list:
        """
        Extrage toate variantele de culoare disponibile.
        Returnează listă de dict-uri {name, color_code, url, image}.
        """
        variants = []

        # Metoda 1: Linkuri/butoane de culoare
        color_selectors = [
            'a[class*="color"]',
            'button[class*="color"]',
            '[class*="variant"] a',
            '[class*="color-option"]',
            '[class*="color-selector"] a',
            '[class*="color-picker"] a',
            '[class*="swatch"] a',
            '[data-color]',
            '.product-detail-configurator a',
            '.product-configurator a',
            'a[href*="variantId"]',
            'a[href*="color"]',
        ]

        for sel in color_selectors:
            elements = soup.select(sel)
            if elements:
                for el in elements:
                    variant = {}

                    # Nume culoare
                    variant['name'] = (
                        el.get('title')
                        or el.get('aria-label')
                        or el.get('data-color')
                        or el.get('data-name')
                        or el.get_text(strip=True)
                        or ''
                    )

                    # URL variantă
                    href = el.get('href', '')
                    if href:
                        variant['url'] = make_absolute_url(
                            href, self.base_url
                        )
                    else:
                        variant['url'] = ''

                    # Imagine variantă
                    img = el.select_one('img')
                    if img:
                        variant['image'] = (
                            img.get('src')
                            or img.get('data-src')
                            or ''
                        )
                    else:
                        # Background color/image
                        style = el.get('style', '')
                        bg_match = re.search(
                            r'background(?:-image)?:\s*url\(["\']?'
                            r'([^"\')\s]+)',
                            style
                        )
                        if bg_match:
                            variant['image'] = bg_match.group(1)
                        else:
                            variant['image'] = ''

                    # Cod culoare
                    variant['color_code'] = (
                        el.get('data-color-code')
                        or el.get('data-value')
                        or ''
                    )

                    # Verificăm dacă e o variantă validă
                    if variant['name'] or variant['url']:
                        if variant['name'] not in [
                            v['name'] for v in variants
                        ]:
                            variants.append(variant)

                if variants:
                    break

        # Metoda 2: Select dropdown
        if not variants:
            for sel in [
                'select[name*="color"]',
                'select[id*="color"]',
                'select[name*="variant"]',
                'select[class*="color"]',
            ]:
                select = soup.select_one(sel)
                if select:
                    options = select.select('option')
                    for opt in options:
                        val = opt.get('value', '')
                        text = opt.get_text(strip=True)
                        if val and text and val != '' and text != '--':
                            variants.append({
                                'name': text,
                                'url': '',
                                'image': '',
                                'color_code': val,
                            })
                    if variants:
                        break

        # Metoda 3: Data attributes pe container
        if not variants:
            containers = soup.select(
                '[data-variants], [data-colors]'
            )
            for container in containers:
                data = (
                    container.get('data-variants')
                    or container.get('data-colors')
                    or ''
                )
                if data:
                    try:
                        import json
                        variant_data = json.loads(data)
                        if isinstance(variant_data, list):
                            for v in variant_data:
                                if isinstance(v, dict):
                                    variants.append({
                                        'name': (
                                            v.get('name')
                                            or v.get('label')
                                            or v.get('color')
                                            or ''
                                        ),
                                        'url': v.get('url', ''),
                                        'image': v.get('image', ''),
                                        'color_code': (
                                            v.get('code')
                                            or v.get('id')
                                            or ''
                                        ),
                                    })
                    except Exception:
                        pass

        return variants

    def scrape(self, url: str) -> dict | None:
        """Scrape produs de pe xdconnects.com cu variante de culoare."""
        try:
            self._login_if_needed()

            soup = self.get_page(
                url,
                wait_selector=(
                    'h1, .product-detail, .product-info, '
                    '[class*="product"]'
                ),
                prefer_selenium=True
            )
            if not soup:
                return None

            # ═══ NUME PRODUS ═══
            name = ""
            for sel in [
                'h1.product-detail-name',
                'h1.product-name',
                'h1[class*="product"]',
                '.product-detail h1',
                '.product-info h1',
                'h1',
            ]:
                el = soup.select_one(sel)
                if el and el.get_text(strip=True):
                    name = el.get_text(strip=True)
                    break

            if not name:
                name = "Produs XD Connects"

            # ═══ SKU ═══
            sku = ""
            # Din URL (ex: p705.29, P762.51)
            sku_match = re.search(
                r'([pP]\d{3}\.\d{2,3})', url
            )
            if sku_match:
                sku = sku_match.group(1).upper()

            for sel in [
                '.product-detail-sku',
                '.product-sku',
                '[class*="sku"]',
                '[class*="article-number"]',
                '[class*="product-id"]',
                '[class*="product-code"]',
            ]:
                el = soup.select_one(sel)
                if el:
                    sku_text = el.get_text(strip=True)
                    if sku_text:
                        sku = sku_text
                    break

            # ═══ PREȚ ═══
            price = 0.0
            for sel in [
                '.product-detail-price',
                '.product-price',
                '[class*="price"] .price',
                '[class*="price"]',
                '.price',
            ]:
                el = soup.select_one(sel)
                if el:
                    price_text = el.get_text(strip=True)
                    price = clean_price(price_text)
                    if price > 0:
                        break

            # ═══ DESCRIERE ═══
            description = ""
            for sel in [
                '.product-detail-description',
                '.product-description',
                '[class*="description"]',
                '.product-detail-body',
                '#product-description',
                '.product-info-description',
            ]:
                el = soup.select_one(sel)
                if el:
                    description = str(el)
                    break

            # ═══ SPECIFICAȚII ═══
            specifications = {}
            for sel in [
                '.product-detail-properties',
                '.product-properties',
                '.product-specifications',
                'table.specifications',
                '[class*="specification"]',
                '[class*="properties"]',
                '.product-detail-features',
                'table',
            ]:
                container = soup.select_one(sel)
                if container:
                    # Table rows
                    rows = container.select('tr')
                    for row in rows:
                        cells = row.select('td, th')
                        if len(cells) >= 2:
                            key = cells[0].get_text(strip=True)
                            val = cells[1].get_text(strip=True)
                            if key and val:
                                specifications[key] = val

                    # Property rows (div-based)
                    if not specifications:
                        prop_rows = container.select(
                            '.property-row, .spec-row, '
                            '[class*="property"], dl dt'
                        )
                        for j in range(0, len(prop_rows) - 1, 2):
                            key = prop_rows[j].get_text(strip=True)
                            val = prop_rows[j + 1].get_text(strip=True)
                            if key and val:
                                specifications[key] = val

                    # Definition list
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

            # ═══ IMAGINI ═══
            images = []
            for sel in [
                '.product-detail-images img',
                '.product-gallery img',
                '.product-images img',
                '[class*="gallery"] img',
                '[class*="product-image"] img',
                '.product-detail img',
                '.product-media img',
                '[class*="carousel"] img',
                '[class*="slider"] img',
            ]:
                imgs = soup.select(sel)
                if imgs:
                    for img in imgs:
                        src = (
                            img.get('data-src')
                            or img.get('src')
                            or img.get('data-lazy')
                            or img.get('data-zoom-image')
                            or img.get('data-large')
                            or ''
                        )
                        if (
                            src
                            and 'placeholder' not in src.lower()
                            and 'icon' not in src.lower()
                            and 'logo' not in src.lower()
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
                        for kw in ['product', 'media', 'upload', 'image']
                    ):
                        abs_url = make_absolute_url(src, self.base_url)
                        if (
                            abs_url not in images
                            and 'icon' not in abs_url.lower()
                            and 'logo' not in abs_url.lower()
                            and 'flag' not in abs_url.lower()
                        ):
                            images.append(abs_url)

            # ═══ VARIANTE DE CULOARE ═══
            color_variants = self._extract_color_variants(soup)

            colors = []
            variant_images = {}

            if color_variants:
                st.info(
                    f"🎨 XD: {len(color_variants)} variante de "
                    f"culoare găsite pentru {name[:40]}"
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

            # Fallback culori din text/atribute
            if not colors:
                for sel in [
                    '.color-selector a',
                    '[class*="color"] [class*="option"]',
                    '.color-picker a',
                    '[data-color]',
                ]:
                    color_els = soup.select(sel)
                    for el in color_els:
                        c = (
                            el.get('title')
                            or el.get('aria-label')
                            or el.get('data-color')
                            or el.get_text(strip=True)
                        )
                        if c and c not in colors and len(c) < 30:
                            colors.append(c)
                    if colors:
                        break

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
            )

            # Adăugăm informații extra despre variante
            product['color_variants'] = color_variants
            product['variant_images'] = variant_images

            if colors:
                st.info(
                    f"🎨 XD: Culori: {', '.join(colors[:5])}"
                    f"{'...' if len(colors) > 5 else ''}"
                )

            return product

        except Exception as e:
            st.error(f"❌ Eroare scraping XD Connects: {str(e)}")
            return None
