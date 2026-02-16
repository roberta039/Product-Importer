# gomag/importer.py
"""
Modul pentru import produse în Gomag.ro
Metoda 1: Generare CSV compatibil cu importul Gomag
Metoda 2: Upload CSV prin Selenium (browser automation)
"""
import os
import io
import re
import time
import csv
import pandas as pd
import streamlit as st
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException,
    StaleElementReferenceException
)


class GomagImporter:
    """Importă produse în Gomag.ro prin CSV sau browser automation."""

    # Coloanele exacte din modelul de import Gomag
    GOMAG_COLUMNS = [
        'Cod Produs (SKU)',
        'Cod EAN',
        'Cod Grupa',
        'Varianta principala',
        'Denumire Produs',
        'Descriere Produs',
        'Descriere Scurta a Produsului',
        'URL Poza de Produs',
        'URL Video',
        'Pozitie in Listari',
        'Produse Cross-Sell',
        'Produse Up-Sell',
        'Descriere pt feed-uri',
        'Atribute: Culoare (variante de produs)',
        'Cuvinte Cautare',
        'Pret Produs: Descriere',
        'GEO',
        'Produs: Cantitate Totala',
        'Produs: Unitatea de Masura pentru Cantitatea Totala',
        'Produs: Cantitate Unitara',
        'Produs: Unitate de Masura pentru Cantitatea Unitara',
        'Pret Special',
        'Produs: Durata de Livrare',
        'Produs: Tip Durata de Livrare',
        'Produs: Cantitate Maxima',
        'Produs: Unitate de masura',
        'Produs: Cod extern',
        'Pret de Achizitie',
        'Produs: Tag postari',
        'Produs: Produs digital',
        'Produs: Data ultimei modificari de pret',
        'Produs: Cota TVA diferita pentru persoanele juridice',
        'Pretul Include TVA',
        'Produs: Cota TVA persoane juridice',
        'Produs: Informatii siguranta produs',
        'Cota TVA',
        'Moneda',
        'Stoc Cantitativ',
        'Completare Stoc Cantitativ',
        'Stare Stoc',
        'Gestioneaza Automat Stocul',
        'Se Aduce la Comanda',
        'Cantitate Minima',
        'Increment de Cantitate',
        'Greutate (Kg)',
        'Activ in Magazin',
        'Activ in Magazin de la data de',
        'Activ in Magazin pana la data de',
        'Categorie / Categorii',
        'Marca (Brand)',
        'Titlu Meta',
        'Descriere Meta',
        'Cuvinte Cheie',
        'Titlul Imaginii Principale',
        'Url Link Canonical',
        'Id Produs',
    ]

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
                    "BASE_URL",
                    "https://rucsacantifurtro.gomag.ro"
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
                self.driver = webdriver.Chrome(
                    service=service, options=options
                )
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
                "❌ Credențiale Gomag lipsă! "
                "Configurează GOMAG în Secrets."
            )
            return False

        self._init_driver()
        if not self.driver:
            return False

        try:
            self.base_url = config['base_url'].rstrip('/')
            login_url = f"{self.base_url}/gomag/login"

            st.info(f"🔐 Mă conectez la Gomag...")
            self.driver.get(login_url)
            time.sleep(4)

            # Email
            email_field = None
            for selector in [
                "input[name='email']",
                "input[name='username']",
                "input[type='email']",
                "input[type='text']",
            ]:
                try:
                    field = self.driver.find_element(
                        By.CSS_SELECTOR, selector
                    )
                    if field.is_displayed():
                        email_field = field
                        break
                except NoSuchElementException:
                    continue

            if not email_field:
                st.error("❌ Nu găsesc câmpul de email Gomag")
                return False

            email_field.clear()
            email_field.send_keys(config['username'])
            time.sleep(0.5)

            # Parolă
            try:
                pass_field = self.driver.find_element(
                    By.CSS_SELECTOR, "input[type='password']"
                )
            except NoSuchElementException:
                st.error("❌ Nu găsesc câmpul de parolă Gomag")
                return False

            pass_field.clear()
            pass_field.send_keys(config['password'])
            time.sleep(0.5)

            # Submit
            try:
                btn = self.driver.find_element(
                    By.CSS_SELECTOR,
                    "button[type='submit'], input[type='submit']"
                )
                self.driver.execute_script(
                    "arguments[0].click();", btn
                )
            except NoSuchElementException:
                pass_field.send_keys(Keys.RETURN)

            time.sleep(5)

            current_url = self.driver.current_url
            if (
                'dashboard' in current_url
                or 'admin' in current_url
                or 'login' not in current_url
            ):
                self.logged_in = True
                st.success("✅ Conectat la Gomag!")
                return True

            st.error("❌ Login Gomag eșuat")
            return False

        except Exception as e:
            st.error(f"❌ Eroare login Gomag: {str(e)}")
            return False

    def get_categories(self) -> list:
        """Obține categoriile din Gomag."""
        if self.categories_cache:
            return self.categories_cache

        if not self.logged_in:
            if not self.login():
                return []

        try:
            self.driver.get(f"{self.base_url}/gomag/categories")
            time.sleep(4)

            categories = []

            # Tabel
            try:
                rows = self.driver.find_elements(
                    By.CSS_SELECTOR, "table tbody tr"
                )
                for row in rows:
                    try:
                        name_el = row.find_element(
                            By.CSS_SELECTOR, "td a, td:first-child"
                        )
                        cat_name = name_el.text.strip()
                        cat_href = (
                            name_el.get_attribute('href') or ''
                        )
                        cat_id = ""
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

            # Select din pagina add product
            if not categories:
                try:
                    self.driver.get(
                        f"{self.base_url}/gomag/products/add"
                    )
                    time.sleep(3)
                    for selector in [
                        "select[name*='category']",
                        "select[id*='category']",
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
                                if (
                                    val and text
                                    and val != '0' and val != ''
                                ):
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

            self.categories_cache = categories
            return categories

        except Exception as e:
            st.error(f"❌ Eroare obținere categorii: {str(e)}")
            return []

    # ══════════════════════════════════════════════
    # GENERARE CSV COMPATIBIL GOMAG
    # ══════════════════════════════════════════════

    def generate_gomag_csv(
        self,
        products: list,
        category_name: str = "",
        brand: str = "",
    ) -> pd.DataFrame:
        """
        Generează un DataFrame cu structura exactă
        a modelului de import Gomag.
        """
        rows = []

        for product in products:
            row = self._product_to_gomag_row(
                product, category_name, brand
            )
            rows.append(row)

        df = pd.DataFrame(rows, columns=self.GOMAG_COLUMNS)
        return df

    def _product_to_gomag_row(
        self,
        product: dict,
        category_name: str = "",
        brand: str = "",
    ) -> list:
        """Convertește un produs scraped în rând Gomag CSV."""

        # SKU
        sku = product.get('sku', '')

        # Nume
        name = product.get('name', 'Produs Importat')

        # Descriere HTML
        description = product.get('description', '')

        # Descriere scurtă
        short_desc = ""
        if product.get('specifications'):
            specs_parts = []
            for k, v in product['specifications'].items():
                specs_parts.append(f"{k}: {v}")
            short_desc = " | ".join(specs_parts[:5])

        if not short_desc and description:
            # Extragem text simplu din HTML
            import re as re_mod
            clean = re_mod.sub(r'<[^>]+>', '', description)
            short_desc = clean[:250].strip()

        # URL Imagini - separate cu |
        images = product.get('images', [])
        images_url = '|'.join(images[:10]) if images else ''

        # Culori - separate cu ,
        colors = product.get('colors', [])
        colors_str = ','.join(colors) if colors else ''

        # Preț
        price = product.get('final_price', 1.0)
        if price <= 0:
            price = 1.0
        price_str = f"{price:.2f}"

        # Preț achiziție (original)
        buy_price = product.get('original_price', 0)
        buy_price_str = (
            f"{buy_price:.2f}" if buy_price > 0 else ""
        )

        # Greutate
        weight = product.get('weight', '')
        weight_str = ""
        if weight:
            weight_match = re.search(r'([\d.]+)', str(weight))
            if weight_match:
                weight_str = weight_match.group(1)

        # Cuvinte cheie
        keywords = name.lower().replace('-', ' ')
        if 'anti' in keywords.lower():
            keywords += ", anti-furt, anti-theft"
        if 'rucsac' in keywords.lower() or 'backpack' in keywords.lower():
            keywords += ", rucsac, backpack"
        keywords += ", protectie, siguranta"

        # Descriere Meta
        meta_desc = short_desc[:160] if short_desc else name[:160]

        # Brand
        if not brand:
            source = product.get('source_site', '')
            brand_map = {
                'xdconnects': 'XD Design',
                'pfconcept': 'PF Concept',
                'promobox': 'Promobox',
                'andapresent': 'Anda Present',
                'midocean': 'Midocean',
                'sipec': 'Sipec',
                'stricker': 'Stricker',
                'stamina': 'Stamina',
                'utteam': 'UT Team',
                'clipper': 'Clipper',
                'psi': 'PSI',
            }
            brand = brand_map.get(source, source)

        # Construim rândul cu TOATE coloanele Gomag
        row = [
            sku,                            # Cod Produs (SKU)
            '',                             # Cod EAN
            '',                             # Cod Grupa
            '',                             # Varianta principala
            name,                           # Denumire Produs
            description,                    # Descriere Produs
            short_desc,                     # Descriere Scurta
            images_url,                     # URL Poza de Produs
            '',                             # URL Video
            '',                             # Pozitie in Listari
            '',                             # Produse Cross-Sell
            '',                             # Produse Up-Sell
            short_desc[:200],               # Descriere pt feed-uri
            colors_str,                     # Atribute: Culoare
            keywords,                       # Cuvinte Cautare
            price_str,                      # Pret Produs: Descriere
            '',                             # GEO
            '',                             # Cantitate Totala
            '',                             # UM Cantitate Totala
            '',                             # Cantitate Unitara
            '',                             # UM Cantitate Unitara
            '',                             # Pret Special
            '2-5 zile lucratoare',          # Durata de Livrare
            'zile',                         # Tip Durata Livrare
            '',                             # Cantitate Maxima
            'buc',                          # Unitate de masura
            product.get('source_url', ''),  # Cod extern
            buy_price_str,                  # Pret de Achizitie
            '',                             # Tag postari
            '0',                            # Produs digital
            '',                             # Data modif pret
            '',                             # Cota TVA diferita PJ
            '1',                            # Pretul Include TVA
            '',                             # Cota TVA PJ
            '',                             # Info siguranta
            '19',                           # Cota TVA
            'RON',                          # Moneda
            '1',                            # Stoc Cantitativ
            '',                             # Completare Stoc
            'In Stoc',                      # Stare Stoc
            '0',                            # Gestioneaza Auto Stoc
            '0',                            # Se Aduce la Comanda
            '1',                            # Cantitate Minima
            '1',                            # Increment Cantitate
            weight_str,                     # Greutate (Kg)
            '1',                            # Activ in Magazin
            '',                             # Activ de la
            '',                             # Activ pana la
            category_name,                  # Categorie
            brand,                          # Marca (Brand)
            name[:70],                      # Titlu Meta
            meta_desc,                      # Descriere Meta
            keywords[:250],                 # Cuvinte Cheie
            name[:100],                     # Titlul Imaginii
            '',                             # Url Link Canonical
            '',                             # Id Produs
        ]

        return row

    def generate_csv_file(
        self,
        products: list,
        category_name: str = "",
        brand: str = "",
    ) -> bytes:
        """
        Generează CSV-ul ca bytes pentru download.
        Encoding: UTF-8 cu BOM (Excel compatibility).
        """
        df = self.generate_gomag_csv(
            products, category_name, brand
        )

        # CSV cu separator ; (Gomag standard)
        output = io.StringIO()
        df.to_csv(
            output,
            index=False,
            sep=',',
            quoting=csv.QUOTE_ALL,
            encoding='utf-8',
        )

        csv_content = output.getvalue()
        # Adăugăm BOM pentru Excel
        return ('\ufeff' + csv_content).encode('utf-8')

    def generate_excel_file(
        self,
        products: list,
        category_name: str = "",
        brand: str = "",
    ) -> bytes:
        """Generează Excel-ul pentru import Gomag."""
        df = self.generate_gomag_csv(
            products, category_name, brand
        )

        excel_buffer = io.BytesIO()
        df.to_excel(
            excel_buffer,
            index=False,
            engine='openpyxl',
        )
        excel_buffer.seek(0)
        return excel_buffer.getvalue()

    # ══════════════════════════════════════════════
    # UPLOAD CSV ÎN GOMAG (Browser Automation)
    # ══════════════════════════════════════════════

    def upload_csv_to_gomag(self, csv_bytes: bytes) -> bool:
        """
        Uploadează CSV-ul în Gomag prin browser automation.
        Navighează la Import Produse → Upload fișier.
        """
        if not self.logged_in:
            if not self.login():
                return False

        try:
            # Navigăm la pagina de import
            import_urls = [
                f"{self.base_url}/gomag/products/import",
                f"{self.base_url}/gomag/import",
                f"{self.base_url}/gomag/products/csv-import",
            ]

            import_page_found = False
            for import_url in import_urls:
                self.driver.get(import_url)
                time.sleep(3)
                # Verificăm dacă pagina există
                if 'import' in self.driver.current_url.lower():
                    import_page_found = True
                    st.info(
                        f"📄 Gomag: Pagina import: "
                        f"{self.driver.current_url[:60]}"
                    )
                    break
                # Verificăm dacă avem input file
                try:
                    self.driver.find_element(
                        By.CSS_SELECTOR, "input[type='file']"
                    )
                    import_page_found = True
                    break
                except NoSuchElementException:
                    continue

            if not import_page_found:
                st.error(
                    "❌ Nu găsesc pagina de import produse "
                    "în Gomag"
                )
                # Screenshot debug
                try:
                    screenshot = self.driver.get_screenshot_as_png()
                    st.image(
                        screenshot,
                        caption="Gomag - căutare import",
                        width=700
                    )
                except Exception:
                    pass
                return False

            # Salvăm CSV-ul temporar
            import tempfile
            tmp_file = tempfile.NamedTemporaryFile(
                suffix='.csv',
                delete=False,
                mode='wb'
            )
            tmp_file.write(csv_bytes)
            tmp_file.close()
            tmp_path = tmp_file.name

            try:
                # Găsim input-ul de file
                file_input = None
                for selector in [
                    "input[type='file']",
                    "input[name='file']",
                    "input[name='import_file']",
                    "input[name='csv_file']",
                    "input[accept*='.csv']",
                    "input[accept*='.xlsx']",
                ]:
                    try:
                        file_input = self.driver.find_element(
                            By.CSS_SELECTOR, selector
                        )
                        break
                    except NoSuchElementException:
                        continue

                if not file_input:
                    st.error("❌ Nu găsesc câmpul de upload fișier")
                    return False

                # Upload fișier
                file_input.send_keys(tmp_path)
                time.sleep(2)

                st.info("📤 Fișier CSV atașat, caut butonul de import...")

                # Click pe butonul de import/upload
                submit_selectors = [
                    "button[type='submit']",
                    "input[type='submit']",
                    "button[class*='import']",
                    "button[class*='upload']",
                    "button.btn-primary",
                    "button[class*='submit']",
                ]

                for selector in submit_selectors:
                    try:
                        btn = self.driver.find_element(
                            By.CSS_SELECTOR, selector
                        )
                        if btn.is_displayed():
                            self.driver.execute_script(
                                "arguments[0].click();", btn
                            )
                            time.sleep(10)
                            st.info(
                                "✅ CSV uploadat, aștept procesarea..."
                            )
                            break
                    except NoSuchElementException:
                        continue

                # Verificăm rezultatul
                time.sleep(5)
                page_source = self.driver.page_source.lower()
                if any(
                    msg in page_source
                    for msg in [
                        'success', 'importat', 'imported',
                        'finalizat', 'complete', 'produse adaugate',
                    ]
                ):
                    st.success("✅ Import CSV reușit!")
                    return True
                elif any(
                    msg in page_source
                    for msg in ['error', 'eroare', 'failed', 'eșuat']
                ):
                    st.error("❌ Import CSV eșuat!")
                    return False
                else:
                    st.warning(
                        "⚠️ Status import neclar, verifică manual"
                    )
                    return True

            finally:
                # Ștergem fișierul temporar
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        except Exception as e:
            st.error(f"❌ Eroare upload CSV: {str(e)}")
            return False

    def import_product(
        self,
        product: dict,
        category_id: str = "",
        category_name: str = "",
    ) -> bool:
        """
        Import un singur produs - generează CSV
        și îl uploadează.
        """
        try:
            csv_bytes = self.generate_csv_file(
                [product], category_name
            )
            return self.upload_csv_to_gomag(csv_bytes)
        except Exception as e:
            st.error(f"❌ Eroare import produs: {str(e)}")
            return False

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
