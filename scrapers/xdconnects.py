# scrapers/xdconnects.py
"""
Scraper pentru xdconnects.com (Bobby, Swiss Peak, Urban, etc.)
Imagini: de pe pagina /en-gb/imgdtbs?productId=X&variantId=Y
Rezoluție: 96 dpi, 1024x1024 px
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
)


class XDConnectsScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.name = "xdconnects"
        self.base_url = "https://www.xdconnects.com"
        self._logged_in = False

    def _dismiss_cookie_banner(self):
        """Închide cookie banner (Cookiebot)."""
        if not self.driver:
            return
        for selector in [
            "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
            "#CybotCookiebotDialogBodyButtonAccept",
        ]:
            try:
                btn = self.driver.find_element(
                    By.CSS_SELECTOR, selector
                )
                if btn.is_displayed():
                    self.driver.execute_script(
                        "arguments[0].click();", btn
                    )
                    time.sleep(2)
                    st.info("🍪 XD: Cookie banner închis")
                    return
            except NoSuchElementException:
                continue
        try:
            self.driver.execute_script("""
                ['#CybotCookiebotDialog',
                 '#CybotCookiebotDialogBodyUnderlay'
                ].forEach(function(s) {
                    document.querySelectorAll(s).forEach(function(el) {
                        el.remove();
                    });
                });
                document.body.style.overflow = 'auto';
            """)
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

            st.info("🔐 XD: Mă conectez...")
            self.driver.get(
                f"{self.base_url}/en-gb/profile/login"
            )
            time.sleep(5)

            self._dismiss_cookie_banner()
            time.sleep(1)

            # Email
            email_field = None
            for selector in [
                "input[type='email'][name='email']",
                "input[name='email']",
                "input[type='email']",
            ]:
                try:
                    for field in self.driver.find_elements(
                        By.CSS_SELECTOR, selector
                    ):
                        if field.is_displayed() and field.is_enabled():
                            email_field = field
                            break
                    if email_field:
                        break
                except Exception:
                    continue

            if not email_field:
                st.error("❌ XD: Nu găsesc câmpul de email!")
                return

            self.driver.execute_script(
                "arguments[0].focus();", email_field
            )
            email_field.clear()
            email_field.send_keys(Keys.CONTROL, 'a')
            email_field.send_keys(Keys.DELETE)
            email_field.send_keys(xd_user)
            time.sleep(0.5)

            # Parolă
            pass_field = None
            for field in self.driver.find_elements(
                By.CSS_SELECTOR, "input[type='password']"
            ):
                if field.is_displayed() and field.is_enabled():
                    pass_field = field
                    break

            if not pass_field:
                st.error("❌ XD: Nu găsesc câmpul de parolă!")
                return

            self.driver.execute_script(
                "arguments[0].focus();", pass_field
            )
            pass_field.clear()
            pass_field.send_keys(Keys.CONTROL, 'a')
            pass_field.send_keys(Keys.DELETE)
            pass_field.send_keys(xd_pass)
            time.sleep(0.5)

            # Submit
            self._dismiss_cookie_banner()
            submitted = False
            for selector in [
                "form button[type='submit']",
                "button[type='submit']",
            ]:
                try:
                    for btn in self.driver.find_elements(
                        By.CSS_SELECTOR, selector
                    ):
                        if btn.is_displayed():
                            self.driver.execute_script(
                                "arguments[0].click();", btn
                            )
                            submitted = True
                            break
                    if submitted:
                        break
                except Exception:
                    continue

            if not submitted:
                pass_field.send_keys(Keys.RETURN)

            time.sleep(6)

            page_source = self.driver.page_source.lower()
            if (
                'logout' in page_source
                or 'account' in page_source
            ):
                self._logged_in = True
                st.success("✅ XD: Login reușit!")
            else:
                st.warning("⚠️ XD: Status login neclar, continui...")
                self._logged_in = True

        except Exception as e:
            st.error(f"❌ XD login error: {str(e)[:150]}")

    def _extract_product_variant_ids(self, url: str) -> tuple:
        """
        Extrage productId și variantId din URL.
        URL format: .../bobby-hero-small-...p705.70?variantId=P705.709
        productId = P705.70
        variantId = P705.709
        """
        product_id = ""
        variant_id = ""

        # variantId din query string
        variant_match = re.search(
            r'variantId=([A-Z0-9.]+)', url, re.IGNORECASE
        )
        if variant_match:
            variant_id = variant_match.group(1).upper()

        # productId din URL path (ex: p705.70)
        product_match = re.search(
            r'([pP]\d{3}\.\d{2})', url
        )
        if product_match:
            product_id = product_match.group(1).upper()

        # Dacă avem variantId dar nu productId, derivăm
        if variant_id and not product_id:
            # P705.709 -> P705.70
            parts = variant_id.rsplit('.', 1)
            if len(parts) == 2:
                # P705.709 -> P705 + 709 -> P705.70
                base = parts[0]
                suffix = parts[1]
                if len(suffix) > 2:
                    product_id = f"{base}.{suffix[:2]}"
                else:
                    product_id = variant_id

        return product_id, variant_id

    def _get_images_from_database(
        self, product_id: str, variant_id: str
    ) -> list:
        """
        Navighează la pagina de imagini și extrage
        link-urile de download 1024x1024.
        URL: /en-gb/imgdtbs?productId=X&variantId=Y
        """
        images = []

        if not self.driver or not product_id:
            return images

        try:
            imgdb_url = (
                f"{self.base_url}/en-gb/imgdtbs"
                f"?productId={product_id}"
            )
            if variant_id:
                imgdb_url += f"&variantId={variant_id}"

            st.info(f"📸 XD: Accesez image database: {imgdb_url[:80]}")
            self.driver.get(imgdb_url)
            time.sleep(5)

            self._dismiss_cookie_banner()
            time.sleep(1)

            # Scroll pentru lazy loading
            self.driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);"
            )
            time.sleep(2)
            self.driver.execute_script(
                "window.scrollTo(0, 0);"
            )
            time.sleep(1)

            # ═══ METODA 1: JavaScript - extragem structura tabelului ═══
            try:
                js_images = self.driver.execute_script("""
                    var results = [];
                    var rows = document.querySelectorAll('tr, [class*="row"]');

                    rows.forEach(function(row) {
                        var cells = row.querySelectorAll('td, [class*="cell"]');
                        var rowText = row.textContent || '';

                        // Căutăm rândul cu imagini
                        var imgs = row.querySelectorAll('img');
                        var links = row.querySelectorAll('a[href]');

                        // Căutăm celulele cu 1024x1024
                        cells.forEach(function(cell, index) {
                            var cellLinks = cell.querySelectorAll('a[href]');
                            cellLinks.forEach(function(link) {
                                var href = link.getAttribute('href') || '';
                                var title = link.getAttribute('title') || '';
                                var text = link.textContent.trim();

                                if (href && (
                                    href.includes('1024') ||
                                    title.includes('1024') ||
                                    href.includes('/media/') ||
                                    href.includes('/image/') ||
                                    href.includes('.jpg') ||
                                    href.includes('.png') ||
                                    href.includes('.jpeg') ||
                                    href.includes('download')
                                )) {
                                    results.push({
                                        href: href,
                                        title: title,
                                        text: text,
                                        cellIndex: index
                                    });
                                }
                            });
                        });
                    });

                    return results;
                """)

                if js_images:
                    st.info(
                        f"📸 XD: {len(js_images)} link-uri imagine "
                        f"găsite"
                    )
                    for item in js_images:
                        href = item.get('href', '')
                        if href:
                            abs_url = make_absolute_url(
                                href, self.base_url
                            )
                            if abs_url not in images:
                                images.append(abs_url)

            except Exception as e:
                st.warning(
                    f"⚠️ XD imgdb JS metoda 1: {str(e)[:60]}"
                )

            # ═══ METODA 2: Căutăm coloanele din tabel ═══
            if not images:
                try:
                    # Găsim header-ul coloanei 1024x1024
                    js_images_2 = self.driver.execute_script("""
                        var results = [];

                        // Căutăm toate textele cu "1024"
                        var allElements = document.querySelectorAll('*');
                        var targetColumnIndex = -1;

                        // Găsim header-ul coloanei
                        var headers = document.querySelectorAll(
                            'th, td, [class*="header"]'
                        );
                        for (var i = 0; i < headers.length; i++) {
                            var text = headers[i].textContent.trim();
                            if (text.includes('1024x1024') ||
                                text.includes('1024')) {
                                targetColumnIndex = i;
                                break;
                            }
                        }

                        if (targetColumnIndex >= 0) {
                            // Luăm toate rândurile
                            var rows = document.querySelectorAll('tr');
                            for (var r = 1; r < rows.length; r++) {
                                var cells = rows[r].querySelectorAll('td');
                                if (cells.length > targetColumnIndex) {
                                    var cell = cells[targetColumnIndex];
                                    var links = cell.querySelectorAll('a');
                                    links.forEach(function(link) {
                                        var href = link.getAttribute('href');
                                        if (href) {
                                            results.push(href);
                                        }
                                    });
                                }
                            }
                        }

                        // Fallback: toate linkurile cu download/image
                        if (results.length === 0) {
                            var allLinks = document.querySelectorAll(
                                'a[href*="download"], ' +
                                'a[href*=".jpg"], ' +
                                'a[href*=".png"], ' +
                                'a[href*=".jpeg"], ' +
                                'a[href*="media"], ' +
                                'a[href*="image"]'
                            );
                            allLinks.forEach(function(link) {
                                results.push(
                                    link.getAttribute('href')
                                );
                            });
                        }

                        return results;
                    """)

                    if js_images_2:
                        st.info(
                            f"📸 XD: {len(js_images_2)} imagini "
                            f"(metoda 2)"
                        )
                        for href in js_images_2:
                            if href:
                                abs_url = make_absolute_url(
                                    href, self.base_url
                                )
                                if abs_url not in images:
                                    images.append(abs_url)

                except Exception as e:
                    st.warning(
                        f"⚠️ XD imgdb metoda 2: {str(e)[:60]}"
                    )

            # ═══ METODA 3: BeautifulSoup pe pagina imgdtbs ═══
            if not images:
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(
                        self.driver.page_source, 'html.parser'
                    )

                    # Căutăm toate link-urile din pagină
                    all_links = soup.select('a[href]')
                    for link in all_links:
                        href = link.get('href', '')
                        # Filtrăm doar linkurile de imagini
                        if href and any(
                            ext in href.lower()
                            for ext in [
                                '.jpg', '.jpeg', '.png', '.webp',
                                'download', 'media/image',
                                'image/product'
                            ]
                        ):
                            # Verificăm dacă e 1024
                            parent_row = link.find_parent('tr')
                            if parent_row:
                                row_text = parent_row.get_text()
                                # Orice link din rândul care conține
                                # date e bun
                                abs_url = make_absolute_url(
                                    href, self.base_url
                                )
                                if abs_url not in images:
                                    images.append(abs_url)
                            else:
                                abs_url = make_absolute_url(
                                    href, self.base_url
                                )
                                if abs_url not in images:
                                    images.append(abs_url)

                except Exception as e:
                    st.warning(
                        f"⚠️ XD imgdb BS4: {str(e)[:60]}"
                    )

            # ═══ METODA 4: Extragem doar butonul/icon-ul ═══
            # de download din coloana 1024x1024
            if not images:
                try:
                    # Căutăm butoanele de download
                    download_btns = self.driver.find_elements(
                        By.CSS_SELECTOR,
                        "a[download], a[href*='download'], "
                        "button[class*='download']"
                    )
                    for btn in download_btns:
                        href = btn.get_attribute('href') or ''
                        if href:
                            abs_url = make_absolute_url(
                                href, self.base_url
                            )
                            if abs_url not in images:
                                images.append(abs_url)
                except Exception:
                    pass

            # ═══ METODA 5: Preview images din tabel ═══
            if not images:
                try:
                    preview_imgs = self.driver.find_elements(
                        By.CSS_SELECTOR,
                        "table img, [class*='image-database'] img"
                    )
                    for img in preview_imgs:
                        src = (
                            img.get_attribute('data-src')
                            or img.get_attribute('src')
                            or ''
                        )
                        if (
                            src
                            and 'placeholder' not in src.lower()
                            and 'icon' not in src.lower()
                            and 'logo' not in src.lower()
                        ):
                            # Încercăm să obținem versiunea mare
                            # Înlocuim dimensiunea din URL
                            large_src = re.sub(
                                r'/\d+x\d+/', '/1024x1024/', src
                            )
                            if large_src == src:
                                large_src = re.sub(
                                    r'width=\d+', 'width=1024', src
                                )
                            abs_url = make_absolute_url(
                                large_src, self.base_url
                            )
                            if abs_url not in images:
                                images.append(abs_url)

                            # Adăugăm și originalul ca fallback
                            abs_orig = make_absolute_url(
                                src, self.base_url
                            )
                            if abs_orig not in images:
                                images.append(abs_orig)
                except Exception:
                    pass

            if images:
                st.success(
                    f"📸 XD: {len(images)} imagini descărcate "
                    f"din image database"
                )
            else:
                st.warning(
                    "⚠️ XD: Nu am găsit imagini în database"
                )

        except Exception as e:
            st.warning(
                f"⚠️ XD image database error: {str(e)[:80]}"
            )

        return images

    def _extract_colors_with_selenium(self) -> list:
        """Extrage culorile din pagina produsului (DOM live)."""
        variants = []
        if not self.driver:
            return variants

        try:
            js_result = self.driver.execute_script("""
                var results = [];

                // Căutăm secțiunea "Colour:"
                var allElements = document.querySelectorAll('*');
                var colourSection = null;

                for (var i = 0; i < allElements.length; i++) {
                    var text = allElements[i].textContent.trim();
                    if (text === 'Colour:' || text === 'Color:' ||
                        text === 'Colour' || text === 'Color') {
                        colourSection = allElements[i].parentElement;
                        break;
                    }
                }

                if (colourSection) {
                    var clickables = colourSection.querySelectorAll(
                        'a, button, [role="button"], ' +
                        'div[style*="background"], ' +
                        'span[style*="background"]'
                    );

                    clickables.forEach(function(el) {
                        var info = {
                            title: el.getAttribute('title') || '',
                            ariaLabel:
                                el.getAttribute('aria-label') || '',
                            dataColor:
                                el.getAttribute('data-color') || '',
                            href: el.getAttribute('href') || '',
                            bgColor: window.getComputedStyle(el)
                                .backgroundColor,
                            text: el.textContent.trim()
                                .substring(0, 30)
                        };
                        results.push(info);
                    });
                }

                // Fallback: link-uri cu variantId
                if (results.length === 0) {
                    document.querySelectorAll(
                        'a[href*="variantId"]'
                    ).forEach(function(el) {
                        var info = {
                            title: el.getAttribute('title') || '',
                            ariaLabel:
                                el.getAttribute('aria-label') || '',
                            dataColor:
                                el.getAttribute('data-color') || '',
                            href: el.getAttribute('href') || '',
                            bgColor: window.getComputedStyle(el)
                                .backgroundColor,
                            text: el.textContent.trim()
                                .substring(0, 30)
                        };
                        results.push(info);
                    });
                }

                return results;
            """)

            if js_result:
                for item in js_result:
                    color_name = (
                        item.get('title')
                        or item.get('ariaLabel')
                        or item.get('dataColor')
                        or item.get('text')
                        or ''
                    ).strip()

                    color_url = item.get('href', '')

                    if not color_name:
                        bg = item.get('bgColor', '')
                        if (
                            bg
                            and bg != 'rgba(0, 0, 0, 0)'
                            and bg != 'transparent'
                        ):
                            color_name = f"Color ({bg})"

                    # Extragem variantId din URL
                    variant_id = ''
                    if color_url:
                        vid_match = re.search(
                            r'variantId=([A-Z0-9.]+)',
                            color_url, re.IGNORECASE
                        )
                        if vid_match:
                            variant_id = vid_match.group(1).upper()
                            if not color_name:
                                color_name = variant_id

                    if color_name and color_name not in [
                        v['name'] for v in variants
                    ]:
                        variants.append({
                            'name': color_name,
                            'url': make_absolute_url(
                                color_url, self.base_url
                            ) if color_url else '',
                            'image': '',
                            'color_code': variant_id or '',
                            'variant_id': variant_id,
                        })

            # Fallback: regex pe page source
            if not variants:
                page_source = self.driver.page_source
                variant_ids = re.findall(
                    r'variantId=([A-Z0-9.]+)',
                    page_source, re.IGNORECASE
                )
                unique_ids = list(dict.fromkeys(
                    [v.upper() for v in variant_ids]
                ))
                for vid in unique_ids:
                    if vid not in [v['name'] for v in variants]:
                        variants.append({
                            'name': vid,
                            'url': '',
                            'image': '',
                            'color_code': vid,
                            'variant_id': vid,
                        })

        except Exception as e:
            st.warning(f"⚠️ XD color extract: {str(e)[:80]}")

        return variants

    def scrape(self, url: str) -> dict | None:
        """Scrape produs de pe xdconnects.com."""
        try:
            self._login_if_needed()

            self._init_driver()
            if not self.driver:
                return None

            # ═══ Navigăm la produs ═══
            st.info(f"📦 XD: Scrapez {url[:70]}...")
            self.driver.get(url)
            time.sleep(5)

            self._dismiss_cookie_banner()
            time.sleep(1)

            # Scroll
            for scroll_pos in [
                'document.body.scrollHeight/3',
                'document.body.scrollHeight/2',
                'document.body.scrollHeight',
                '0'
            ]:
                self.driver.execute_script(
                    f"window.scrollTo(0, {scroll_pos});"
                )
                time.sleep(0.8)

            # Parsăm pagina
            from bs4 import BeautifulSoup
            page_source = self.driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')

            # ═══ NUME ═══
            name = ""
            for sel in [
                'h1', '.product-detail h1', '.product-info h1',
            ]:
                el = soup.select_one(sel)
                if el and el.get_text(strip=True):
                    name = el.get_text(strip=True)
                    break
            if not name:
                name = "Produs XD Connects"

            # ═══ SKU / Item no. ═══
            sku = ""
            item_match = re.search(
                r'Item\s*no\.?\s*:?\s*([A-Z0-9.]+)',
                page_source, re.IGNORECASE
            )
            if item_match:
                sku = item_match.group(1).upper()

            if not sku:
                sku_match = re.search(
                    r'([pP]\d{3}\.\d{2,3})', url
                )
                if sku_match:
                    sku = sku_match.group(1).upper()

            # ═══ Product ID & Variant ID ═══
            product_id, variant_id = (
                self._extract_product_variant_ids(url)
            )
            st.info(
                f"📋 XD: productId={product_id}, "
                f"variantId={variant_id}"
            )

            # ═══ PREȚ ═══
            price = 0.0
            price_match = re.search(
                r'(?:From\s+)?(\d+[.,]\d{2})\s*RON',
                page_source, re.IGNORECASE
            )
            if price_match:
                price = clean_price(price_match.group(1))

            if price <= 0:
                for sel in [
                    '.product-detail-price', '.product-price',
                    '[class*="price"]', '.price',
                ]:
                    el = soup.select_one(sel)
                    if el:
                        price = clean_price(
                            el.get_text(strip=True)
                        )
                        if price > 0:
                            break

            # ═══ DESCRIERE ═══
            description = ""
            # Descriere scurtă din pagină
            short_match = re.search(
                r'((?:rPET|PVC|recycled|anti-theft|volume|laptop)'
                r'[^<]{10,300})',
                page_source, re.IGNORECASE
            )
            if short_match:
                description = short_match.group(1).strip()

            for sel in [
                '.product-detail-description',
                '.product-description',
                '[class*="description"]',
            ]:
                el = soup.select_one(sel)
                if el:
                    desc = str(el)
                    if len(desc) > len(description):
                        description = desc
                    break

            # ═══ SPECIFICAȚII ═══
            specifications = {}
            for sel in [
                '.product-detail-properties',
                '.product-properties',
                '.product-specifications',
                'table',
                '[class*="specification"]',
                '[class*="properties"]',
            ]:
                container = soup.select_one(sel)
                if container:
                    for row in container.select('tr'):
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

            # Preț recomandat
            price_rows = re.findall(
                r'(\d+)\s+(\d+[.,]\d{2})\s*RON',
                page_source
            )
            if price_rows:
                specifications['Preț recomandat'] = (
                    f"{price_rows[0][1]} RON "
                    f"(min. {price_rows[0][0]} buc)"
                )

            # ═══ VARIANTE DE CULOARE (Selenium) ═══
            color_variants = self._extract_colors_with_selenium()

            colors = []
            for v in color_variants:
                if v['name']:
                    colors.append(v['name'])

            if colors:
                st.info(
                    f"🎨 XD: {len(colors)} culori: "
                    + ", ".join(colors[:6])
                    + ("..." if len(colors) > 6 else "")
                )

            # ═══ IMAGINI din Image Database ═══
            images = self._get_images_from_database(
                product_id, variant_id
            )

            # Fallback: imagini din pagina produsului
            if not images:
                st.info(
                    "📸 XD: Imagini din database goale, "
                    "încerc din pagina produsului..."
                )
                for sel in [
                    '.product-detail-images img',
                    '.product-gallery img',
                    '.product-images img',
                    '[class*="gallery"] img',
                    '.product-detail img',
                    '.product-media img',
                ]:
                    imgs = soup.select(sel)
                    if imgs:
                        for img in imgs:
                            src = (
                                img.get('data-src')
                                or img.get('src')
                                or ''
                            )
                            if (
                                src
                                and 'placeholder' not in src.lower()
                                and 'icon' not in src.lower()
                                and 'logo' not in src.lower()
                                and 'co2' not in src.lower()
                            ):
                                abs_url = make_absolute_url(
                                    src, self.base_url
                                )
                                if abs_url not in images:
                                    images.append(abs_url)
                        if images:
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
                currency='RON',
            )

            product['color_variants'] = color_variants
            product['variant_images'] = {}
            product['product_id'] = product_id
            product['variant_id'] = variant_id

            st.success(
                f"📦 XD: {name[:40]} | SKU: {sku} | "
                f"Preț: {price} RON | "
                f"Culori: {len(colors)} | "
                f"Imagini: {len(images)}"
            )

            return product

        except Exception as e:
            st.error(
                f"❌ Eroare scraping XD Connects: {str(e)}"
            )
            return None
