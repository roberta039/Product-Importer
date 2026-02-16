# app.py
"""
Aplicație Streamlit pentru import produse anti-theft în Gomag.ro
Pasul 1: Extragere date de pe site-uri + traducere
Pasul 2: Import în Gomag.ro
"""
import io
import json
import time
import pandas as pd
import streamlit as st
from utils.helpers import match_scraper, format_product_for_display
from utils.translator import translate_product_data
from scrapers import get_scraper
from gomag.importer import GomagImporter

# ──────────────────────────────────────────────
# CONFIGURARE PAGINĂ
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="Import Produse Anti-Theft → Gomag",
    page_icon="🎒",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🎒 Import Produse Anti-Theft → Gomag.ro")
st.markdown("---")

# ──────────────────────────────────────────────
# INIȚIALIZARE SESSION STATE
# ──────────────────────────────────────────────
if 'scraped_products' not in st.session_state:
    st.session_state.scraped_products = []
if 'translated_products' not in st.session_state:
    st.session_state.translated_products = []
if 'import_results' not in st.session_state:
    st.session_state.import_results = []
if 'categories' not in st.session_state:
    st.session_state.categories = []
if 'selected_category' not in st.session_state:
    st.session_state.selected_category = ""
if 'step' not in st.session_state:
    st.session_state.step = 1
if 'urls_to_process' not in st.session_state:
    st.session_state.urls_to_process = []

# ──────────────────────────────────────────────
# SIDEBAR - CONFIGURARE
# ──────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Configurare")

    # Verificare Secrets
    st.subheader("🔑 Status Credențiale")

    gomag_ok = False
    try:
        gomag_user = st.secrets.get("GOMAG", {}).get("USERNAME", "")
        gomag_ok = bool(gomag_user)
    except Exception:
        pass

    if gomag_ok:
        st.success("✅ Credențiale Gomag configurate")
    else:
        st.error("❌ Credențiale Gomag lipsă!")
        st.code("""
# În Streamlit Cloud → Settings → Secrets:

[GOMAG]
BASE_URL = "https://rucsacantifurtro.gomag.ro"
DASHBOARD_PATH = "/gomag/dashboard"
USERNAME = "email@exemplu.com"
PASSWORD = "parola_ta"

[SOURCES]
PROMOBOX_USER = ""
PROMOBOX_PASS = ""
ANDA_USER = ""
ANDA_PASS = ""
XD_USER = "user_xd"
XD_PASS = "pass_xd"
PSI_USER = "user_psi"
PSI_PASS = "pass_psi"
        """, language="toml")

    st.markdown("---")

    # Status
    st.subheader("📊 Status")
    st.metric("Produse extrase", len(st.session_state.scraped_products))
    st.metric("Produse traduse", len(st.session_state.translated_products))
    st.metric("Produse importate", len(st.session_state.import_results))

    st.markdown("---")

    # Navigare pași
    st.subheader("📋 Pași")
    step_options = {
        1: "📥 Pas 1: Upload & Extragere",
        2: "📝 Pas 2: Verificare & Import Gomag",
    }
    selected_step = st.radio(
        "Selectează pasul:",
        options=list(step_options.keys()),
        format_func=lambda x: step_options[x],
        index=st.session_state.step - 1,
    )
    st.session_state.step = selected_step

    st.markdown("---")

    # Buton reset
    if st.button("🔄 Reset Complet", type="secondary"):
        for key in [
            'scraped_products', 'translated_products',
            'import_results', 'categories', 'urls_to_process'
        ]:
            st.session_state[key] = []
        st.session_state.step = 1
        st.session_state.selected_category = ""
        st.rerun()


