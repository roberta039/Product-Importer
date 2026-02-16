# scrapers/psi.py
"""
Scraper pentru psiproductfinder.de.
Login fields: input[name='username'], input[name='password']
Cookie: #onetrust-accept-btn-handler
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
    NoSuchElementException, StaleElementReferenceException
)


class PSIScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.name = "psi"
        self.base_url = "https://psiproductfinder.de"
        self._logged_in = False

    def _dismiss_cookie_banner(self):
        """Închide OneTrust cookie banner."""
        if not self.driver:
            return

        # OneTrust - selectorul exact de pe PSI
        try:
            btn = self.driver.find_element(
                By.CSS_SELECTOR, "#onetrust-accept-btn-handler"
            )
            if btn.is_displayed():
                self.driver.execute_script(
                    "arguments[0].click();", btn
                )
                time.sleep(2)
                st.info("🍪 Cookie banner închis (OneTrust)")
                return
        except NoSuchElementException:
            pass

        # Fallback: eliminăm forțat
        try:
            self.driver.execute_script("""
                var el = document.getElementById('onetrust-banner-sdk');
                if (el) el.remove();
                var bg = document.getElementById('onetrust-consent-sdk');
                if (bg) bg.remove();
                var overlay = document.querySelector('.onetrust-pc-dark-filter');
                if (overlay) overlay.remove();
                document.body.style.overflow = 'auto';
                document.documentElement.style.overflow = 'auto';
            """)
            time.sleep(1)
        except Exception:
            pass

    def _login_if_needed(self):
        """Login pe PSI Product Finder."""
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

            # ═══ Navigăm la login ═══
            st.info("🔐 PSI: Mă conectez...")
            self.driver.get(f"{self.base_url}/login")
            time.sleep(5)

            # ═══ Închidem cookie banner ═══
            self._dismiss_cookie_banner()
            time.sleep(1)

            # ═══ Completăm username ═══
            # Selectorul EXACT de pe PSI: input[name='username']
            try:
                username_field = self.driver.find_element(
                    By.CSS_SELECTOR, "input[name='username']"
                )
            except NoSuchElementException:
                # Fallback
                try:
                    username_field = self.driver.find_element(
                        By.CSS_SELECTOR, "input[type='text']"
                    )
                except NoSuchElementException:
                    st.error("❌ PSI: Nu găsesc câmpul username")
                    return

            # Focus + clear + type
            self.driver.execute_script(
                "arguments[0].focus();", username_field
            )
            time.sleep(0.3)
            username_field.clear()
            username_field.send_keys(Keys.CONTROL, 'a')
            username_field.send_keys(Keys.DELETE)
            time.sleep(0.2)
            username_field.send_keys(psi_user)
            time.sleep(0.5)

            # ═══ Completăm parola ═══
            # Selectorul EXACT: input[name='password']
            try:
                password_field = self.driver.find_element(
                    By.CSS_SELECTOR, "input[name='password']"
                )
            except NoSuchElementException:
                try:
                    password_field = self.driver.find_element(
                        By.CSS_SELECTOR, "input[type='password']"
                    )
                except NoSuchElementException:
                    st.error("❌ PSI: Nu găsesc câmpul parolă")
                    return

            self.driver.execute_script(
                "arguments[0].focus();", password_field
            )
            time.sleep(0.3)
            password_field.clear()
            password_field.send_keys(Keys.CONTROL, 'a')
            password_field.send_keys(Keys.DELETE)
            time.sleep(0.2)
            password_field.send_keys(psi_pass)
            time.sleep(0.5)

            # ═══ Eliminăm overlay-uri înainte de submit ═══
            self._dismiss_cookie_banner()
            time.sleep(0.5)

            # ═══ Submit: 3 metode ═══
            submitted = False

            # Metoda 1: Găsim butonul submit și click cu JS
            submit_selectors = [
                "form button[type='submit']",
                "button[type='submit']",
                "button.is-primary",
                "button.button.is-primary",
            ]
            for selector in submit_selectors:
                try:
                    buttons = self.driver.find_elements(
                        By.CSS_SELECTOR, selector
                    )
                    for btn in buttons:
                        try:
                            if btn.is_displayed():
                                # Eliminăm orice overlay rămas
                                self.driver.execute_script("""
                                    var el = document.getElementById(
                                        'onetrust-banner-sdk'
                                    );
                                    if (el) el.remove();
                                    var overlay = document.querySelector(
                                        '.onetrust-pc-dark-filter'
                                    );
                                    if (overlay) overlay.remove();
                                    var sdk = document.getElementById(
                                        'onetrust-consent-sdk'
                                    );
                                    if (sdk) sdk.remove();
                                """)
                                time.sleep(0.3)

                                # Click cu JavaScript
                                self.driver.execute_script(
                                    "arguments[0].click();", btn
                                )
                                submitted = True
                                st.info(
                                    f"✅ PSI: Submit cu JS "
                                    f"[{selector}]"
                                )
                                break
                        except StaleElementReferenceException:
                            continue
                    if submitted:
                        break
                except Exception:
                    continue

            # Metoda 2: Form submit cu JS
            if not submitted:
                try:
                    self.driver.execute_script("""
                        var form = document.querySelector(
                            'form'
                        );
                        if (form) form.submit();
                    """)
                    submitted = True
                    st.info("✅ PSI: Submit cu form.submit()")
                except Exception:
                    pass

            # Metoda 3: ENTER pe parola
            if not submitted:
                try:
                    password_field.send_keys(Keys.RETURN)
                    submitted = True
                    st.info("✅ PSI: Submit cu ENTER")
                except Exception:
                    pass

            if not submitted:
                st.error("❌ PSI: Nu am putut trimite formularul")
                return

            # ═══ Așteptăm și verificăm ═══
            time.sleep(6)

            current_url = self.driver.current_url.lower()
            page_source = self.driver.page_source.lower()

            if (
                'login' not in current_url
                or 'logout' in page_source
                or 'abmelden' in page_source
                or 'profil' in page_source
                or 'dashboard' in current_url
            ):
                self._logged_in = True
                st.success("✅ PSI: Login reușit!")
            else:
                if any(
                    err in page_source
                    for err in [
                        'invalid', 'falsch', 'fehler',
                        'incorrect', 'ungültig'
                    ]
                ):
                    st.error(
                        "❌ PSI: Credențiale incorecte! "
                        "Verifică SOURCES.PSI_USER și "
                        "SOURCES.PSI_PASS în Secrets."
                    )
                else:
                    st.warning(
                        "⚠️ PSI: Status login neclar, "
                        "continui oricum..."
                    )
                    self._logged_in = True

        except Exception as e:
            st.error(f"❌ PSI login error: {str(e)}")

    def scrape(self, url: str) -> dict | None:
        """Scrape produs de pe psiproductfinder.de."""
        try:
            self._login_if_needed()

            soup = self.get_page(
                url,
                wait_selector=(
                    'h1, .title, article, '
                    '[class*="product"]'
                ),
                prefer_selenium=True
            )
            if not soup:
                return None

            # NUME
            name = ""
            for sel in [
                'h1', 'h1.title', '.title.is-3', '.title.is-4',
                '.product-name', '.product-title',
                'h2.title', 'article h1', 'article h2',
            ]:
                el = soup.select_one(sel)
                if el and el.get_text(strip=True):
                    text = el.get_text(strip=True)
                    if len(text) > 3:
                        name = text
                        break

            # SKU din URL
            sku = ""
            sku_match = re.search(r'/p-([a-f0-9]+)-', url)
            variant_match = re.search(r'/v-([a-f0-9]+)', url)

            if sku_match and variant_match:
                sku = (
                    f"PSI-{sku_match.group(1).upper()[:8]}-"
                    f"{variant_match.group(1).upper()[:8]}"
                )
            elif sku_match:
                sku = f"PSI-{sku_match.group(1).upper()[:8]}"
            elif variant_match:
                sku = f"PSI-V-{variant_match.group(1).upper()[:8]}"

            # SKU din pagină
            for sel in [
                '.product-sku', '[class*="sku"]',
                '.article-number', '[class*="article"]',
                '.product-code', '.tag.is-info',
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
                '.product-price', '.price',
                '[class*="price"]', '.tag.is-large',
            ]:
                el = soup.select_one(sel)
                if el:
                    price = clean_price(el.get_text(strip=True))
                    if price > 0:
                        break

            # DESCRIERE
            description = ""
            for sel in [
                '.product-description',
                '[class*="description"]',
                '.description', '.content',
                'article .content', 'article p',
            ]:
                el = soup.select_one(sel)
                if el:
                    description = str(el)
                    break

            # SPECIFICAȚII
            specifications = {}
            for sel in [
                'table', 'table.table',
                '.table.is-striped',
                '.product-specifications',
                '[class*="spec"]', 'dl',
            ]:
                container = soup.select_one(sel)
                if container:
                    # Table rows
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

                    if specifications:
                        break

            # IMAGINI
            images = []
            for sel in [
                '.product-gallery img',
                '.product-images img',
                '[class*="gallery"] img',
                '.product-image img',
                'figure img', '.image img',
                'article img',
                'img[src*="product"]',
                'img[src*="media"]',
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
                        if src and 'placeholder' not in src.lower():
                            abs_url = make_absolute_url(
                                src, self.base_url
                            )
                            if (
                                abs_url not in images
                                and 'icon' not in abs_url.lower()
                                and 'logo' not in abs_url.lower()
                                and 'flag' not in abs_url.lower()
                                and len(abs_url) > 20
                            ):
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
                        ):
                            images.append(abs_url)

            # CULORI
            colors = []
            for sel in [
                '.color-selector a', '[data-color]',
                '.color-options a', '.variant-color',
            ]:
                color_els = soup.select(sel)
                for el in color_els:
                    c = (
                        el.get('title')
                        or el.get('data-color')
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
