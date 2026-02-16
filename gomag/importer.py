# gomag/importer.py
"""
Modul pentru import produse în Gomag.ro
- Generare CSV/Excel compatibil
- Upload automat prin Selenium la:
  /gomag/product/import/add
"""
import os
import io
import re
import time
import csv
import tempfile
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
            self.driver.set_page_load_timeout(120)
            self.driver.implicitly_wait(10)
        except Exception as e:
            st.error(f"❌ Nu pot inițializa browser: {str(e)}")
            self.driver = None

    def _save_screenshot(self, name: str):
        """Screenshot debug."""
        if not self.driver:
            return
        try:
            screenshot = self.driver.get_screenshot_as_png()
            st.image(
                screenshot,
                caption=f"🖥️ Gomag: {name}",
                width=700
            )
        except Exception:
            pass

    def login(self) -> bool:
        if self.logged_in:
            return True
        config = self._get_config()
        if not config['username'] or not config['password']:
            st.error("❌ Credențiale Gomag lipsă!")
            return False
        self._init_driver()
        if not self.driver:
            return False
        try:
            self.base_url = config['base_url'].rstrip('/')
            login_url = f"{self.base_url}/gomag/login"
            st.info("🔐 Mă conectez la Gomag...")
            self.driver.get(login_url)
            time.sleep(4)

            # Email
            email_field = None
            for sel in [
                "input[name='email']",
                "input[name='username']",
                "input[type='email']",
                "input[type='text']",
            ]:
                try:
                    f = self.driver.find_element(
                        By.CSS_SELECTOR, sel
                    )
                    if f.is_displayed():
                        email_field = f
                        break
                except NoSuchElementException:
                    continue

            if not email_field:
                st.error("❌ Nu găsesc câmpul email Gomag")
                self._save_screenshot("login_no_email")
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
                st.error("❌ Nu găsesc câmpul parolă Gomag")
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

            cur = self.driver.current_url
            if (
                'dashboard' in cur
                or 'admin' in cur
                or 'login' not in cur
            ):
                self.logged_in = True
                st.success("✅ Conectat la Gomag!")
                return True

            st.error("❌ Login Gomag eșuat")
            self._save_screenshot("login_failed")
            return False

        except Exception as e:
            st.error(f"❌ Eroare login Gomag: {str(e)}")
            return False

    def get_categories(self) -> list:
        if self.categories_cache:
            return self.categories_cache
        if not self.logged_in:
            if not self.login():
                return []
        try:
            self.driver.get(f"{self.base_url}/gomag/categories")
            time.sleep(4)
            categories = []
            try:
                rows = self.driver.find_elements(
                    By.CSS_SELECTOR, "table tbody tr"
                )
                for row in rows:
                    try:
                        el = row.find_element(
                            By.CSS_SELECTOR, "td a, td:first-child"
                        )
                        cat_name = el.text.strip()
                        cat_href = el.get_attribute('href') or ''
                        cat_id = ""
                        m = re.search(r'/(\d+)', cat_href)
                        if m:
                            cat_id = m.group(1)
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
            self.categories_cache = categories
            return categories
        except Exception as e:
            st.error(f"❌ Eroare categorii: {str(e)}")
            return []

    # ══════════════════════════════════════════
    # CONSTRUCȚIE DESCRIERE PRODUS
    # ══════════════════════════════════════════

    def _build_full_description(self, product: dict) -> str:
        """Construiește descriere completă HTML."""
        parts = []

        raw_desc = product.get('description', '')
        if raw_desc:
            clean = re.sub(r'<[^>]+>', ' ', raw_desc)
            clean = re.sub(r'\s+', ' ', clean).strip()
            if clean and len(clean) > 10:
                parts.append(f"<p>{clean}</p>")

        specs = product.get('specifications', {})
        if specs:
            parts.append("<h3>Specificații</h3>")
            parts.append("<ul>")
            for key, val in specs.items():
                if key and val:
                    parts.append(
                        f"<li><strong>{key}:</strong> {val}</li>"
                    )
            parts.append("</ul>")

        if product.get('material'):
            parts.append(
                f"<p><strong>Material:</strong> "
                f"{product['material']}</p>"
            )
        if product.get('dimensions'):
            parts.append(
                f"<p><strong>Dimensiuni:</strong> "
                f"{product['dimensions']}</p>"
            )
        if product.get('weight'):
            parts.append(
                f"<p><strong>Greutate:</strong> "
                f"{product['weight']}</p>"
            )

        colors = product.get('colors', [])
        if colors:
            parts.append(
                f"<p><strong>Culori disponibile:</strong> "
                f"{', '.join(colors)}</p>"
            )

        if not parts:
            name = product.get('name', 'Produs importat')
            parts.append(
                f"<p>{name}. Produs de calitate superioară, "
                f"ideal pentru protecția bunurilor personale.</p>"
            )

        return "\n".join(parts)

    def _build_short_description(self, product: dict) -> str:
        """Construiește descriere scurtă (max 250 car)."""
        parts = []

        raw_desc = product.get('description', '')
        if raw_desc:
            clean = re.sub(r'<[^>]+>', ' ', raw_desc)
            clean = re.sub(r'\s+', ' ', clean).strip()
            if clean and len(clean) > 10:
                first = clean.split('.')[0]
                if len(first) > 20:
                    parts.append(first.strip() + '.')

        specs = product.get('specifications', {})
        if specs and not parts:
            sp = []
            for k, v in list(specs.items())[:4]:
                sp.append(f"{k}: {v}")
            parts.append(" | ".join(sp))

        if product.get('material') and not parts:
            parts.append(f"Material: {product['material']}")

        colors = product.get('colors', [])
        if colors:
            parts.append(
                f"Disponibil în {len(colors)} culori: "
                f"{', '.join(colors[:3])}"
                + ("..." if len(colors) > 3 else "")
            )

        if not parts:
            name = product.get('name', 'Produs importat')
            parts.append(
                f"{name} - produs cu protecție anti-furt."
            )

        return " | ".join(parts)[:250]

    def _build_feed_description(self, product: dict) -> str:
        """Descriere feed-uri (max 200 car)."""
        name = product.get('name', '')
        colors = product.get('colors', [])
        specs = product.get('specifications', {})
        parts = [name]
        if colors:
            parts.append(f"Culori: {', '.join(colors[:3])}")
        for k, v in list(specs.items())[:2]:
            parts.append(f"{k}: {v}")
        return ". ".join(parts)[:200]

    # ══════════════════════════════════════════
    # GENERARE CSV/EXCEL COMPATIBIL GOMAG
    # ══════════════════════════════════════════

    def generate_gomag_csv(
        self, products: list,
        category_name: str = "", brand: str = "",
    ) -> pd.DataFrame:
        rows = []
        for product in products:
            row = self._product_to_gomag_row(
                product, category_name, brand
            )
            rows.append(row)
        return pd.DataFrame(rows, columns=self.GOMAG_COLUMNS)

    def _product_to_gomag_row(
        self, product: dict,
        category_name: str = "", brand: str = "",
    ) -> list:
        sku = product.get('sku', '')
        name = product.get('name', 'Produs Importat')
        description = self._build_full_description(product)
        short_desc = self._build_short_description(product)
        feed_desc = self._build_feed_description(product)

        images = product.get('images', [])
        images_url = '|'.join(images[:10]) if images else ''

        colors = product.get('colors', [])
        colors_str = ','.join(colors) if colors else ''

        price = product.get('final_price', 1.0)
        if price <= 0:
            price = 1.0
        price_str = f"{price:.2f}"

        buy_price = product.get('original_price', 0)
        buy_price_str = (
            f"{buy_price:.2f}" if buy_price > 0 else ""
        )

        weight = product.get('weight', '')
        weight_str = ""
        if weight:
            wm = re.search(r'([\d.]+)', str(weight))
            if wm:
                weight_str = wm.group(1)

        kw_parts = [name.lower().replace('-', ' ')]
        if 'anti' in name.lower():
            kw_parts.extend(["anti-furt", "anti-theft"])
        if (
            'rucsac' in name.lower()
            or 'backpack' in name.lower()
        ):
            kw_parts.extend(["rucsac", "ghiozdan"])
        kw_parts.extend(["protectie", "siguranta"])
        if colors:
            kw_parts.extend(colors[:3])
        keywords = ", ".join(kw_parts)

        meta_desc = (
            short_desc[:160] if short_desc else name[:160]
        )

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

        return [
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
            feed_desc,                      # Descriere pt feed-uri
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

    def generate_csv_file(
        self, products: list,
        category_name: str = "", brand: str = "",
    ) -> bytes:
        df = self.generate_gomag_csv(
            products, category_name, brand
        )
        output = io.StringIO()
        df.to_csv(
            output, index=False, sep=',',
            quoting=csv.QUOTE_ALL, encoding='utf-8',
        )
        return ('\ufeff' + output.getvalue()).encode('utf-8')

    def generate_excel_file(
        self, products: list,
        category_name: str = "", brand: str = "",
    ) -> bytes:
        df = self.generate_gomag_csv(
            products, category_name, brand
        )
        buf = io.BytesIO()
        df.to_excel(buf, index=False, engine='openpyxl')
        buf.seek(0)
        return buf.getvalue()

    # ══════════════════════════════════════════
    # UPLOAD AUTOMAT ÎN GOMAG
    # URL: /gomag/product/import/add
    # ══════════════════════════════════════════

    def upload_csv_to_gomag(self, csv_bytes: bytes) -> bool:
        """
        Upload automat CSV în Gomag.
        Pagina: /gomag/product/import/add
        1. Selectează fișier
        2. Corelează coloanele automat (prima linie = header)
        3. Click Start Import
        """
        if not self.logged_in:
            if not self.login():
                return False

        try:
            # ═══ PASUL 1: Navigăm la pagina de import ═══
            import_url = (
                f"{self.base_url}/gomag/product/import/add"
            )
            st.info(f"📤 Gomag: Navighez la {import_url}")
            self.driver.get(import_url)
            time.sleep(4)

            # Verificăm că suntem pe pagina corectă
            cur_url = self.driver.current_url.lower()
            if 'login' in cur_url:
                st.error(
                    "❌ Sesiunea a expirat, reloghez..."
                )
                self.logged_in = False
                if not self.login():
                    return False
                self.driver.get(import_url)
                time.sleep(4)

            self._save_screenshot("1_pagina_import")

            # ═══ PASUL 2: Salvăm fișierul temporar (.xlsx) ═══
            # Gomag acceptă XLS, XLSX, TSV
            # Generăm Excel în loc de CSV
            tmp = tempfile.NamedTemporaryFile(
                suffix='.xlsx', delete=False, mode='wb'
            )
            tmp.write(csv_bytes)
            tmp.close()
            tmp_path = tmp.name

            # Regenerăm ca Excel dacă am primit CSV
            if csv_bytes[:3] == b'\xef\xbb\xbf':
                # E CSV cu BOM, convertim la Excel
                try:
                    csv_str = csv_bytes.decode('utf-8-sig')
                    df_tmp = pd.read_csv(
                        io.StringIO(csv_str), encoding='utf-8'
                    )
                    excel_buf = io.BytesIO()
                    df_tmp.to_excel(
                        excel_buf, index=False, engine='openpyxl'
                    )
                    excel_buf.seek(0)

                    # Rescriem fișierul temporar
                    with open(tmp_path, 'wb') as f:
                        f.write(excel_buf.getvalue())

                    st.info("📄 Fișier convertit la Excel (.xlsx)")
                except Exception as e:
                    st.warning(
                        f"⚠️ Nu am putut converti la Excel: "
                        f"{str(e)[:50]}"
                    )

            try:
                # ═══ PASUL 3: Găsim input file ═══
                file_input = None
                for sel in [
                    "input[type='file']",
                    "input[name='file']",
                    "input[name='import_file']",
                    "input[name='importFile']",
                    "input[accept*='.xls']",
                    "input[accept*='.xlsx']",
                    "input[accept*='.csv']",
                    "input[accept*='.tsv']",
                ]:
                    try:
                        fi = self.driver.find_element(
                            By.CSS_SELECTOR, sel
                        )
                        file_input = fi
                        st.info(f"✅ Input file găsit: [{sel}]")
                        break
                    except NoSuchElementException:
                        continue

                if not file_input:
                    # Fallback: orice input file
                    try:
                        file_input = self.driver.find_element(
                            By.CSS_SELECTOR, "input[type='file']"
                        )
                    except NoSuchElementException:
                        st.error(
                            "❌ Nu găsesc câmpul de upload fișier!"
                        )
                        self._save_screenshot("ERROR_no_file_input")
                        return False

                # ═══ PASUL 4: Upload fișier ═══
                file_input.send_keys(tmp_path)
                time.sleep(3)
                st.info("📤 Fișier atașat, aștept procesarea...")

                # ═══ PASUL 5: Click Selectează Fișier (dacă e nevoie) ═══
                select_btns = [
                    "button[class*='select']",
                    "button[class*='upload']",
                    "input[value*='Selecteaza']",
                    "input[value*='Select']",
                    "button:contains('Selecteaza')",
                ]
                for sel in select_btns:
                    try:
                        btn = self.driver.find_element(
                            By.CSS_SELECTOR, sel
                        )
                        if btn.is_displayed():
                            self.driver.execute_script(
                                "arguments[0].click();", btn
                            )
                            time.sleep(3)
                            st.info("✅ Click pe Selectează Fișier")
                            break
                    except NoSuchElementException:
                        continue

                # Căutăm butonul prin XPath
                try:
                    btns = self.driver.find_elements(
                        By.XPATH,
                        "//button[contains(text(), 'Selecteaza')] | "
                        "//input[@value='Selecteaza Fisier'] | "
                        "//button[contains(text(), 'Select')]"
                    )
                    for btn in btns:
                        if btn.is_displayed():
                            self.driver.execute_script(
                                "arguments[0].click();", btn
                            )
                            time.sleep(3)
                            st.info(
                                "✅ Click Selectează (XPath)"
                            )
                            break
                except Exception:
                    pass

                time.sleep(3)
                self._save_screenshot("2_dupa_upload_fisier")

                # ═══ PASUL 6: Așteptăm tabelul de mapare ═══
                # Gomag arată un tabel cu coloanele detectate
                # și dropdown-uri pentru a le mapa
                st.info(
                    "⏳ Aștept detectarea coloanelor..."
                )

                # Așteptăm până apare tabelul sau selecturile
                max_wait = 30
                table_found = False
                for _ in range(max_wait):
                    try:
                        selects = self.driver.find_elements(
                            By.CSS_SELECTOR, "select"
                        )
                        visible_selects = [
                            s for s in selects
                            if s.is_displayed()
                        ]
                        if len(visible_selects) >= 3:
                            table_found = True
                            st.info(
                                f"✅ {len(visible_selects)} "
                                f"selecturi de mapare detectate"
                            )
                            break
                    except Exception:
                        pass
                    time.sleep(1)

                if not table_found:
                    st.warning(
                        "⚠️ Nu am detectat selecturi de mapare. "
                        "Posibil corelarea automată e activă."
                    )

                self._save_screenshot("3_mapare_coloane")

                # ═══ PASUL 7: Bifăm opțiunile corecte ═══

                # Checkbox: "Salvează corelarea ca template"
                try:
                    checkboxes = self.driver.find_elements(
                        By.CSS_SELECTOR, "input[type='checkbox']"
                    )
                    for cb in checkboxes:
                        try:
                            label = self.driver.find_element(
                                By.CSS_SELECTOR,
                                f"label[for='{cb.get_attribute('id')}']"
                            )
                            label_text = label.text.lower()

                            # Bifăm "Ignora prima linie"
                            if (
                                'ignora' in label_text
                                or 'prima' in label_text
                                or 'first' in label_text
                                or 'header' in label_text
                            ):
                                if not cb.is_selected():
                                    self.driver.execute_script(
                                        "arguments[0].click();", cb
                                    )
                                    st.info(
                                        "✅ Bifat: Ignoră prima linie"
                                    )
                        except Exception:
                            continue
                except Exception:
                    pass

                # ═══ PASUL 8: Click Start Import ═══
                st.info("🚀 Caut butonul Start Import...")
                time.sleep(2)

                import_clicked = False

                # Metoda 1: Buton cu text "Start Import"
                try:
                    btns = self.driver.find_elements(
                        By.XPATH,
                        "//button[contains(text(), 'Start Import')] | "
                        "//input[@value='Start Import'] | "
                        "//a[contains(text(), 'Start Import')] | "
                        "//button[contains(text(), 'Import')] | "
                        "//button[contains(text(), 'Importa')]"
                    )
                    for btn in btns:
                        if btn.is_displayed():
                            self.driver.execute_script(
                                "arguments[0].scrollIntoView("
                                "{block: 'center'});",
                                btn
                            )
                            time.sleep(0.5)
                            self.driver.execute_script(
                                "arguments[0].click();", btn
                            )
                            import_clicked = True
                            st.info(
                                f"✅ Click pe: {btn.text.strip()}"
                            )
                            break
                except Exception:
                    pass

                # Metoda 2: CSS selectori
                if not import_clicked:
                    for sel in [
                        "button[type='submit']",
                        "input[type='submit']",
                        "button.btn-primary",
                        "button.btn-success",
                        "button[class*='import']",
                        "button[class*='start']",
                        "#startImport",
                        ".start-import",
                    ]:
                        try:
                            btn = self.driver.find_element(
                                By.CSS_SELECTOR, sel
                            )
                            if btn.is_displayed():
                                btn_text = btn.text.strip()
                                if (
                                    'import' in btn_text.lower()
                                    or 'start' in btn_text.lower()
                                    or not btn_text
                                ):
                                    self.driver.execute_script(
                                        "arguments[0].click();", btn
                                    )
                                    import_clicked = True
                                    st.info(
                                        f"✅ Click pe: "
                                        f"[{sel}] '{btn_text}'"
                                    )
                                    break
                        except NoSuchElementException:
                            continue

                if not import_clicked:
                    st.error(
                        "❌ Nu am găsit butonul Start Import!"
                    )
                    self._save_screenshot("ERROR_no_start_import")
                    return False

                # ═══ PASUL 9: Așteptăm finalizarea ═══
                st.info("⏳ Import în curs, aștept finalizarea...")

                # Așteptăm până la 120 secunde
                for wait_sec in range(0, 120, 5):
                    time.sleep(5)
                    try:
                        page = self.driver.page_source.lower()
                        cur = self.driver.current_url.lower()

                        # Verificăm succes
                        if any(
                            msg in page
                            for msg in [
                                'import finalizat',
                                'import complet',
                                'importul a fost finalizat',
                                'produse importate',
                                'import successful',
                                'successfully imported',
                                'produse adaugate',
                            ]
                        ):
                            st.success(
                                "✅ Import finalizat cu succes!"
                            )
                            self._save_screenshot(
                                "SUCCESS_import"
                            )
                            return True

                        # Verificăm eroare
                        if any(
                            msg in page
                            for msg in [
                                'eroare import',
                                'import error',
                                'import failed',
                                'eroare la import',
                            ]
                        ):
                            st.error("❌ Eroare la import!")
                            self._save_screenshot(
                                "ERROR_import"
                            )
                            return False

                        # Verificăm dacă pagina s-a schimbat
                        # (redirect după import)
                        if (
                            'import' not in cur
                            and 'product' in cur
                        ):
                            st.success(
                                "✅ Import probabil reușit "
                                "(redirect detectat)"
                            )
                            self._save_screenshot(
                                "REDIRECT_after_import"
                            )
                            return True

                    except Exception:
                        pass

                    if wait_sec % 15 == 0 and wait_sec > 0:
                        st.info(
                            f"⏳ Încă aștept... "
                            f"({wait_sec}s)"
                        )

                # Timeout
                st.warning(
                    "⚠️ Timeout așteptare import (120s). "
                    "Verifică manual în Gomag."
                )
                self._save_screenshot("TIMEOUT_import")
                return True

            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        except Exception as e:
            st.error(f"❌ Eroare upload: {str(e)}")
            self._save_screenshot("ERROR_upload")
            return False

    def import_product(
        self, product: dict,
        category_id: str = "",
        category_name: str = "",
    ) -> bool:
        try:
            csv_bytes = self.generate_csv_file(
                [product], category_name
            )
            return self.upload_csv_to_gomag(csv_bytes)
        except Exception as e:
            st.error(f"❌ Eroare import: {str(e)}")
            return False

    def close(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
        self.logged_in = False

    def __del__(self):
        self.close()