# ══════════════════════════════════════════════
# PAS 1: UPLOAD EXCEL + EXTRAGERE DATE
# ══════════════════════════════════════════════
if st.session_state.step == 1:
    st.header("📥 Pas 1: Upload Link-uri & Extragere Date")

    # Tab-uri pentru input
    tab_upload, tab_manual = st.tabs([
        "📄 Upload Excel/CSV",
        "✍️ Introducere manuală"
    ])

    with tab_upload:
        st.markdown(
            "Încarcă un fișier Excel (.xlsx) sau CSV cu link-urile "
            "produselor. Fișierul trebuie să aibă o coloană cu URL-uri."
        )

        uploaded_file = st.file_uploader(
            "Alege fișierul Excel/CSV",
            type=['xlsx', 'xls', 'csv'],
            help="Fișierul trebuie să conțină o coloană cu URL-uri"
        )

        has_header = st.checkbox(
            "Fișierul are rând de antet (header)",
            value=False,
            help=(
                "Bifează DOAR dacă primul rând conține titluri "
                "de coloane (ex: 'URL', 'Link'), NU un URL."
            ),
        )

        if uploaded_file:
            try:
                header_option = 0 if has_header else None

                if uploaded_file.name.endswith('.csv'):
                    df = pd.read_csv(uploaded_file, header=header_option)
                else:
                    df = pd.read_excel(uploaded_file, header=header_option)

                # Dacă nu are header, punem nume generic coloanelor
                if not has_header:
                    df.columns = [
                        f"Coloana_{i+1}" for i in range(len(df.columns))
                    ]

                st.success(
                    f"✅ Fișier încărcat: {len(df)} rânduri, "
                    f"{len(df.columns)} coloane"
                )
                st.dataframe(df.head(10), use_container_width=True)

                # Selectăm coloana cu URL-uri
                url_column = st.selectbox(
                    "Selectează coloana cu URL-uri:",
                    options=df.columns.tolist(),
                    index=0,
                )

                urls = df[url_column].dropna().astype(str).tolist()
                urls = [
                    u.strip() for u in urls
                    if u.strip().startswith('http')
                ]

                st.info(f"📎 {len(urls)} URL-uri valide găsite")

                if urls:
                    st.session_state.urls_to_process = urls

            except Exception as e:
                st.error(f"❌ Eroare la citirea fișierului: {str(e)}")

    with tab_manual:
        st.markdown("Introdu URL-urile (câte unul pe linie):")

        urls_text = st.text_area(
            "URL-uri produse:",
            height=300,
            placeholder=(
                "https://www.xdconnects.com/en-gb/bags-travel/...\n"
                "https://www.pfconcept.com/en_cz/...\n"
                "https://promobox.com/en/products/..."
            ),
        )

        if urls_text:
            urls = [
                u.strip() for u in urls_text.strip().split('\n')
                if u.strip().startswith('http')
            ]
            st.info(f"📎 {len(urls)} URL-uri introduse")
            st.session_state.urls_to_process = urls

    st.markdown("---")

    # PROCESARE URL-uri
    if st.session_state.urls_to_process:
        urls = st.session_state.urls_to_process

        # Afișăm URL-urile grupate per site
        st.subheader("📋 URL-uri de procesat")

        url_summary = {}
        for url in urls:
            scraper_name = match_scraper(url)
            url_summary.setdefault(scraper_name, []).append(url)

        for site, site_urls in url_summary.items():
            with st.expander(f"🌐 {site} ({len(site_urls)} produse)"):
                for u in site_urls:
                    st.text(u)

        st.markdown("---")

        # BUTON EXTRAGERE
        col1, col2 = st.columns(2)

        with col1:
            start_scraping = st.button(
                "🚀 Începe Extragerea Datelor",
                type="primary",
                use_container_width=True,
            )

        with col2:
            translate_option = st.checkbox(
                "🌍 Traduce automat în română",
                value=True,
            )

        if start_scraping:
            st.session_state.scraped_products = []
            st.session_state.translated_products = []

            progress_bar = st.progress(0)
            status_text = st.empty()
            results_container = st.container()

            total = len(urls)
            active_scrapers = {}

            for i, url in enumerate(urls):
                progress = (i + 1) / total
                progress_bar.progress(progress)
                status_text.text(
                    f"⏳ Procesez {i + 1}/{total}: {url[:80]}..."
                )

                scraper_name = match_scraper(url)

                # Reutilizăm scraperul pentru același site
                if scraper_name not in active_scrapers:
                    active_scrapers[scraper_name] = get_scraper(scraper_name)

                scraper = active_scrapers[scraper_name]

                try:
                    product = scraper.scrape(url)

                    if product:
                        # Traducere dacă e activată
                        if translate_option:
                            status_text.text(
                                f"🌍 Traduc produsul {i + 1}/{total}..."
                            )
                            try:
                                product = translate_product_data(product)
                            except Exception as te:
                                st.warning(
                                    f"⚠️ Traducere eșuată pentru "
                                    f"{product.get('name', 'N/A')}: "
                                    f"{str(te)[:80]}"
                                )

                        st.session_state.scraped_products.append(product)

                        with results_container:
                            st.success(
                                f"✅ [{i + 1}/{total}] "
                                f"{product.get('name', 'N/A')} "
                                f"| Preț: "
                                f"{product.get('final_price', 0):.2f} LEI "
                                f"| SKU: {product.get('sku', 'N/A')}"
                            )
                    else:
                        with results_container:
                            st.warning(
                                f"⚠️ [{i + 1}/{total}] "
                                f"Nu am putut extrage: {url[:80]}"
                            )

                except Exception as e:
                    with results_container:
                        st.error(
                            f"❌ [{i + 1}/{total}] Eroare: {str(e)[:100]}"
                        )

                # Delay între request-uri
                time.sleep(2)

            # Închidem scraperele
            for scraper in active_scrapers.values():
                try:
                    scraper.close()
                except Exception:
                    pass

            progress_bar.progress(1.0)
            status_text.text(
                f"✅ Finalizat! "
                f"{len(st.session_state.scraped_products)} "
                f"produse extrase din {total}"
            )

            if translate_option:
                st.session_state.translated_products = (
                    st.session_state.scraped_products.copy()
                )

    # AFIȘARE PRODUSE EXTRASE
    if st.session_state.scraped_products:
        st.markdown("---")
        st.subheader(
            f"📦 Produse Extrase "
            f"({len(st.session_state.scraped_products)})"
        )

        for idx, product in enumerate(st.session_state.scraped_products):
            with st.expander(
                f"{'✅' if product.get('status') == 'scraped' else '⚠️'} "
                f"{product.get('name', 'N/A')} | "
                f"SKU: {product.get('sku', 'N/A')} | "
                f"Preț: {product.get('final_price', 0):.2f} LEI"
            ):
                col_info, col_img = st.columns([2, 1])

                with col_info:
                    st.write(f"**Nume:** {product.get('name', 'N/A')}")
                    st.write(f"**SKU:** {product.get('sku', 'N/A')}")
                    st.write(
                        f"**Preț original:** "
                        f"{product.get('original_price', 0):.2f} "
                        f"{product.get('currency', 'EUR')}"
                    )
                    st.write(
                        f"**Preț final (x2):** "
                        f"{product.get('final_price', 0):.2f} LEI"
                    )
                    st.write(f"**Stoc:** {product.get('stock', 1)}")
                    st.write(
                        f"**Sursă:** {product.get('source_site', 'N/A')}"
                    )
                    st.write(
                        f"**URL:** {product.get('source_url', '')}"
                    )

                    if product.get('colors'):
                        st.write(
                            f"**Culori:** "
                            f"{', '.join(product['colors'])}"
                        )

                    if product.get('specifications'):
                        st.write("**Specificații:**")
                        for k, v in product['specifications'].items():
                            st.write(f"  - {k}: {v}")

                with col_img:
                    images = product.get('images', [])
                    if images:
                        try:
                            st.image(
                                images[0],
                                caption="Imagine principală",
                                width=200
                            )
                        except Exception:
                            st.write(f"🖼️ {images[0][:60]}...")
                        if len(images) > 1:
                            st.write(f"📷 +{len(images) - 1} imagini")

                # Editare inline
                with st.form(key=f"edit_product_{idx}"):
                    new_name = st.text_input(
                        "Editează numele:",
                        value=product.get('name', ''),
                        key=f"name_{idx}"
                    )
                    new_price = st.number_input(
                        "Editează prețul (LEI):",
                        value=float(product.get('final_price', 1.0)),
                        min_value=0.01,
                        step=0.01,
                        key=f"price_{idx}"
                    )
                    new_sku = st.text_input(
                        "Editează SKU:",
                        value=product.get('sku', ''),
                        key=f"sku_{idx}"
                    )

                    if st.form_submit_button("💾 Salvează modificările"):
                        st.session_state.scraped_products[idx]['name'] = (
                            new_name
                        )
                        st.session_state.scraped_products[idx][
                            'final_price'
                        ] = new_price
                        st.session_state.scraped_products[idx]['sku'] = (
                            new_sku
                        )
                        st.success("✅ Modificări salvate!")
                        st.rerun()

        # Buton pentru a trece la pasul 2
        st.markdown("---")
        if st.button(
            "➡️ Continuă la Pasul 2: Import în Gomag",
            type="primary",
            use_container_width=True,
        ):
            st.session_state.translated_products = (
                st.session_state.scraped_products.copy()
            )
            st.session_state.step = 2
            st.rerun()

        # Export JSON
        st.markdown("---")
        st.subheader("💾 Export Date")

        col_export1, col_export2 = st.columns(2)

        with col_export1:
            json_data = json.dumps(
                st.session_state.scraped_products,
                indent=2,
                ensure_ascii=False,
            )
            st.download_button(
                label="📥 Descarcă JSON cu produsele extrase",
                data=json_data,
                file_name="produse_extrase.json",
                mime="application/json",
            )

        with col_export2:
            # Export ca Excel
            export_data = []
            for p in st.session_state.scraped_products:
                export_data.append({
                    'Nume': p.get('name', ''),
                    'SKU': p.get('sku', ''),
                    'Preț Original': p.get('original_price', 0),
                    'Moneda': p.get('currency', 'EUR'),
                    'Preț Final LEI': p.get('final_price', 0),
                    'Stoc': p.get('stock', 1),
                    'Culori': ', '.join(p.get('colors', [])),
                    'Imagini': ' | '.join(p.get('images', [])[:5]),
                    'Sursă': p.get('source_url', ''),
                    'Site': p.get('source_site', ''),
                })

            df_export = pd.DataFrame(export_data)
            excel_buffer = io.BytesIO()
            df_export.to_excel(excel_buffer, index=False, engine='openpyxl')
            excel_buffer.seek(0)

            st.download_button(
                label="📥 Descarcă Excel cu produsele extrase",
                data=excel_buffer,
                file_name="produse_extrase.xlsx",
                mime=(
                    "application/vnd.openxmlformats-officedocument"
                    ".spreadsheetml.sheet"
                ),
            )


