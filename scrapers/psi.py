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
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException,
    ElementClickInterceptedException, StaleElementReferenceException
)


class PSIScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.name = "psi"
        self.base_url = "https://psiproductfinder.de"
        self._logged_in = False

    def _save_debug_screenshot(self, name: str):
        """Salvează screenshot pentru debugging."""
        if not self.driver:
            return
        try:
            screenshot = self.driver.get_screenshot_as_png()
            st.image(
                screenshot,
                caption=f"🖥️ Debug PSI: {name}",
                width=700
            )
        except Exception as e:
            st.warning(f"⚠️ Nu pot face screenshot: {str(e)[:50]}")

    def _log_page_info(self, step_name: str):
        """Loghează informații despre pagina curentă."""
        if not self.driver:
            return
        try:
            url = self.driver.current_url
            title = self.driver.title
            st.info(
                f"📄 PSI [{step_name}] URL: {url[:80]} | "
                f"Title: {title[:50]}"
            )
        except Exception:
            pass

    def _dismiss_all_overlays(self):
        """Elimină TOATE overlay-urile, cookie banners, modals."""
        if not self.driver:
            return

        # PASUL 1: Încearcă click pe butoane de accept
        cookie_button_selectors = [
            # PSI specifice (Bulma framework)
            "button.is-primary",
            ".modal.is-active button.is-primary",
            ".modal.is-active .button.is-primary",
            # Cookie consent comune
            "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
            "#CybotCookiebotDialogBodyButtonAccept",
            "#onetrust-accept-btn-handler",
            ".cc-accept",
            ".cc-allow",
            ".cc-dismiss",
            # Generic
            "button[data-action='accept']",
            "button[data-action='allow']",
            "[class*='cookie'] button",
            "[class*='consent'] button",
            "[class*='privacy'] button",
            "[id*='cookie'] button",
            "[id*='consent'] button",
        ]

        for selector in cookie_button_selectors:
            try:
                buttons = self.driver.find_elements(
                    By.CSS_SELECTOR, selector
                )
                for btn in buttons:
                    if btn.is_displayed():
                        try:
                            self.driver.execute_script(
                                "arguments[0].click();", btn
                            )
                            time.sleep(1)
                            st.info(
                                f"🍪 Click pe: {selector} "
                                f"(text: {btn.text[:30]})"
                            )
                            return
                        except Exception:
                            continue
            except Exception:
                continue

        # PASUL 2: Căutăm prin text (DE + EN)
        accept_texts = [
            "Alle akzeptieren", "Akzeptieren", "Verstanden",
            "Einverstanden", "Zustimmen", "OK",
            "Accept All", "Accept", "Allow All", "Allow",
            "Agree", "Got it", "I agree",
            "Alle Cookies akzeptieren",
        ]
        for text in accept_texts:
            try:
                # Buton cu text exact
                btn = self.driver.find_element(
                    By.XPATH,
                    f"//button[normalize-space()='{text}']"
                )
                if btn.is_displayed():
                    self.driver.execute_script(
                        "arguments[0].click();", btn
                    )
                    time.sleep(1)
                    st.info(f"🍪 Click pe buton cu text: '{text}'")
                    return
            except NoSuchElementException:
                pass

            try:
                # Buton care conține textul
                btn = self.driver.find_element(
                    By.XPATH,
                    f"//button[contains(text(), '{text}')]"
                )
                if btn.is_displayed():
                    self.driver.execute_script(
                        "arguments[0].click();", btn
                    )
                    time.sleep(1)
                    st.info(f"🍪 Click pe buton conținând: '{text}'")
                    return
            except NoSuchElementException:
                continue

        # PASUL 3: Eliminăm forțat cu JavaScript
        try:
            removed = self.driver.execute_script("""
                var removed = 0;
                // Eliminăm elementele care blochează
                var selectors = [
                    '.modal.is-active', '.modal-background',
                    '.cookie-banner', '.cookie-notice',
                    '.cookie-consent', '#cookie-banner',
                    '#cookieBanner', '.gdpr-banner',
                    '.privacy-banner', '.consent-banner',
                    '[class*="cookie"]', '[class*="consent"]',
                    '[id*="cookie"]', '[id*="consent"]',
                    '.overlay', '.popup',
                    '#CybotCookiebotDialog',
                    '#onetrust-banner-sdk',
                ];
                selectors.forEach(function(sel) {
                    var elements = document.querySelectorAll(sel);
                    elements.forEach(function(el) {
                        el.parentNode.removeChild(el);
                        removed++;
                    });
                });
                // Resetăm body
                document.body.style.overflow = 'auto';
                document.body.style.position = 'static';
                document.documentElement.style.overflow = 'auto';
                // Eliminăm clase de pe body
                document.body.classList.remove(
                    'modal-open', 'no-scroll', 'has-modal'
                );
                return removed;
            """)
            if removed > 0:
                st.info(f"🧹 Eliminat {removed} overlay-uri cu JS")
        except Exception:
            pass

        time.sleep(0.5)

    def _login_if_needed(self):
        """Login pe PSI cu debugging detaliat."""
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
                st.error("❌ PSI: Nu pot inițializa browserul")
                return

            # ═══ PASUL 1: Navigăm la login ═══
            login_url = f"{self.base_url}/login"
            st.info(f"🔐 PSI: Navighez la {login_url}")
            self.driver.get(login_url)
            time.sleep(5)  # așteptăm mai mult pentru JS

            self._log_page_info("După navigare login")
            self._save_debug_screenshot("1_pagina_login")

            # ═══ PASUL 2: Închidem TOATE overlay-urile ═══
            st.info("🍪 PSI: Încerc să închid overlay-uri...")
            self._dismiss_all_overlays()
            time.sleep(2)

            self._save_debug_screenshot("2_dupa_cookie_dismiss")

            # ═══ PASUL 3: Găsim formularul de login ═══
            # Listăm toate input-urile vizibile pentru debug
            try:
                all_inputs = self.driver.find_elements(
                    By.CSS_SELECTOR, "input"
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
                                f"id={inp_id}, placeholder={inp_ph}"
                            )
                    except StaleElementReferenceException:
                        continue

                st.info(
                    f"📋 PSI: {len(visible_inputs)} input-uri vizibile: "
                    f"{visible_inputs[:5]}"
                )
            except Exception as e:
                st.warning(f"⚠️ PSI: Nu pot lista input-uri: {str(e)[:50]}")

            # ═══ PASUL 4: Completăm email ═══
            email_field = None
            email_selectors = [
                "input[type='email']",
                "input[name='email']",
                "input[name='_username']",
                "input[name='username']",
                "input[id='email']",
                "input[id='username']",
                "input[id='_username']",
                "input[placeholder*='mail']",
                "input[placeholder*='Mail']",
                "input[placeholder*='E-Mail']",
                "input[placeholder*='Benutzername']",
                "input[placeholder*='user']",
                "input.input[type='email']",
                "input.input[type='text']",
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
                                    f"✅ PSI: Câmp email găsit cu: "
                                    f"{selector}"
                                )
                                break
                        except StaleElementReferenceException:
                            continue
                    if email_field:
                        break
                except Exception:
                    continue

            if not email_field:
                st.error("❌ PSI: Nu găsesc câmpul de email/username!")
                self._save_debug_screenshot("ERROR_no_email_field")

                # Ultima încercare: primul input vizibil din form
                try:
                    forms = self.driver.find_elements(
                        By.CSS_SELECTOR, "form"
                    )
                    for form in forms:
                        inputs = form.find_elements(
                            By.CSS_SELECTOR, "input:not([type='hidden'])"
                        )
                        for inp in inputs:
                            if inp.is_displayed() and inp.is_enabled():
                                email_field = inp
                                st.info(
                                    "✅ PSI: Folosesc primul input "
                                    "din form ca email"
                                )
                                break
                        if email_field:
                            break
                except Exception:
                    pass

            if not email_field:
                st.error("❌ PSI: Nu pot continua fără câmp email")
                return

            # Scroll + focus + clear + type
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});",
                email_field
            )
            time.sleep(0.3)
            self.driver.execute_script(
                "arguments[0].focus();", email_field
            )
            time.sleep(0.2)
            email_field.clear()
            time.sleep(0.2)

            # Ștergem conținutul existent cu select all + delete
            email_field.send_keys(Keys.CONTROL, 'a')
            email_field.send_keys(Keys.DELETE)
            time.sleep(0.2)

            email_field.send_keys(psi_user)
            time.sleep(0.5)

            st.info(f"✅ PSI: Email completat: {psi_user[:3]}***")

            # ═══ PASUL 5: Completăm parola ═══
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
                st.error("❌ PSI: Nu găsesc câmpul de parolă!")
                self._save_debug_screenshot("ERROR_no_password_field")
                return

            self.driver.execute_script(
                "arguments[0].focus();", pass_field
            )
            time.sleep(0.2)
            pass_field.clear()
            pass_field.send_keys(Keys.CONTROL, 'a')
            pass_field.send_keys(Keys.DELETE)
            time.sleep(0.2)
            pass_field.send_keys(psi_pass)
            time.sleep(0.5)

            st.info("✅ PSI: Parolă completată")
            self._save_debug_screenshot("3_campuri_completate")

            # ═══ PASUL 6: Eliminăm overlay-uri ÎNAINTE de submit ═══
            self._dismiss_all_overlays()
            time.sleep(1)

            # ═══ PASUL 7: Submit login ═══
            login_success = False

            # Metoda A: Găsim butonul submit și click JS
            submit_selectors = [
                "form button[type='submit']",
                "button[type='submit']",
                "input[type='submit']",
                "button.is-primary",
                ".button.is-primary",
                "form .button.is-primary",
                "button.btn-primary",
                "button.login-button",
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
                                btn_text = btn.text.strip()
                                st.info(
                                    f"🔘 PSI: Buton găsit [{selector}]: "
                                    f"'{btn_text}'"
                                )

                                # Scroll la buton
                                self.driver.execute_script(
                                    "arguments[0].scrollIntoView("
                                    "{block: 'center'});",
                                    btn
                                )
                                time.sleep(0.5)

                                # Eliminăm overlay-uri o ultimă dată
                                self._dismiss_all_overlays()
                                time.sleep(0.3)

                                # Click cu JavaScript (cel mai sigur)
                                self.driver.execute_script(
                                    "arguments[0].click();", btn
                                )
                                st.info(
                                    "✅ PSI: Click JS pe butonul "
                                    f"'{btn_text}'"
                                )
                                login_success = True
                                break
                        except StaleElementReferenceException:
                            continue
                    if login_success:
                        break
                except Exception:
                    continue

            # Metoda B: Submit form cu JavaScript
            if not login_success:
                st.info("🔄 PSI: Încerc form.submit() cu JS...")
                try:
                    self.driver.execute_script("""
                        var forms = document.querySelectorAll('form');
                        for (var i = 0; i < forms.length; i++) {
                            var inputs = forms[i].querySelectorAll(
                                'input[type="password"]'
                            );
                            if (inputs.length > 0) {
                                forms[i].submit();
                                return true;
                            }
                        }
                        // Fallback: submit primul form
                        if (forms.length > 0) {
                            forms[0].submit();
                            return true;
                        }
                        return false;
                    """)
                    login_success = True
                    st.info("✅ PSI: Form submitted cu JS")
                except Exception as e:
                    st.warning(f"⚠️ PSI: form.submit() eșuat: {str(e)[:50]}")

            # Metoda C: Enter pe câmpul de parolă
            if not login_success:
                st.info("🔄 PSI: Încerc ENTER pe câmpul de parolă...")
                try:
                    pass_field.send_keys(Keys.RETURN)
                    login_success = True
                    st.info("✅ PSI: ENTER trimis")
                except Exception as e:
                    st.warning(
                        f"⚠️ PSI: ENTER eșuat: {str(e)[:50]}"
                    )

            # ═══ PASUL 8: Așteptăm și verificăm ═══
            time.sleep(6)

            self._log_page_info("După submit login")
            self._save_debug_screenshot("4_dupa_login_submit")

            # Verificăm dacă suntem logați
            current_url = self.driver.current_url.lower()
            page_source = self.driver.page_source.lower()

            login_indicators = [
                'logout' in page_source,
                'abmelden' in page_source,
                'profil' in page_source,
                'dashboard' in current_url,
                'account' in current_url,
                'login' not in current_url,
                'my-account' in page_source,
                'mein-konto' in page_source,
            ]

            if any(login_indicators):
                self._logged_in = True
                st.success("✅ PSI: Login reușit!")
            else:
                # Verificăm dacă sunt erori de login
                error_indicators = [
                    'invalid' in page_source,
                    'incorrect' in page_source,
                    'falsch' in page_source,
                    'fehler' in page_source,
                    'error' in page_source,
                    'ungültig' in page_source,
                ]

                if any(error_indicators):
                    st.error(
                        "❌ PSI: Credențiale incorecte sau eroare login!"
                    )
                else:
                    st.warning(
                        "⚠️ PSI: Nu pot confirma login. "
                        "Continui oricum..."
                    )
                    # Poate suntem logați dar pe o pagină diferită
                    self._logged_in = True

        except Exception as e:
            st.error(f"❌ PSI login error complet: {str(e)}")
            self._save_debug_screenshot("ERROR_login_exception")

    def scrape(self, url: str) -> dict | None:
        """Scrape produs de pe psiproductfinder.de."""
        try:
            self._login_if_needed()

            # Navigăm la produs
            st.info(f"📦 PSI: Scrapez {url[:80]}...")

            soup = self.get_page(
                url,
                wait_selector=(
                    'h1, .product-name, [class*="product"], '
                    '.product-detail, .product-info, '
                    '.title, article'
                ),
                prefer_selenium=True
            )
            if not soup:
                return None

            # NUME PRODUS
            name = ""
            for sel in [
                'h1', 'h1.title', '.title.is-3', '.title.is-4',
                '.product-name', '.product-title',
                '[class*="product-detail"] h1',
                '[class*="product"] h1',
                'h2.title', 'article h1', 'article h2',
            ]:
                el = soup.select_one(sel)
                if el and el.get_text(strip=True):
                    text = el.get_text(strip=True)
                    if len(text) > 3:  # evităm texte prea scurte
                        name = text
                        break

            # SKU
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
                'article .content', 'article p',
            ]:
                el = soup.select_one(sel)
                if el:
                    description = str(el)
                    break

            # SPECIFICAȚII
            specifications = {}
            for sel in [
                'table', 'table.table', '.table.is-striped',
                '.product-specifications', '[class*="spec"]',
                '.product-attributes', '.product-properties',
                'dl',
            ]:
                container = soup.select_one(sel)
                if container:
                    rows = container.select('tr')
                    for row in rows:
                        cells = row.select('td, th')
                        if len(cells) >= 2:
                            k = cells[0].get_text(strip=True)
                            v = cells[1].get_text(strip=True)
                            if k and v:
                                specifications[k] = v

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
                '.product-gallery img', '.product-images img',
                '[class*="gallery"] img', '.product-image img',
                'figure img', '.image img',
                'img[src*="product"]', 'img[src*="media"]',
                '.carousel img', '.slider img',
                'article img',
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
                                and len(abs_url) > 20
                            ):
                                images.append(abs_url)
                    if images:
                        break

            # Fallback imagini
            if not images:
                for img in soup.select('img'):
                    src = img.get('src', '') or img.get('data-src', '')
                    if src and any(
                        kw in src.lower()
                        for kw in [
                            'product', 'media', 'upload',
                            'image', 'photo'
                        ]
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
                        or el.get('aria-label')
                        or el.get_text(strip=True)
                    )
                    if c and c not in colors and len(c) < 30:
                        colors.append(c)
                if colors:
                    break

            product = self._build_product(
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

            st.info(
                f"📦 PSI: Extras: {product['name'][:50]} | "
                f"SKU: {product['sku']} | "
                f"Preț: {product['original_price']} | "
                f"Imagini: {len(product['images'])}"
            )

            return product

        except Exception as e:
            st.error(f"❌ Eroare scraping PSI: {str(e)}")
            return None
