# scrapers/base_scraper.py
"""
Scraper de bază cu Selenium headless + cloudscraper fallback.
Include metode robuste de extragere descriere și specificații.
"""
import os
import re
import time
import streamlit as st
import cloudscraper
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, WebDriverException,
    NoSuchElementException
)
from utils.helpers import clean_price, double_price, generate_sku
from utils.image_handler import make_absolute_url


class BaseScraper:
    """Clasă de bază pentru toate scraperele."""

    def __init__(self):
        self.driver = None
        self.cloud_scraper = None
        self.name = "base"

    def _get_chrome_options(self) -> Options:
        options = Options()
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-extensions')
        options.add_argument('--window-size=1920,1080')
        options.add_argument(
            '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        )
        options.add_argument('--lang=en-US')
        options.add_argument(
            '--disable-blink-features=AutomationControlled'
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
            self.driver.set_page_load_timeout(60)
            self.driver.implicitly_wait(10)
        except Exception as e:
            st.warning(f"⚠️ Selenium init failed: {str(e)[:150]}")
            self.driver = None

    def _init_cloudscraper(self):
        if not self.cloud_scraper:
            self.cloud_scraper = cloudscraper.create_scraper(
                browser={
                    'browser': 'chrome',
                    'platform': 'windows',
                    'desktop': True,
                }
            )

    def get_page_selenium(
        self, url: str,
        wait_selector: str = None,
        wait_time: int = 15
    ) -> str | None:
        self._init_driver()
        if not self.driver:
            return None
        try:
            self.driver.get(url)
            time.sleep(3)
            if wait_selector:
                try:
                    WebDriverWait(self.driver, wait_time).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, wait_selector)
                        )
                    )
                except TimeoutException:
                    pass

            # Scroll complet pentru lazy loading
            for pos in ['document.body.scrollHeight/3',
                        'document.body.scrollHeight/2',
                        'document.body.scrollHeight',
                        '0']:
                self.driver.execute_script(
                    f"window.scrollTo(0, {pos});"
                )
                time.sleep(0.8)

            # Click pe tab-uri de descriere/specificații
            self._click_description_tabs()

            time.sleep(1)
            return self.driver.page_source
        except Exception as e:
            st.warning(
                f"⚠️ Selenium error: {str(e)[:100]}"
            )
            return None

    def _click_description_tabs(self):
        """
        Click pe tab-uri de descriere/specificații
        care ascund conținutul.
        """
        if not self.driver:
            return

        tab_selectors = [
            # Tab-uri comune
            "a[href*='description']",
            "a[href*='specification']",
            "a[href*='details']",
            "a[href*='features']",
            "a[href*='info']",
            "button[data-target*='description']",
            "button[data-target*='specification']",
            "button[data-target*='details']",
            # Tab-uri cu text
            "[class*='tab'] a",
            "[class*='tab'] button",
            "[role='tab']",
            ".nav-tabs a",
            ".nav-tabs li a",
            ".tab-nav a",
            # Accordion
            "[class*='accordion'] button",
            "[class*='accordion'] a",
            "[class*='collapse'] button",
            "details summary",
        ]

        for selector in tab_selectors:
            try:
                elements = self.driver.find_elements(
                    By.CSS_SELECTOR, selector
                )
                for el in elements:
                    try:
                        text = el.text.lower().strip()
                        if any(
                            kw in text
                            for kw in [
                                'descri', 'specifi', 'detail',
                                'feature', 'info', 'propert',
                                'about', 'overview',
                                'caracterist', 'detalii',
                            ]
                        ):
                            if el.is_displayed():
                                self.driver.execute_script(
                                    "arguments[0].click();", el
                                )
                                time.sleep(1)
                    except Exception:
                        continue
            except Exception:
                continue

    def get_page_cloudscraper(self, url: str) -> str | None:
        self._init_cloudscraper()
        try:
            response = self.cloud_scraper.get(url, timeout=30)
            response.raise_for_status()
            return response.text
        except Exception as e:
            st.warning(
                f"⚠️ Cloudscraper error: {str(e)[:100]}"
            )
            return None

    def get_page(
        self, url: str,
        wait_selector: str = None,
        prefer_selenium: bool = True
    ) -> BeautifulSoup | None:
        html = None
        if prefer_selenium:
            html = self.get_page_selenium(url, wait_selector)
        if not html:
            html = self.get_page_cloudscraper(url)
        if not html:
            st.error(f"❌ Nu pot accesa: {url[:80]}")
            return None
        return BeautifulSoup(html, 'html.parser')

    # ══════════════════════════════════════════
    # METODE ROBUSTE DE EXTRAGERE
    # ══════════════════════════════════════════

    def extract_description(
        self, soup: BeautifulSoup, page_source: str = ""
    ) -> str:
        """
        Extrage descrierea produsului folosind
        multiple strategii.
        """
        description = ""

        # Strategia 1: Selectori CSS specifici
        desc_selectors = [
            '.product-detail-description',
            '.product-description',
            '#product-description',
            '#description',
            '[class*="description"]',
            '.product-detail-body',
            '.product-info-description',
            '.product-details',
            '.product-detail-text',
            '.product-text',
            '.description-content',
            '.tab-pane.active',
            '#tab-description',
            '[data-tab="description"]',
            '.product-detail__description',
            '.product__description',
            'article .content',
            '.product-info .content',
        ]

        for sel in desc_selectors:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(strip=True)
                if text and len(text) > 20:
                    description = str(el)
                    break

        # Strategia 2: Meta description
        if not description or len(description) < 30:
            meta = soup.select_one(
                'meta[name="description"]'
            )
            if meta:
                content = meta.get('content', '')
                if content and len(content) > 20:
                    description = f"<p>{content}</p>"

        # Strategia 3: Paragrafele după h1
        if not description or len(description) < 30:
            h1 = soup.select_one('h1')
            if h1:
                parent = h1.parent
                if parent:
                    paragraphs = parent.find_all_next(
                        'p', limit=5
                    )
                    texts = []
                    for p in paragraphs:
                        t = p.get_text(strip=True)
                        if t and len(t) > 15:
                            texts.append(str(p))
                    if texts:
                        description = "\n".join(texts)

        # Strategia 4: Orice div mare cu text
        if not description or len(description) < 30:
            divs = soup.select('div, section, article')
            best_div = ""
            best_len = 0
            for div in divs:
                text = div.get_text(strip=True)
                # Excludem navigația, header, footer
                classes = ' '.join(
                    div.get('class', [])
                ).lower()
                div_id = (div.get('id', '') or '').lower()
                if any(
                    skip in classes or skip in div_id
                    for skip in [
                        'nav', 'header', 'footer', 'menu',
                        'sidebar', 'cookie', 'cart', 'login',
                        'search', 'filter',
                    ]
                ):
                    continue
                if (
                    50 < len(text) < 2000
                    and len(text) > best_len
                ):
                    best_div = str(div)
                    best_len = len(text)

            if best_len > 50:
                description = best_div

        # Strategia 5: Selenium - text vizibil pe pagină
        if (
            (not description or len(description) < 30)
            and self.driver
        ):
            try:
                desc_text = self.driver.execute_script("""
                    var result = '';

                    // Căutăm secțiuni cu text lung
                    var selectors = [
                        '[class*="description"]',
                        '[class*="detail"]',
                        '[class*="info"]',
                        '[class*="content"]',
                        'article', '.content',
                    ];

                    for (var i = 0; i < selectors.length; i++) {
                        var els = document.querySelectorAll(
                            selectors[i]
                        );
                        for (var j = 0; j < els.length; j++) {
                            var text = els[j].innerText.trim();
                            if (text.length > 50 &&
                                text.length > result.length &&
                                text.length < 3000) {
                                result = text;
                            }
                        }
                        if (result.length > 100) break;
                    }

                    return result;
                """)

                if desc_text and len(desc_text) > 30:
                    description = f"<p>{desc_text}</p>"

            except Exception:
                pass

        return description

    def extract_specifications(
        self, soup: BeautifulSoup, page_source: str = ""
    ) -> dict:
        """
        Extrage specificațiile produsului folosind
        multiple strategii.
        """
        specifications = {}

        # Strategia 1: Tabele
        table_selectors = [
            '.product-detail-properties table',
            '.product-properties table',
            '.product-specifications table',
            '.specifications table',
            '#specifications table',
            '[class*="specification"] table',
            '[class*="properties"] table',
            '[class*="features"] table',
            '[class*="detail"] table',
            '.product-attributes table',
            '.product-info table',
            'table.table',
            'table',
        ]

        for sel in table_selectors:
            tables = soup.select(sel)
            for table in tables:
                rows = table.select('tr')
                for row in rows:
                    cells = row.select('td, th')
                    if len(cells) >= 2:
                        key = cells[0].get_text(strip=True)
                        val = cells[1].get_text(strip=True)
                        if (
                            key and val
                            and len(key) < 50
                            and len(val) < 200
                            and key.lower() not in [
                                'quantity', 'cantitate',
                                'printed', 'price', 'pret',
                            ]
                        ):
                            specifications[key] = val
                if specifications:
                    break
            if specifications:
                break

        # Strategia 2: Definition Lists (dl/dt/dd)
        if not specifications:
            dl_selectors = [
                '.product-detail-properties dl',
                '.product-properties dl',
                '.specifications dl',
                '[class*="specification"] dl',
                '[class*="properties"] dl',
                'dl',
            ]
            for sel in dl_selectors:
                dls = soup.select(sel)
                for dl in dls:
                    dts = dl.select('dt')
                    dds = dl.select('dd')
                    for dt, dd in zip(dts, dds):
                        key = dt.get_text(strip=True)
                        val = dd.get_text(strip=True)
                        if (
                            key and val
                            and len(key) < 50
                        ):
                            specifications[key] = val
                    if specifications:
                        break
                if specifications:
                    break

        # Strategia 3: Liste cu format "Key: Value"
        if not specifications:
            list_selectors = [
                '.product-detail-properties li',
                '.product-properties li',
                '.specifications li',
                '[class*="specification"] li',
                '[class*="properties"] li',
                '[class*="features"] li',
                '.product-info li',
                'ul li',
            ]
            for sel in list_selectors:
                items = soup.select(sel)
                found_specs = {}
                for item in items:
                    text = item.get_text(strip=True)
                    if ':' in text:
                        parts = text.split(':', 1)
                        key = parts[0].strip()
                        val = parts[1].strip()
                        if (
                            key and val
                            and len(key) < 50
                            and len(val) < 200
                        ):
                            found_specs[key] = val
                    elif '•' in text or '●' in text:
                        # Bullet points
                        clean = text.replace(
                            '•', ''
                        ).replace('●', '').strip()
                        if clean and len(clean) > 5:
                            found_specs[
                                f"Caracteristică {len(found_specs)+1}"
                            ] = clean

                if len(found_specs) >= 2:
                    specifications = found_specs
                    break

        # Strategia 4: Div-uri cu perechi key-value
        if not specifications:
            pair_selectors = [
                '.product-detail-properties .row',
                '.product-properties .row',
                '[class*="spec"] .row',
                '[class*="property"]',
                '[class*="attribute"]',
                '.feature-row',
                '.spec-row',
            ]
            for sel in pair_selectors:
                pairs = soup.select(sel)
                for pair in pairs:
                    children = pair.select(
                        'span, div, label, strong, p'
                    )
                    if len(children) >= 2:
                        key = children[0].get_text(strip=True)
                        val = children[1].get_text(strip=True)
                        if (
                            key and val
                            and len(key) < 50
                        ):
                            specifications[key] = val
                if specifications:
                    break

        # Strategia 5: Selenium - text din elemente ascunse
        if not specifications and self.driver:
            try:
                js_specs = self.driver.execute_script("""
                    var specs = {};

                    // Căutăm tabele
                    var tables = document.querySelectorAll(
                        'table'
                    );
                    for (var t = 0; t < tables.length; t++) {
                        var rows = tables[t].querySelectorAll('tr');
                        for (var r = 0; r < rows.length; r++) {
                            var cells = rows[r]
                                .querySelectorAll('td, th');
                            if (cells.length >= 2) {
                                var key = cells[0]
                                    .innerText.trim();
                                var val = cells[1]
                                    .innerText.trim();
                                if (key && val &&
                                    key.length < 50 &&
                                    val.length < 200) {
                                    specs[key] = val;
                                }
                            }
                        }
                        if (Object.keys(specs).length > 0) break;
                    }

                    // Fallback: dt/dd
                    if (Object.keys(specs).length === 0) {
                        var dts = document.querySelectorAll('dt');
                        var dds = document.querySelectorAll('dd');
                        for (var i = 0;
                             i < Math.min(dts.length, dds.length);
                             i++) {
                            var k = dts[i].innerText.trim();
                            var v = dds[i].innerText.trim();
                            if (k && v) specs[k] = v;
                        }
                    }

                    // Fallback: li cu ":"
                    if (Object.keys(specs).length === 0) {
                        var lis = document.querySelectorAll('li');
                        for (var i = 0; i < lis.length; i++) {
                            var txt = lis[i].innerText.trim();
                            if (txt.indexOf(':') > 0) {
                                var parts = txt.split(':');
                                var k = parts[0].trim();
                                var v = parts.slice(1)
                                    .join(':').trim();
                                if (k && v && k.length < 50) {
                                    specs[k] = v;
                                }
                            }
                        }
                    }

                    return specs;
                """)

                if js_specs and isinstance(js_specs, dict):
                    specifications = js_specs

            except Exception:
                pass

        # Strategia 6: Regex pe page source
        if not specifications and page_source:
            # Căutăm pattern-uri "Key: Value" sau "Key - Value"
            patterns = re.findall(
                r'(?:^|\n)\s*([A-Z][a-zA-ZăîșțâÎȘȚ\s]{2,30})'
                r'\s*[:|-]\s*(.{3,100})',
                page_source
            )
            for key, val in patterns[:10]:
                key = key.strip()
                val = val.strip()
                if (
                    key and val
                    and len(key) < 40
                    and not any(
                        skip in key.lower()
                        for skip in [
                            'http', 'www', 'script',
                            'function', 'var ',
                        ]
                    )
                ):
                    specifications[key] = val

        return specifications

    def scrape(self, url: str) -> dict | None:
        raise NotImplementedError

    def _build_product(self, **kwargs) -> dict:
        original_price = kwargs.get('price', 0.0)
        if original_price <= 0:
            original_price = 0.0
        final_price = double_price(original_price)

        return {
            'name': kwargs.get('name', 'Produs Importat'),
            'description': kwargs.get('description', ''),
            'sku': generate_sku(
                kwargs.get('sku', ''),
                kwargs.get('source_url', '')
            ),
            'original_price': original_price,
            'final_price': final_price,
            'currency': kwargs.get('currency', 'EUR'),
            'images': kwargs.get('images', []),
            'colors': kwargs.get('colors', []),
            'sizes': kwargs.get('sizes', []),
            'specifications': kwargs.get('specifications', {}),
            'material': kwargs.get('material', ''),
            'weight': kwargs.get('weight', ''),
            'dimensions': kwargs.get('dimensions', ''),
            'source_url': kwargs.get('source_url', ''),
            'source_site': kwargs.get(
                'source_site', self.name
            ),
            'stock': 1,
            'status': 'scraped',
            'category': kwargs.get('category', ''),
        }

    def close(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    def __del__(self):
        self.close()