# ══════════════════════════════════════════════
# PAS 2: VERIFICARE & IMPORT ÎN GOMAG
# ══════════════════════════════════════════════
elif st.session_state.step == 2:
    st.header("📝 Pas 2: Verificare & Import în Gomag.ro")

    products = (
        st.session_state.translated_products
        or st.session_state.scraped_products
    )

    if not products:
        st.warning(
            "⚠️ Nu ai produse de importat. Întoarce-te la Pasul 1."
        )

        # Opțiune de import din JSON
        st.subheader("📂 Importă din JSON salvat anterior")
        json_upload = st.file_uploader(
            "Încarcă fișier JSON cu produse",
            type=['json'],
            key="json_upload_empty"
        )
        if json_upload:
            try:
                imported = json.loads(
                    json_upload.read().decode('utf-8')
                )
                if isinstance(imported, list) and imported:
                    st.session_state.translated_products = imported
                    st.success(
                        f"✅ {len(imported)} produse importate din JSON"
                    )
                    st.rerun()
            except Exception as e:
                st.error(f"❌ Eroare citire JSON: {str(e)}")

        if st.button("⬅️ Înapoi la Pasul 1"):
            st.session_state.step = 1
            st.rerun()
        st.stop()

    # ---- IMPORT JSON (opțional) ----
    with st.expander("📂 Importă din JSON salvat anterior"):
        json_upload = st.file_uploader(
            "Încarcă fișier JSON cu produse",
            type=['json'],
            key="json_upload_step2"
        )
        if json_upload:
            try:
                imported = json.loads(
                    json_upload.read().decode('utf-8')
                )
                if isinstance(imported, list) and imported:
                    st.session_state.translated_products = imported
                    products = imported
                    st.success(
                        f"✅ {len(imported)} produse importate din JSON"
                    )
                    st.rerun()
            except Exception as e:
                st.error(f"❌ Eroare citire JSON: {str(e)}")

    st.markdown("---")

    # ---- CATEGORII GOMAG ----
    st.subheader("📂 Selectare Categorie Gomag")

    col_cat1, col_cat2 = st.columns(2)

    with col_cat1:
        if st.button("🔄 Obține Categorii din Gomag", type="secondary"):
            with st.spinner("Se conectează la Gomag..."):
                importer = GomagImporter()
                if importer.login():
                    cats = importer.get_categories()
                    st.session_state.categories = cats
                    if cats:
                        st.success(
                            f"✅ {len(cats)} categorii găsite"
                        )
                    else:
                        st.warning(
                            "⚠️ Nu am găsit categorii. "
                            "Introdu manual mai jos."
                        )
                else:
                    st.error(
                        "❌ Nu mă pot conecta la Gomag. "
                        "Verifică credențialele din Secrets."
                    )
                importer.close()

    with col_cat2:
        new_cat_name = st.text_input(
            "Sau creează categorie nouă:",
            placeholder="ex: Rucsacuri Anti-Furt"
        )

    if st.session_state.categories:
        cat_options = ["-- Selectează --"] + [
            f"{c['name']} (ID: {c['id']})"
            for c in st.session_state.categories
        ]
        selected = st.selectbox("Categorie existentă:", cat_options)

        if selected != "-- Selectează --":
            idx = cat_options.index(selected) - 1
            st.session_state.selected_category = (
                st.session_state.categories[idx]
            )
    elif new_cat_name:
        st.session_state.selected_category = {
            'id': '',
            'name': new_cat_name,
            'path': new_cat_name,
        }
        st.info(
            f"ℹ️ Categoria '{new_cat_name}' va fi folosită. "
            f"Dacă nu există, trebuie creată manual în Gomag."
        )

    st.markdown("---")

    # ---- TABEL PRODUSE PENTRU VERIFICARE ----
    st.subheader(f"📋 Produse de importat ({len(products)})")

    # Creăm DataFrame pentru afișare
    display_data = []
    for p in products:
        display_data.append({
            'Import': True,
            'Nume': p.get('name', 'N/A'),
            'SKU': p.get('sku', 'N/A'),
            'Preț (LEI)': round(float(p.get('final_price', 1.0)), 2),
            'Imagini': len(p.get('images', [])),
            'Sursă': p.get('source_site', 'N/A'),
        })

    df_display = pd.DataFrame(display_data)

    # Tabel editabil
    edited_df = st.data_editor(
        df_display,
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "Import": st.column_config.CheckboxColumn(
                "Import?",
                help="Bifează produsele de importat",
                default=True,
            ),
            "Preț (LEI)": st.column_config.NumberColumn(
                "Preț (LEI)",
                help="Prețul final în LEI",
                min_value=0.01,
                format="%.2f",
            ),
            "Imagini": st.column_config.NumberColumn(
                "Imagini",
                help="Numărul de imagini",
            ),
        },
        hide_index=True,
    )

    st.markdown("---")

    # ---- BUTON IMPORT ----
    st.subheader("🚀 Import în Gomag")

    selected_category = st.session_state.get('selected_category', {})
    if isinstance(selected_category, dict):
        cat_name = selected_category.get('name', 'Neconfigurat')
    else:
        cat_name = 'Neconfigurat'

    st.info(f"📂 Categorie selectată: **{cat_name}**")

    # Filtrăm doar produsele bifate
    products_to_import = []
    if edited_df is not None:
        for i, row in edited_df.iterrows():
            if row.get('Import', True):
                if i < len(products):
                    # Actualizăm prețul dacă a fost modificat
                    try:
                        new_price = float(row.get('Preț (LEI)', 1.0))
                        products[i]['final_price'] = new_price
                    except (ValueError, TypeError):
                        pass
                    products_to_import.append(products[i])

    st.write(
        f"**{len(products_to_import)} produse selectate pentru import**"
    )

    # Opțiuni suplimentare
    col_opt1, col_opt2 = st.columns(2)
    with col_opt1:
        delay_between = st.slider(
            "Delay între importuri (secunde):",
            min_value=2,
            max_value=15,
            value=5,
            help="Timp de așteptare între importul fiecărui produs",
        )
    with col_opt2:
        show_screenshots = st.checkbox(
            "Afișează screenshots la erori",
            value=True,
            help="Afișează capturi de ecran când apar erori",
        )

    st.markdown("---")

    import_btn = st.button(
        f"🚀 Importă {len(products_to_import)} Produse în Gomag",
        type="primary",
        use_container_width=True,
        disabled=len(products_to_import) == 0,
    )

    if import_btn and products_to_import:
        progress_bar = st.progress(0)
        status_text = st.empty()
        results_container = st.container()

        importer = GomagImporter()

        with st.spinner("Se conectează la Gomag..."):
            if not importer.login():
                st.error(
                    "❌ Nu mă pot conecta la Gomag. "
                    "Verifică credențialele."
                )
                importer.close()
                st.stop()

        total = len(products_to_import)
        success_count = 0
        fail_count = 0

        for i, product in enumerate(products_to_import):
            progress = (i + 1) / total
            progress_bar.progress(progress)
            status_text.text(
                f"⏳ Import {i + 1}/{total}: "
                f"{product.get('name', 'N/A')[:50]}..."
            )

            try:
                cat_id = ""
                cat_nm = ""
                if isinstance(selected_category, dict):
                    cat_id = selected_category.get('id', '')
                    cat_nm = selected_category.get('name', '')

                success = importer.import_product(
                    product,
                    category_id=cat_id,
                    category_name=cat_nm,
                )

                result = {
                    'name': product.get('name', 'N/A'),
                    'sku': product.get('sku', 'N/A'),
                    'price': product.get('final_price', 0),
                    'status': 'success' if success else 'failed',
                }
                st.session_state.import_results.append(result)

                if success:
                    success_count += 1
                    with results_container:
                        st.success(
                            f"✅ [{i + 1}/{total}] "
                            f"{product.get('name', 'N/A')}"
                        )
                else:
                    fail_count += 1
                    with results_container:
                        st.error(
                            f"❌ [{i + 1}/{total}] "
                            f"{product.get('name', 'N/A')}"
                        )

            except Exception as e:
                fail_count += 1
                with results_container:
                    st.error(
                        f"❌ [{i + 1}/{total}] Eroare: {str(e)[:100]}"
                    )
                st.session_state.import_results.append({
                    'name': product.get('name', 'N/A'),
                    'sku': product.get('sku', 'N/A'),
                    'price': product.get('final_price', 0),
                    'status': 'error',
                })

            # Delay între importuri
            time.sleep(delay_between)

        importer.close()

        progress_bar.progress(1.0)
        status_text.text("✅ Import finalizat!")

        st.markdown("---")
        st.subheader("📊 Rezumat Import")
        col_s, col_f, col_t = st.columns(3)
        with col_s:
            st.metric("✅ Importate cu succes", success_count)
        with col_f:
            st.metric("❌ Eșuate", fail_count)
        with col_t:
            st.metric("📦 Total procesate", total)

    # ---- REZULTATE IMPORT ----
    if st.session_state.import_results:
        st.markdown("---")
        st.subheader("📊 Istoric Import")

        results_df = pd.DataFrame(st.session_state.import_results)
        st.dataframe(results_df, use_container_width=True)

        # Export rezultate
        results_json = json.dumps(
            st.session_state.import_results,
            indent=2,
            ensure_ascii=False,
        )
        st.download_button(
            label="📥 Descarcă rezultatele importului",
            data=results_json,
            file_name="rezultate_import.json",
            mime="application/json",
        )

    # Buton înapoi
    st.markdown("---")
    if st.button("⬅️ Înapoi la Pasul 1"):
        st.session_state.step = 1
        st.rerun()


# ──────────────────────────────────────────────
# FOOTER
# ──────────────────────────────────────────────
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: gray;'>"
    "🎒 Anti-Theft Backpack Importer v2.0 | "
    "Selenium + Cloudscraper + Streamlit"
    "</div>",
    unsafe_allow_html=True,
)
