# gomag/importer.py
"""
Modul pentru import produse în Gomag.ro via Selenium browser automation.
"""
import os
import re
import time
import json
import tempfile
import streamlit as st
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, WebDriverException
)


class GomagImporter:
    """Importă produse în Gomag.ro folosind Selenium."""

    def __init__(self):
        self.driver = None
        self.logged_in = False
        self.base_url = ""
        self.categories_cache = []

    def _get_config(self) -> dict:
        """Citește configurarea din Streamlit Secrets."""
        try:
            gomag_secrets = st.secrets.get("GOMAG", {})
            return {
                'base_url': gomag_secrets.get(
                    "BASE_URL", "https://rucsacantifurtro.gomag.ro"
                ),
                'dashboard_path': gomag_secrets.get(
                    "DASHBOARD_PATH", "/gomag/dashboard"
                ),
                'username': gomag_secrets.get("USERNAME", ""),
                'password': gomag_secrets.get("PASSWORD", ""),
            }
        except Exception:
            return {
                'base_url': "https://rucsacantifurtro.gomag.ro",
                'dashboard_path': "/gomag/dashboard",
                'username': "",
                'password': "",
            }

    def _get_chrome_options(self) -> Options:
        """Chrome options pentru headless."""
        options = Options()
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument(
            '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        )
        options.add_argument('--disable-blink-features=AutomationControlled')

        if os.path.exists('/usr/bin/chromium'):
            options.binary_location = '/usr/bin/chromium'
        elif os.path.exists('/usr/bin/chromium-browser'):
            options.binary_location = '/usr/bin/chromium-browser'

        return options

    def _init_driver(self):
        """Inițializează WebDriver."""
        if self.driver:
            return

        try:
            options = self._get_chrome_options()

            driver_path = None
            for path in [
                '/usr/bin/chromedriver',
                '/usr/lib/chromium/chromedriver',
                '/usr/lib/chromium-browser/chromedriver',
            ]:
                if os.path.exists(path):
                    driver_path = path
                    break

            if driver_path:
                service = Service(executable_path=driver_path)
                self.driver = webdriver.Chrome(service=service, options=options)
            else:
                self.driver = webdriver.Chrome(options=options)

            self.driver.set_page_load_timeout(60)
            self.driver.implicitly_wait(10)

        except Exception as e:
            st.error(f"❌ Nu pot inițializa browser: {str(e)}")
            self.driver = None

    def login(self) -> bool:
        """Login în panoul Gomag."""
        if self.logged_in:
            return True

        config = self._get_config()
        if not config['username'] or not config['password']:
            st.error(
                "❌ Credențiale Gomag lipsă! Configurează GOMAG în Secrets."
            )
            return False

        self._init_driver()
        if not self.driver:
            return False

        try:
            self.base_url = config['base_url'].rstrip('/')
            login_url = f"{self.base_url}/gomag/login"

            st.info(f"🔐 Mă conectez la {login_url}...")
            self.driver.get(login_url)
            time.sleep(3)

            # Căutăm câmpul de email/username
            username_field = None
            for selector in [
                "input[name='email']",
                "input[name='username']",
                "input[type='email']",
                "input[name='user']",
                "input[id*='email']",
                "input[id*='user']",
                "input[type='text']",
            ]:
                try:
                    username_field = self.driver.find_element(
                        By.CSS_SELECTOR, selector
                    )
                    if username_field.is_displayed():
                        break
                    username_field = None
                except NoSuchElementException:
                    continue

            if not username_field:
                # Încercăm cu XPath
                try:
                    username_field = self.driver.find_element(
                        By.XPATH,
                        "//input[@type='text' or @type='email'][1]"
                    )
                except Exception:
                    st.error("❌ Nu găsesc câmpul de email/username")
                    self._save_screenshot("login_error")
                    return False

            username_field.clear()
            username_field.send_keys(config['username'])
            time.sleep(0.5)

            # Câmpul de parolă
            password_field = None
            try:
                password_field = self.driver.find_element(
                    By.CSS_SELECTOR, "input[type='password']"
                )
            except NoSuchElementException:
                st.error("❌ Nu găsesc câmpul de parolă")
                return False

            password_field.clear()
            password_field.send_keys(config['password'])
            time.sleep(0.5)

            # Butonul de submit
            submit_btn = None
            for selector in [
                "button[type='submit']",
                "input[type='submit']",
                "button.login-btn",
                "button.btn-login",
                "button[class*='login']",
                "button.btn-primary",
                ".login-form button",
                "form button",
            ]:
                try:
                    submit_btn = self.driver.find_element(
                        By.CSS_SELECTOR, selector
                    )
                    if submit_btn.is_displayed():
                        break
                    submit_btn = None
                except NoSuchElementException:
                    continue

            if not submit_btn:
                # Încercăm Enter
                password_field.send_keys(Keys.RETURN)
            else:
                submit_btn.click()

            time.sleep(5)

            # Verificăm dacă suntem logați
            current_url = self.driver.current_url
            if 'dashboard' in current_url or 'admin' in current_url:
                self.logged_in = True
                st.success("✅ Conectat la Gomag!")
                return True

            # Verificăm dacă există mesaj de eroare
            page_source = self.driver.page_source.lower()
            if any(
                err in page_source
                for err in ['invalid', 'error', 'incorrect', 'greșit',
                            'incorect']
            ):
                st.error("❌ Credențiale incorecte!")
                return False

            # Poate suntem logați dar pe altă pagină
            self.driver.get(
                f"{self.base_url}{config['dashboard_path']}"
            )
            time.sleep(3)

            if 'login' not in self.driver.current_url.lower():
                self.logged_in = True
                st.success("✅ Conectat la Gomag!")
                return True

            st.error("❌ Login eșuat - verifică credențialele")
            self._save_screenshot("login_failed")
            return False

        except Exception as e:
            st.error(f"❌ Eroare login Gomag: {str(e)}")
            return False

    def get_categories(self) -> list:
        """
        Obține lista de categorii din Gomag.
        Returnează lista de dict-uri {id, name, path}.
        """
        if self.categories_cache:
            return self.categories_cache

        if not self.logged_in:
            if not self.login():
                return []

        try:
            # Navigăm la pagina de categorii
            categories_url = f"{self.base_url}/gomag/categories"
            self.driver.get(categories_url)
            time.sleep(3)

            categories = []

            # Încercăm mai multe metode de a găsi categoriile
            # Metoda 1: Tabel cu categorii
            try:
                rows = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    "table tbody tr, .category-item, "
                    ".category-row, [class*='category'] li"
                )
                for row in rows:
                    try:
                        name_el = row.find_element(
                            By.CSS_SELECTOR,
                            "td:first-child a, .category-name, "
                            "a[class*='category']"
                        )
                        cat_name = name_el.text.strip()
                        cat_href = name_el.get_attribute('href') or ''
                        cat_id = ""

                        # Extragem ID din href
                        id_match = re.search(r'/(\d+)', cat_href)
                        if id_match:
                            cat_id = id_match.group(1)

                        if cat_name:
                            categories.append({
                                'id': cat_id,
                                'name': cat_name,
                                'path': cat_name,
                            })
                    except Exception:
                        continue
            except Exception:
                pass

            # Metoda 2: Select dropdown din pagina de adăugare produs
            if not categories:
                try:
                    add_url = f"{self.base_url}/gomag/products/add"
                    self.driver.get(add_url)
                    time.sleep(3)

                    # Căutăm select pentru categorie
                    for selector in [
                        "select[name*='category']",
                        "select[id*='category']",
                        "select[name*='categ']",
                        "#category_id",
                        "#product_category",
                    ]:
                        try:
                            select_el = self.driver.find_element(
                                By.CSS_SELECTOR, selector
                            )
                            options = select_el.find_elements(
                                By.TAG_NAME, "option"
                            )
                            for opt in options:
                                val = opt.get_attribute('value')
                                text = opt.text.strip()
                                if val and text and val != '0' and val != '':
                                    categories.append({
                                        'id': val,
                                        'name': text.strip('- '),
                                        'path': text,
                                    })
                            if categories:
                                break
                        except NoSuchElementException:
                            continue
                except Exception:
                    pass

            # Metoda 3: Checkboxes sau tree
            if not categories:
                try:
                    checkboxes = self.driver.find_elements(
                        By.CSS_SELECTOR,
                        "input[name*='category'], "
                        "[class*='category-tree'] input"
                    )
                    for cb in checkboxes:
                        try:
                            label = self.driver.find_element(
                                By.CSS_SELECTOR,
                                f"label[for='{cb.get_attribute('id')}']"
                            )
                            cat_name = label.text.strip()
                            cat_val = cb.get_attribute('value')
                            if cat_name and cat_val:
                                categories.append({
                                    'id': cat_val,
                                    'name': cat_name,
                                    'path': cat_name,
                                })
                        except Exception:
                            continue
                except Exception:
                    pass

            self.categories_cache = categories

            if not categories:
                st.warning(
                    "⚠️ Nu am putut extrage categoriile automat. "
                    "Poți introduce manual."
                )

            return categories

        except Exception as e:
            st.error(f"❌ Eroare obținere categorii: {str(e)}")
            return []

    def import_product(self, product: dict, category_id: str = "",
                       category_name: str = "") -> bool:
        """
        Importă un produs în Gomag prin browser automation.
        """
        if not self.logged_in:
            if not self.login():
                return False

        try:
            # Navigăm la pagina de adăugare produs
            add_url = f"{self.base_url}/gomag/products/add"
            self.driver.get(add_url)
            time.sleep(3)

            # --- NUME PRODUS ---
            self._fill_field(
                [
                    "input[name='name']",
                    "input[name='title']",
                    "input[name='product_name']",
                    "input[id*='name']",
                    "input[id*='title']",
                ],
                product.get('name', 'Produs Importat')
            )
            time.sleep(0.5)

            # --- SKU ---
            self._fill_field(
                [
                    "input[name='sku']",
                    "input[name='code']",
                    "input[name='product_code']",
                    "input[id*='sku']",
                    "input[id*='code']",
                ],
                product.get('sku', '')
            )
            time.sleep(0.3)

            # --- PREȚ ---
            price_str = str(product.get('final_price', 1.0))
            self._fill_field(
                [
                    "input[name='price']",
                    "input[name='regular_price']",
                    "input[id*='price']",
                ],
                price_str
            )
            time.sleep(0.3)

            # --- STOC ---
            self._fill_field(
                [
                    "input[name='stock']",
                    "input[name='quantity']",
                    "input[id*='stock']",
                    "input[id*='quantity']",
                ],
                "1"
            )
            time.sleep(0.3)

            # --- CATEGORIE ---
            if category_id:
                self._select_category(category_id, category_name)

            # --- DESCRIERE ---
            description = product.get('description', '')
            if description:
                self._fill_description(description)

            # --- IMAGINI ---
            images = product.get('images', [])
            if images:
                self._upload_images(images)

            # --- STATUS VIZIBIL ---
            self._set_product_visible()

            # --- SALVARE ---
            time.sleep(1)
            saved = self._save_product()

            if saved:
                st.success(
                    f"✅ Produs importat: {product.get('name', 'N/A')}"
                )
            else:
                st.warning(
                    f"⚠️ Posibil salvat cu probleme: "
                    f"{product.get('name', 'N/A')}"
                )

            return saved

        except Exception as e:
            st.error(
                f"❌ Eroare import produs "
                f"{product.get('name', 'N/A')}: {str(e)}"
            )
            self._save_screenshot("import_error")
            return False

    def _fill_field(self, selectors: list, value: str):
        """Completează un câmp găsit prin mai mulți selectori."""
        for selector in selectors:
            try:
                field = self.driver.find_element(By.CSS_SELECTOR, selector)
                if field.is_displayed():
                    field.clear()
                    field.send_keys(value)
                    return True
            except NoSuchElementException:
                continue
        return False

    def _select_category(self, category_id: str, category_name: str = ""):
        """Selectează categoria produsului."""
        # Metoda 1: Select dropdown
        for selector in [
            "select[name*='category']",
            "select[id*='category']",
            "#category_id",
        ]:
            try:
                select_el = self.driver.find_element(
                    By.CSS_SELECTOR, selector
                )
                select = Select(select_el)
                try:
                    select.select_by_value(category_id)
                    return
                except Exception:
                    if category_name:
                        try:
                            select.select_by_visible_text(category_name)
                            return
                        except Exception:
                            pass
            except NoSuchElementException:
                continue

        # Metoda 2: Checkbox
        try:
            checkbox = self.driver.find_element(
                By.CSS_SELECTOR,
                f"input[value='{category_id}'][name*='category']"
            )
            if not checkbox.is_selected():
                checkbox.click()
            return
        except NoSuchElementException:
            pass

        # Metoda 3: Click pe text
        if category_name:
            try:
                labels = self.driver.find_elements(
                    By.XPATH,
                    f"//label[contains(text(), '{category_name}')]"
                )
                for label in labels:
                    try:
                        label.click()
                        return
                    except Exception:
                        continue
            except Exception:
                pass

    def _fill_description(self, description: str):
        """Completează descrierea produsului (cu suport TinyMCE/CKEditor)."""
        # Metoda 1: Textarea simplă
        for selector in [
            "textarea[name='description']",
            "textarea[name='body']",
            "textarea[id*='description']",
            "textarea[id*='content']",
        ]:
            try:
                textarea = self.driver.find_element(
                    By.CSS_SELECTOR, selector
                )
                if textarea.is_displayed():
                    textarea.clear()
                    textarea.send_keys(description)
                    return
            except NoSuchElementException:
                continue

        # Metoda 2: TinyMCE
        try:
            iframes = self.driver.find_elements(
                By.CSS_SELECTOR, "iframe[id*='mce'], iframe[id*='editor']"
            )
            for iframe in iframes:
                try:
                    self.driver.switch_to.frame(iframe)
                    body = self.driver.find_element(
                        By.CSS_SELECTOR, "body"
                    )
                    body.clear()
                    self.driver.execute_script(
                        "arguments[0].innerHTML = arguments[1];",
                        body, description
                    )
                    self.driver.switch_to.default_content()
                    return
                except Exception:
                    self.driver.switch_to.default_content()
                    continue
        except Exception:
            pass

        # Metoda 3: CKEditor
        try:
            self.driver.execute_script("""
                if (typeof CKEDITOR !== 'undefined') {
                    for (var name in CKEDITOR.instances) {
                        CKEDITOR.instances[name].setData(arguments[0]);
                        return;
                    }
                }
            """, description)
        except Exception:
            pass

        # Metoda 4: ContentEditable
        try:
            editable = self.driver.find_element(
                By.CSS_SELECTOR,
                "[contenteditable='true']"
            )
            self.driver.execute_script(
                "arguments[0].innerHTML = arguments[1];",
                editable, description
            )
        except Exception:
            pass

    def _upload_images(self, image_urls: list):
        """Upload imagini sau setează URL-uri de imagini."""
        # Metoda 1: Câmp de URL imagine
        for i, img_url in enumerate(image_urls[:5]):  # max 5 imagini
            for selector in [
                f"input[name='image_url[{i}]']",
                f"input[name='images[{i}]']",
                "input[name='image_url']",
                "input[name='image']",
                "input[id*='image_url']",
            ]:
                try:
                    field = self.driver.find_element(
                        By.CSS_SELECTOR, selector
                    )
                    if field.is_displayed():
                        field.clear()
                        field.send_keys(img_url)
                        break
                except NoSuchElementException:
                    continue

        # Metoda 2: Buton de adăugare imagine prin URL
        try:
            for img_url in image_urls[:5]:
                add_btns = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    "button[class*='add-image'], "
                    "a[class*='add-image'], "
                    "[data-action='add-image']"
                )
                for btn in add_btns:
                    try:
                        btn.click()
                        time.sleep(1)

                        url_input = self.driver.find_element(
                            By.CSS_SELECTOR,
                            ".modal input[type='url'], "
                            ".modal input[type='text'], "
                            ".popup input[type='url']"
                        )
                        url_input.clear()
                        url_input.send_keys(img_url)

                        confirm_btn = self.driver.find_element(
                            By.CSS_SELECTOR,
                            ".modal button[type='submit'], "
                            ".modal .btn-primary, "
                            ".popup button.confirm"
                        )
                        confirm_btn.click()
                        time.sleep(1)
                        break
                    except Exception:
                        continue
        except Exception:
            pass

    def _set_product_visible(self):
        """Setează produsul ca vizibil."""
        # Metoda 1: Checkbox activ
        for selector in [
            "input[name='active']",
            "input[name='status']",
            "input[name='visible']",
            "input[name='is_active']",
            "input[id*='active']",
            "input[id*='status']",
        ]:
            try:
                checkbox = self.driver.find_element(
                    By.CSS_SELECTOR, selector
                )
                if checkbox.get_attribute('type') == 'checkbox':
                    if not checkbox.is_selected():
                        checkbox.click()
                    return
            except NoSuchElementException:
                continue

        # Metoda 2: Select status
        for selector in [
            "select[name='status']",
            "select[name='active']",
            "select[id*='status']",
        ]:
            try:
                select_el = self.driver.find_element(
                    By.CSS_SELECTOR, selector
                )
                select = Select(select_el)
                try:
                    select.select_by_value('1')
                except Exception:
                    try:
                        select.select_by_visible_text('Activ')
                    except Exception:
                        try:
                            select.select_by_visible_text('Active')
                        except Exception:
                            select.select_by_index(1)
                return
            except NoSuchElementException:
                continue

    def _save_product(self) -> bool:
        """Apasă butonul de salvare."""
        for selector in [
            "button[type='submit']",
            "input[type='submit']",
            "button.btn-save",
            "button[class*='save']",
            "button.btn-primary",
            "#save-product",
            "button[name='save']",
            ".form-actions button[type='submit']",
        ]:
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, selector)
                if btn.is_displayed():
                    # Scroll to button
                    self.driver.execute_script(
                        "arguments[0].scrollIntoView(true);", btn
                    )
                    time.sleep(0.5)
                    btn.click()
                    time.sleep(5)

                    # Verificăm dacă s-a salvat
                    page_source = self.driver.page_source.lower()
                    if any(
                        msg in page_source
                        for msg in [
                            'success', 'salvat', 'saved', 'creat',
                            'created', 'adăugat', 'added'
                        ]
                    ):
                        return True

                    # Dacă nu avem eroare, presupunem succes
                    if not any(
                        err in page_source
                        for err in ['error', 'eroare', 'failed', 'eșuat']
                    ):
                        return True

                    return False
            except NoSuchElementException:
                continue

        st.warning("⚠️ Nu am găsit butonul de salvare")
        return False

    def _save_screenshot(self, name: str):
        """Salvează screenshot pentru debugging."""
        if not self.driver:
            return
        try:
            screenshot = self.driver.get_screenshot_as_png()
            st.image(screenshot, caption=f"Screenshot: {name}", width=600)
        except Exception:
            pass

    def close(self):
        """Închide browserul."""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
        self.logged_in = False

    def __del__(self):
        self.close()
