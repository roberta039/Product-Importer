# scrapers/base_scraper.py
"""
Scraper de bază cu Selenium headless + cloudscraper fallback.
"""
import os
import time
import tempfile
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
    TimeoutException, WebDriverException, NoSuchElementException
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
        """Configurează Chrome pentru headless pe Streamlit Cloud."""
        options = Options()
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-infobars')
        options.add_argument('--disable-notifications')
        options.add_argument('--disable-popup-blocking')
        options.add_argument('--window-size=1920,1080')
        options.add_argument(
            '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        )
        options.add_argument('--lang=en-US')
        options.add_argument('--disable-blink-features=AutomationControlled')

        # Streamlit Cloud – Chromium din packages.txt
        if os.path.exists('/usr/bin/chromium'):
            options.binary_location = '/usr/bin/chromium'
        elif os.path.exists('/usr/bin/chromium-browser'):
            options.binary_location = '/usr/bin/chromium-browser'
        elif os.path.exists('/usr/bin/google-chrome'):
            options.binary_location = '/usr/bin/google-chrome'

        return options

    def _init_driver(self):
        """Inițializează Selenium WebDriver."""
        if self.driver:
            return

        try:
            options = self._get_chrome_options()

            # Încercăm chromedriver din sistem
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
                # Fallback: lasă Selenium să găsească singur
                self.driver = webdriver.Chrome(options=options)

            self.driver.set_page_load_timeout(60)
            self.driver.implicitly_wait(10)

        except Exception as e:
            st.warning(f"⚠️ Selenium init failed: {str(e)[:150]}")
            self.driver = None

    def _init_cloudscraper(self):
        """Inițializează cloudscraper ca fallback."""
        if not self.cloud_scraper:
            self.cloud_scraper = cloudscraper.create_scraper(
                browser={
                    'browser': 'chrome',
                    'platform': 'windows',
                    'desktop': True,
                }
            )

    def get_page_selenium(self, url: str, wait_selector: str = None,
                          wait_time: int = 15) -> str | None:
        """
        Obține pagina cu Selenium.
        Returnează HTML-ul paginii sau None.
        """
        self._init_driver()
        if not self.driver:
            return None

        try:
            self.driver.get(url)
            time.sleep(3)  # așteptăm JS

            if wait_selector:
                try:
                    WebDriverWait(self.driver, wait_time).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, wait_selector)
                        )
                    )
                except TimeoutException:
                    st.warning(
                        f"⚠️ Timeout așteptând {wait_selector} pe {url[:60]}"
                    )

            # Scroll down pentru lazy loading
            self.driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight / 2);"
            )
            time.sleep(1)
            self.driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);"
            )
            time.sleep(1)

            return self.driver.page_source

        except Exception as e:
            st.warning(f"⚠️ Selenium error pe {url[:60]}: {str(e)[:100]}")
            return None

    def get_page_cloudscraper(self, url: str) -> str | None:
        """Obține pagina cu cloudscraper (fallback)."""
        self._init_cloudscraper()

        try:
            response = self.cloud_scraper.get(url, timeout=30)
            response.raise_for_status()
            return response.text
        except Exception as e:
            st.warning(
                f"⚠️ Cloudscraper error pe {url[:60]}: {str(e)[:100]}"
            )
            return None

    def get_page(self, url: str, wait_selector: str = None,
                 prefer_selenium: bool = True) -> BeautifulSoup | None:
        """
        Obține și parsează pagina. Încearcă Selenium, apoi cloudscraper.
        """
        html = None

        if prefer_selenium:
            html = self.get_page_selenium(url, wait_selector)

        if not html:
            html = self.get_page_cloudscraper(url)

        if not html:
            st.error(f"❌ Nu pot accesa: {url[:80]}")
            return None

        return BeautifulSoup(html, 'html.parser')

    def scrape(self, url: str) -> dict | None:
        """
        Metodă principală de scraping. De suprascris în subclase.
        Returnează dict cu datele produsului.
        """
        raise NotImplementedError("Subclasele trebuie să implementeze scrape()")

    def _build_product(self, **kwargs) -> dict:
        """Construiește structura standard a unui produs."""
        original_price = kwargs.get('price', 0.0)
        if original_price <= 0:
            original_price = 0.0

        final_price = double_price(original_price)

        return {
            'name': kwargs.get('name', 'Produs Importat'),
            'description': kwargs.get('description', ''),
            'sku': generate_sku(
                kwargs.get('sku', ''), kwargs.get('source_url', '')
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
            'source_site': kwargs.get('source_site', self.name),
            'stock': 1,
            'status': 'scraped',
            'category': kwargs.get('category', ''),
        }

    def close(self):
        """Închide browserul."""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    def __del__(self):
        self.close()
