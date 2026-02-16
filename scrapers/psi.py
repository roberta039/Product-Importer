# scrapers/psi.py
"""
Scraper pentru psiproductfinder.de.
Gestionează cookie banner, login și extragere date produs.
"""
import re
import time
from scrapers.base_scraper import BaseScraper
from utils.helpers import clean_price
from utils.image_handler import make_absolute_url
import streamlit as st
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, ElementClickInterceptedException
)


class PSIScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.name = "psi"
        self.base_url = "https://psiproductfinder.de"
        self._logged_in = False

    def _dismiss_cookie_banner(self):
        """Închide cookie banner / consent popup."""
        if not self.driver:
            return

        cookie_selectors = [
            # Butoane comune de accept cookies
            "button[id*='accept']",
            "button[class*='accept']",
            "button[id*='cookie']",
            "button[class*='cookie']",
            "button[id*='consent']",
            "button[class*='consent']",
            "a[id*='accept']",
            "a[class*='accept']",
            # Butoane specifice
            ".cookie-banner button",
            ".cookie-notice button",
            ".cookie-consent button",
            "#cookie-banner button",
            "#cookieBanner button",
            ".gdpr-banner button",
            ".privacy-banner button",
            # Butoane cu text
            "button.agree",
            "button.allow",
            ".btn-accept",
            ".btn-agree",
            # Bulma framework (PSI folosește Bulma)
            ".modal-close",
            ".delete",
            "button.is-primary",
            # Generic overlay close
            ".overlay-close",
            ".popup-close",
            ".close-button",
        ]

        for selector in cookie_selectors:
            try:
                buttons = self.driver.find_elements(
                    By.CSS_SELECTOR, selector
                )
                for btn in buttons:
                    try:
                        btn_text = btn.text.lower().strip()
                        # Verificăm dacă e buton de accept cookies
                        if any(
                            keyword in btn_text
                            for keyword in [
                                'accept', 'agree', 'allow', 'ok',
                                'verstanden', 'akzeptieren', 'zustimmen',
                                'einverstanden', 'alle akzeptieren',
                                'accept all', 'allow all',
                            ]
                        ) or not btn_text:
                            # Încercăm click normal
                            try:
                                btn.click()
                                time.sleep(1)
                                st.info("🍪 Cookie banner închis")
                                return
                            except ElementClickInterceptedException:
                                # Folosim JavaScript click
                                self.driver.execute_script(
                                    "arguments[0].click();", btn
                                )
                                time.sleep(1)
                                st.info(
                                    "🍪 Cookie banner închis (JS click)"
                                )
                                return
                    except Exception:
                        continue
            except Exception:
                continue

        # Ultima încercare: căutăm prin XPath butoane cu text
        accept_texts = [
            "Accept", "Akzeptieren", "Alle akzeptieren",
            "Accept All", "Allow All", "OK", "Verstanden",
            "Einverstanden", "Zustimmen", "Agree",
        ]
        for text in accept_texts:
            try:
                btn = self.driver.find_element(
                    By.XPATH,
                    f"//button[contains(text(), '{text}')]"
                )
                try:
                    btn.click()
                except ElementClickInterceptedException:
                    self.driver.execute_script(
                        "arguments[0].click();", btn
                    )
                time.sleep(1)
                st.info(f"🍪 Cookie banner închis (text: {text})")
                return
            except NoSuchElementException:
                continue

        # Încercare extremă: eliminăm toate overlay-urile cu JS
        try:
            self.driver.execute_script("""
                // Eliminăm cookie banners și overlay-uri
                var selectors = [
                    '.cookie-banner', '.cookie-notice', '.cookie-consent',
                    '#cookie-banner', '#cookieBanner', '.gdpr-banner',
                    '.privacy-banner', '.consent-banner', '.modal.is-active',
                    '[class*="cookie"]', '[class*="consent"]',
                    '[id*="cookie"]', '[id*="consent"]',
                    '.overlay', '.modal-background'
                ];
                selectors.forEach(function(sel) {
                    var elements = document.querySelectorAll(sel);
                    elements.forEach(function(el) {
                        el.style.display = 'none';
                        el.remove();
                    });
                });
                // Resetăm overflow pe body
                document.body.style.overflow = 'auto';
                document.documentElement.style.overflow = 'auto';
            """)
            time.sleep(0.5)
        except Exception:
            pass

    def _js_click(self, element):
        """Click pe element folosind JavaScript (bypass intercept)."""
        try:
            self.driver.execute_script("arguments[0].click();", element)
            return True
        except Exception:
            return False

    def _scroll_to_element(self, element):
        """Scroll la element pentru a fi vizibil."""
        try:
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});",
                element
            )
            time.sleep(0.5)
        except Exception:
            pass

    def _login_if_needed(self):
        """Login pe PSI dacă avem credențiale."""
        if self._logged_in:
            return

        try:
            psi_user = st.secrets.get("SOURCES", {}).get("PSI_USER", "")
            psi_pass = st.secrets.get("SOURCES", {}).get("PSI_PASS", "")

            if not psi_user or not psi_pass:
                st.info("ℹ️ PSI: fără credențiale, continui fără login")
                return

            self._init_driver()
            if not self.driver:
                return

            # Navigăm la pagina de login
            login_url = f"{self.base_url}/login"
            st.info(f"🔐 PSI: Navighez la {login_url}")
            self.driver.get(login_url)
            time.sleep(4)

            # PASUL 1: Închidem cookie banner
            self._dismiss_cookie_banner()
            time.sleep(1)

            # PASUL 2: Completăm email
            email_field = None
            email_selectors = [
                "input[type='email']",
                "input[name='email']",
                "input[id*='email']",
                "input[name='username']",
                "input[placeholder*='mail']",
                "input[placeholder*='Mail']",
                "input[placeholder*='E-Mail']",
                "input.input[type='email']",
                "input.input[type='text']",
            ]

            for selector in email_selectors:
                try:
                    fields = self.driver.find_elements(
                        By.CSS_SELECTOR, selector
                    )
                    for field in fields:
                        if field.is_displayed() and field.is_enabled():
                            email_field = field
                            break
                    if email_field:
                        break
                except Exception:
                    continue

            if not email_field:
                # Încercăm XPath
                try:
                    email_field = self.driver.find_element(
                        By.XPATH,
                        "//input[@type='email' or @type='text']"
                        "[ancestor::form]"
                    )
                except Exception:
                    st.warning("⚠️ PSI: Nu găsesc câmpul de email")
                    return

            self._scroll_to_element(email_field)
            email_field.clear()
            email_field.send_keys(psi_user)
            time.sleep(0.5)

            # PASUL 3: Completăm parola
            pass_field = None
            try:
                pass_fields = self.driver.find_elements(
                    By.CSS_SELECTOR, "input[type='password']"
                )
                for field in pass_fields:
                    if field.is_displayed() and field.is_enabled():
                        pass_field = field
                        break
            except Exception:
                pass

            if not pass_field:
                st.warning("⚠️ PSI: Nu găsesc câmpul de parolă")
                return

            pass_field.clear()
            pass_field.send_keys(psi_pass)
            time.sleep(0.5)

            # PASUL 4: Click pe butonul de login
            # Închidem din nou cookie banner (poate a reapărut)
            self._dismiss_cookie_banner()
            time.sleep(0.5)

            submit_btn = None
            submit_selectors = [
                "button[type='submit']",
                "input[type='submit']",
                "button.is-primary[type='submit']",
                "button.is-primary",
                "button.btn-primary",
                "button.login-btn",
                "form button[type='submit']",
                "form button.is-primary",
            ]

            for selector in submit_selectors:
                try:
                    buttons = self.driver.find_elements(
                        By.CSS_SELECTOR, selector
                    )
                    for btn in buttons:
                        if btn.is_displayed():
                            submit_btn = btn
                            break
                    if submit_btn:
                        break
                except Exception:
                    continue

            if submit_btn:
                self._scroll_to_element(submit_btn)
                time.sleep(0.5)

                # Încercare 1: Click normal
                try:
                    submit_btn.click()
                    st.info("🔐 PSI: Click pe buton login (normal)")
                except ElementClickInterceptedException:
                    # Încercare 2: Eliminăm overlay-uri și click JS
                    st.info(
                        "🔐 PSI: Element interceptat, "
                        "elimin overlay și reîncerc..."
                    )
                    self._dismiss_cookie_banner()
                    time.sleep(0.5)

                    try:
                        submit_btn.click()
                    except ElementClickInterceptedException:
                        # Încercare 3: JavaScript click
                        st.info("🔐 PSI: Folosesc JavaScript click...")
                        self._js_click(submit_btn)
                except Exception as e:
                    # Încercare 4: JavaScript click direct
                    st.info(
                        f"🔐 PSI: Eroare click ({str(e)[:50]}), "
                        f"încerc JS..."
                    )
                    self._js_click(submit_btn)
            else:
                # Încercare 5: Submit form direct cu JavaScript
                st.info("🔐 PSI: Nu găsesc buton, submit form cu JS...")
                try:
                    self.driver.execute_script("""
                        var forms = document.querySelectorAll('form');
                        if (forms.length > 0) {
                            forms[0].submit();
                        }
                    """)
                except Exception:
                    # Încercare 6: Enter pe câmpul de parolă
                    from selenium.webdriver.common.keys import Keys
                    pass_field.send_keys(Keys.RETURN)

            time.sleep(5)

            # Verificăm dacă suntem logați
            current_url = self.driver.current_url
            page_source = self.driver.page_source.lower()

            if (
                'login' not in current_url.lower()
                or 'dashboard' in current_url.lower()
                or 'logout' in page_source
                or 'abmelden' in page_source
                or 'profil' in page_source
            ):
                self._logged_in = True
                st.success("✅ Logat pe PSI Product Finder!")
            else:
                st.warning(
                    "⚠️ PSI: Login posibil eșuat. "
                    "Continui oricum cu scraping..."
                )

        except Exception as e:
            st.warning(f"⚠️ PSI login error: {str(e)[:100]}")

    def scrape(self, url: str) -> dict | None:
        try:
            self._login_if_needed()

            # Folosim Selenium pentru PSI (are mult JS)
            soup = self.get_page(
                url,
                wait_selector=(
                    'h1, .product-name, [class*="product"], '
                    '.product-detail, .product-info'
                ),
                prefer_selenium=True
            )
            if not soup:
                return None

            # NUME PRODUS
            name = ""
            for sel in [
                'h1', '.product-name', '.product-title',
                '[class*="product-detail"] h1',
                '[class*="product"] h1',
                '.title.is-3', '.title.is-4',
                'h2.title', 'h1.title',
            ]:
                el = soup.select_one(sel)
                if el and el.get_text(strip=True):
                    name = el.get_text(strip=True)
                    break

            # SKU
            sku = ""
            # Din URL: p-ae08d17a-fahrradschloss...
            sku_match = re.search(r'/p-([a-f0-9]+)-', url)
            if sku_match:
                sku = f"PSI-{sku_match.group(1).upper()[:8]}"

            # Varianta din URL: v-013caef3
            variant_match = re.search(r'/v-([a-f0-9]+)', url)
            if variant_match:
                sku = (
                    f"PSI-{sku_match.group(1).upper()[:8]}-"
                    f"{variant_match.group(1).upper()[:8]}"
                    if sku_match
                    else f"PSI-V-{variant_match.group(1).upper()[:8]}"
                )

            for sel in [
                '.product-sku', '[class*="sku"]',
                '.article-number', '[class*="article"]',
                '.product-code', '[class*="code"]',
                '.tag.is-info', '.product-id',
            ]:
                el = soup.select_one(sel)
                if el:
                    sku_text = el.get_text(strip=True)
                    if sku_text and len(sku_text) < 30:
                        sku = sku_text
                    break

            # PREȚ
            price = 0.0
            for sel in [
                '.product-price', '.price', '[class*="price"]',
                '.tag.is-large', '[class*="cost"]',
            ]:
                el = soup.select_one(sel)
                if el:
                    price = clean_price(el.get_text(strip=True))
                    if price > 0:
                        break

            # DESCRIERE
            description = ""
            for sel in [
                '.product-description', '[class*="description"]',
                '.description', '.content',
                '.product-detail-description',
                '.product-info-description',
                'article .content',
            ]:
                el = soup.select_one(sel)
                if el:
                    description = str(el)
                    break

            # SPECIFICAȚII
            specifications = {}
            for sel in [
                'table', '.product-specifications',
                '[class*="spec"]', '.product-attributes',
                '.product-properties', '.product-features',
                'dl', '.table.is-striped',
            ]:
                container = soup.select_one(sel)
                if container:
                    # Tabel
                    rows = container.select('tr')
                    for row in rows:
                        cells = row.select('td, th')
                        if len(cells) >= 2:
                            k = cells[0].get_text(strip=True)
                            v = cells[1].get_text(strip=True)
                            if k and v:
                                specifications[k] = v

                    # Definition list
                    if not specifications:
                        dts = container.select('dt')
                        dds = container.select('dd')
                        for dt, dd in zip(dts, dds):
                            k = dt.get_text(strip=True)
                            v = dd.get_text(strip=True)
                            if k and v:
                                specifications[k] = v

                    # Li items
                    if not specifications:
                        lis = container.select('li')
                        for li in lis:
                            text = li.get_text(strip=True)
                            if ':' in text:
                                parts = text.split(':', 1)
                                specifications[
                                    parts[0].strip()
                                ] = parts[1].strip()

                    if specifications:
                        break

            # IMAGINI
            images = []
            for sel in [
                '.product-gallery img',
                '.product-images img',
                '[class*="gallery"] img',
                '.product-image img',
                'img[src*="product"]',
                'img[src*="media"]',
                'img[src*="image"]',
                '.image img',
                'figure img',
                '.carousel img',
                '.slider img',
            ]:
                imgs = soup.select(sel)
                if imgs:
                    for img in imgs:
                        src = (
                            img.get('data-src')
                            or img.get('src')
                            or img.get('data-lazy')
                            or img.get('data-original')
                            or ''
                        )
                        if src and 'placeholder' not in src.lower():
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
                    if images:
                        break

            # Fallback imagini
            if not images:
                all_imgs = soup.select('img')
                for img in all_imgs:
                    src = img.get('src', '') or img.get('data-src', '')
                    if src and any(
                        kw in src.lower()
                        for kw in [
                            'product', 'media', 'upload',
                            'image', 'photo', 'pic'
                        ]
                    ):
                        abs_url = make_absolute_url(src, self.base_url)
                        if (
                            abs_url not in images
                            and 'icon' not in abs_url.lower()
                            and 'logo' not in abs_url.lower()
                            and 'flag' not in abs_url.lower()
                            and len(abs_url) > 20
                        ):
                            images.append(abs_url)

            # CULORI
            colors = []
            for sel in [
                '.color-selector a',
                '[class*="color"] [class*="option"]',
                '[data-color]',
                '.color-options a',
                '.variant-color',
            ]:
                color_els = soup.select(sel)
                for el in color_els:
                    c = (
                        el.get('title')
                        or el.get('data-color')
                        or el.get('aria-label')
                        or el.get_text(strip=True)
                    )
                    if c and c not in colors and len(c) < 30:
                        colors.append(c)
                if colors:
                    break

            return self._build_product(
                name=name or f"Produs PSI {sku}",
                sku=sku,
                price=price,
                description=description,
                images=images,
                colors=colors,
                specifications=specifications,
                source_url=url,
                source_site=self.name,
            )

        except Exception as e:
            st.error(f"❌ Eroare scraping PSI: {str(e)}")
            return None
