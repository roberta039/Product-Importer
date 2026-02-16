# scrapers/xdconnects.py
"""
Scraper pentru xdconnects.com (Bobby, Swiss Peak, Urban, etc.)
Login: buton login → modal/pagină separată
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
            "button[data-action='accept']",
            "#onetrust-accept-btn-handler",
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
                    st.info(f"🍪 XD: Cookie banner închis")
                    return
            except NoSuchElementException:
                continue

        # Eliminare forțată
        try:
            self.driver.execute_script("""
                var sels = [
                    '#CybotCookiebotDialog',
                    '#CybotCookiebotDialogBody',
                    '#CybotCookiebotDialogBodyUnderlay',
                    '[class*="cookie"]', '[id*="cookie"]'
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

    def _save_debug_screenshot(self, name: str):
        """Screenshot debug."""
        if not self.driver:
            return
        try:
            screenshot = self.driver.get_screenshot_as_png()
            st.image(
                screenshot,
                caption=f"🖥️ XD Debug: {name}",
                width=700
            )
        except Exception:
            pass

    def _login_if_needed(self):
        """Login pe XD Connects - detectează metoda de login."""
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

            # ═══ PASUL 1: Navigăm la site ═══
            st.info("🔐 XD: Mă conectez...")
            self.driver.get(f"{self.base_url}/en-gb/")
            time.sleep(5)

            # Cookie banner
            self._dismiss_cookie_banner()
            time.sleep(1)

            # ═══ PASUL 2: Căutăm butonul/linkul de Login ═══
            login_link = None
            login_selectors = [
                # Linkuri directe de login
                "a[href*='/login']",
                "a[href*='/account/login']",
                "a[href*='/auth/login']",
                "a[href*='login']",
                "a[href*='/signin']",
                "a[href*='/sign-in']",
                # Butoane de login/account
                "button[class*='login']",
                "button[class*='account']",
                "a[class*='login']",
                "a[class*='account']",
                # Icoane user/account
                "a[class*='user']",
                "a[class*='profile']",
                "[class*='account'] a",
                "[class*='login'] a",
                # Iconuri în header
                ".header a[href*='account']",
                ".header a[href*='login']",
                "header a[href*='account']",
                "header a[href*='login']",
                "nav a[href*='account']",
                "nav a[href*='login']",
                # SVG user icon
                "a svg[class*='user']",
                "a svg[class*='account']",
            ]

            for selector in login_selectors:
                try:
                    elements = self.driver.find_elements(
                        By.CSS_SELECTOR, selector
                    )
                    for el in elements:
                        try:
                            if el.is_displayed():
                                el_text = el.text.strip().lower()
                                el_href = (
                                    el.get_attribute('href') or ''
                                ).lower()
                                # Verificăm că nu e search sau altceva
                                if (
                                    'search' not in el_href
                                    and 'cart' not in el_href
                                ):
                                    login_link = el
                                    st.info(
                                        f"✅ XD: Buton login găsit: "
                                        f"[{selector}] "
                                        f"text='{el_text}' "
                                        f"href='{el_href[:50]}'"
                                    )
                                    break
                        except StaleElementReferenceException:
                            continue
                    if login_link:
                        break
                except Exception:
                    continue

            # Fallback: căutăm prin XPath
            if not login_link:
                xpath_selectors = [
                    "//a[contains(@href, 'login')]",
                    "//a[contains(@href, 'account')]",
                    "//a[contains(text(), 'Login')]",
                    "//a[contains(text(), 'Sign in')]",
                    "//a[contains(text(), 'Log in')]",
                    "//button[contains(text(), 'Login')]",
                    "//button[contains(text(), 'Sign in')]",
                ]
                for xpath in xpath_selectors:
                    try:
                        el = self.driver.find_element(By.XPATH, xpath)
                        if el.is_displayed():
                            login_link = el
                            st.info(
                                f"✅ XD: Login găsit prin XPath: "
                                f"{xpath[:50]}"
                            )
                            break
                    except NoSuchElementException:
                        continue

            if not login_link:
                st.warning(
                    "⚠️ XD: Nu găsesc butonul de login. "
                    "Încerc URL direct..."
                )
                # Încercăm mai multe URL-uri de login
                login_urls = [
                    f"{self.base_url}/en-gb/login",
                    f"{self.base_url}/en-gb/account/login",
                    f"{self.base_url}/en-gb/auth/login",
                    f"{self.base_url}/login",
                    f"{self.base_url}/account/login",
                ]
                for login_url in login_urls:
                    self.driver.get(login_url)
                    time.sleep(3)
                    # Verificăm dacă avem câmpuri de login
                    try:
                        pwd = self.driver.find_element(
                            By.CSS_SELECTOR,
                            "input[type='password']"
                        )
                        if pwd.is_displayed():
                            st.info(
                                f"✅ XD: Pagină login găsită: "
                                f"{login_url}"
                            )
                            break
                    except NoSuchElementException:
                        continue
            else:
                # Click pe butonul de login
                try:
                    self.driver.execute_script(
                        "arguments[0].click();", login_link
                    )
                    time.sleep(4)
                except Exception:
                    # Dacă e link, navigăm direct
                    href = login_link.get_attribute('href')
                    if href:
                        self.driver.get(href)
                        time.sleep(4)

            # ═══ PASUL 3: Acum ar trebui să vedem formularul ═══
            self._dismiss_cookie_banner()
            time.sleep(1)

            # Debug: vedem ce avem pe pagină
            current_url = self.driver.current_url
            st.info(f"📄 XD: URL curent: {current_url[:80]}")

            # Listăm input-urile
            try:
                all_inputs = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    "input:not([type='hidden'])"
                )
                visible_inputs = []
                for inp in all_inputs:
                    try:
                        if inp.is_displayed():
                            inp_info = (
                                f"type={inp.get_attribute('type')}, "
                                f"name={inp.get_attribute('name')}, "
                                f"id={inp.get_attribute('id')}, "
                                f"ph={inp.get_attribute('placeholder')}"
                            )
                            visible_inputs.append(inp_info)
                    except Exception:
                        continue
                st.info(
                    f"📋 XD Login: {len(visible_inputs)} inputs: "
                    f"{visible_inputs[:6]}"
                )
            except Exception:
                pass

            # Screenshot
            self._save_debug_screenshot("pagina_login")

            # ═══ PASUL 4: Completăm email ═══
            email_field = None
            email_selectors = [
                "input[name='username']",
                "input[name='email']",
                "input[name='_username']",
                "input[type='email']",
                "input[id*='email']",
                "input[id*='loginMail']",
                "input[id*='username']",
                "input[autocomplete='email']",
                "input[autocomplete='username']",
                "input[placeholder*='mail']",
                "input[placeholder*='Mail']",
                "input[placeholder*='email']",
                "input[placeholder*='Email']",
                "input[placeholder*='user']",
            ]

            for selector in email_selectors:
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

            # Fallback: primul text input din form
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
                            try:
                                inp_name = (
                                    inp.get_attribute('name') or ''
                                )
                                if (
                                    inp.is_displayed()
                                    and inp.is_enabled()
                                    and 'search' not in inp_name.lower()
                                    and 'q' != inp_name.lower()
                                ):
                                    email_field = inp
                                    st.info(
                                        "✅ XD: Email (form fallback)"
                                    )
                                    break
                            except Exception:
                                continue
                        if email_field:
                            break
                except Exception:
                    pass

            if not email_field:
                st.error(
                    "❌ XD: Nu găsesc câmpul de email! "
                    "Login imposibil."
                )
                self._save_debug_screenshot("ERROR_no_email")
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

            # ═══ PASUL 5: Completăm parola ═══
            pass_field = None
            try:
                pass_fields = self.driver.find_elements(
                    By.CSS_SELECTOR, "input[type='password']"
                )
                for field in pass_fields:
                    try:
                        if (
                            field.is_displayed()
                            and field.is_enabled()
                        ):
                            pass_field = field
                            break
                    except StaleElementReferenceException:
                        continue
            except Exception:
                pass

            if not pass_field:
                st.error("❌ XD: Nu găsesc câmpul de parolă!")
                self._save_debug_screenshot("ERROR_no_password")
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

            # ═══ PASUL 6: Submit ═══
            self._dismiss_cookie_banner()
            time.sleep(0.5)

            submitted = False
            submit_selectors = [
                "form button[type='submit']",
                "button[type='submit']",
                "input[type='submit']",
                "button.btn-primary",
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
                                st.info(
                                    f"✅ XD: Submit [{selector}]"
                                )
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
                or 'my-account' in page_source
                or 'log out' in page_source
            ):
                self._logged_in = True
                st.success("✅ XD: Login reușit!")
            else:
                if any(
                    err in page_source
                    for err in [
                        'invalid', 'incorrect', 'error',
                        'wrong', 'failed'
                    ]
                ):
                    st.error("❌ XD: Credențiale incorecte!")
                else:
                    st.warning(
                        "⚠️ XD: Status login neclar, "
                        "continui oricum..."
                    )
                    self._logged_in = True

        except Exception as e:
            st.error(f"❌ XD login error: {str(e)[:150]}")

    def _extract_color_variants(self, soup) -> list:
        """Extrage variantele de culoare."""
        variants = []

        # Metoda 1: Link-uri cu variantId
        variant_links = soup.select(
            'a[href*="variantId"]'
        )
        if variant_links:
            for link in variant_links:
                v_name = (
                    link.get('title')
                    or link.get('aria-label')
                    or link.get('data-color')
                    or link.get_text(strip=True)
                    or ''
                )
                v_href = link.get('href', '')
                v_img = ''

                img = link.select_one('img')
                if img:
                    v_img = (
                        img.get('data-src')
                        or img.get('src')
                        or ''
                    )
                else:
                    style = link.get('style', '')
                    bg = re.search(
                        r'background(?:-image)?:\s*url\(["\']?'
                        r'([^"\')\s]+)',
                        style
                    )
                    if bg:
                        v_img = bg.group(1)

                if v_name and v_name not in [
                    v['name'] for v in variants
                ]:
                    variants.append({
                        'name': v_name,
                        'url': make_absolute_url(
                            v_href, self.base_url
                        ) if v_href else '',
                        'image': v_img,
                        'color_code': '',
                    })

        # Metoda 2: Selectori generici de culoare
        if not variants:
            color_selectors = [
                '[class*="color-option"]',
                '[class*="color-selector"] a',
                '[class*="color-picker"] a',
                '[class*="swatch"]',
                '[data-color]',
                '.product-detail-configurator a',
                '.product-configurator a',
                '[class*="variant"] a',
            ]
            for sel in color_selectors:
                elements = soup.select(sel)
                if elements:
                    for el in elements:
                        v_name = (
                            el.get('title')
                            or el.get('aria-label')
                            or el.get('data-color')
                            or el.get('data-name')
                            or el.get_text(strip=True)
                            or ''
                        )
                        v_href = el.get('href', '')
                        v_img = ''

                        img = el.select_one('img')
                        if img:
                            v_img = (
                                img.get('data-src')
                                or img.get('src')
                                or ''
                            )

                        if v_name and v_name not in [
                            v['name'] for v in variants
                        ]:
                            variants.append({
                                'name': v_name,
                                'url': make_absolute_url(
                                    v_href, self.base_url
                                ) if v_href else '',
                                'image': v_img,
                                'color_code': (
                                    el.get('data-color-code')
                                    or el.get('data-value')
                                    or ''
                                ),
                            })
                    if variants:
                        break

        # Metoda 3: Select dropdown
        if not variants:
            for sel in [
                'select[name*="color"]',
                'select[id*="color"]',
                'select[name*="variant"]',
            ]:
                select = soup.select_one(sel)
                if select:
                    for opt in select.select('option'):
                        val = opt.get('value', '')
                        text = opt.get_text(strip=True)
                        if val and text and text != '--':
                            variants.append({
                                'name': text,
                                'url': '',
                                'image': '',
                                'color_code': val,
                            })
                    if variants:
                        break

        # Metoda 4: JSON în pagină
        if not variants:
            scripts = soup.select('script')
            for script in scripts:
                script_text = script.string or ''
                if 'variant' in script_text.lower():
                    # Căutăm array-uri JSON cu variante
                    json_matches = re.findall(
                        r'\{[^{}]*"color"[^{}]*\}',
                        script_text
                    )
                    for match in json_matches[:10]:
                        try:
                            data = json_lib.loads(match)
                            color = (
                                data.get('color')
                                or data.get('name')
                                or data.get('label')
                                or ''
                            )
                            if color and color not in [
                                v['name'] for v in variants
                            ]:
                                variants.append({
                                    'name': color,
                                    'url': data.get('url', ''),
                                    'image': data.get('image', ''),
                                    'color_code': (
                                        data.get('code', '')
                                    ),
                                })
                        except Exception:
                            continue

        return variants

    def scrape(self, url: str) -> dict | None:
        """Scrape produs de pe xdconnects.com."""
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

            # ═══ NUME ═══
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
            sku_match = re.search(r'([pP]\d{3}\.\d{2,3})', url)
            if sku_match:
                sku = sku_match.group(1).upper()

            for sel in [
                '.product-detail-sku', '.product-sku',
                '[class*="sku"]', '[class*="article-number"]',
                '[class*="product-id"]',
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
                '.product-detail-price', '.product-price',
                '[class*="price"] .price', '[class*="price"]',
                '.price',
            ]:
                el = soup.select_one(sel)
                if el:
                    price = clean_price(el.get_text(strip=True))
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
                'table',
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
                        for kw in [
                            'product', 'media', 'upload', 'image'
                        ]
                    ):
                        abs_url = make_absolute_url(
                            src, self.base_url
                        )
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
                    f"🎨 XD: {len(color_variants)} variante "
                    f"culoare: {name[:40]}"
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

            # Fallback culori
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

            product['color_variants'] = color_variants
            product['variant_images'] = variant_images

            return product

        except Exception as e:
            st.error(
                f"❌ Eroare scraping XD Connects: {str(e)}"
            )
            return None
