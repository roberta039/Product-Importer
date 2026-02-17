# app.py
"""
Aplicație Streamlit pentru import produse anti-theft în Gomag.ro
Pasul 1: Extragere date de pe site-uri + traducere
Pasul 2: Generare CSV/Excel compatibil Gomag + import
"""
import io
import json
import re
import time
import pandas as pd
import streamlit as st
from utils.helpers import match_scraper, format_product_for_display
from utils.translator import translate_product_data
from utils.image_handler import make_absolute_url
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
    st.metric(
        "Produse traduse", len(st.session_state.translated_products)
    )
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
                    df = pd.read_csv(
                        uploaded_file, header=header_option
                    )
                else:
                    df = pd.read_excel(
                        uploaded_file, header=header_option
                    )

                # Dacă nu are header, punem nume generic
                if not has_header:
                    df.columns = [
                        f"Coloana_{i+1}"
                        for i in range(len(df.columns))
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
                st.error(
                    f"❌ Eroare la citirea fișierului: {str(e)}"
                )

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
            with st.expander(
                f"🌐 {site} ({len(site_urls)} produse)"
            ):
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
                    active_scrapers[scraper_name] = get_scraper(
                        scraper_name
                    )

                scraper = active_scrapers[scraper_name]

                try:
                    product = scraper.scrape(url)

                    if product:
                        # Traducere dacă e activată
                        if translate_option:
                            status_text.text(
                                f"🌍 Traduc {i + 1}/{total}..."
                            )
                            try:
                                product = translate_product_data(
                                    product
                                )
                            except Exception as te:
                                st.warning(
                                    f"⚠️ Traducere eșuată: "
                                    f"{str(te)[:80]}"
                                )

                        st.session_state.scraped_products.append(
                            product
                        )

                        with results_container:
                            colors_info = ""
                            if product.get('colors'):
                                colors_info = (
                                    f" | 🎨 "
                                    f"{len(product['colors'])} culori"
                                )
                            st.success(
                                f"✅ [{i + 1}/{total}] "
                                f"{product.get('name', 'N/A')} "
                                f"| Preț: "
                                f"{product.get('final_price', 0):.2f}"
                                f" LEI "
                                f"| SKU: "
                                f"{product.get('sku', 'N/A')}"
                                f"{colors_info}"
                            )
                    else:
                        with results_container:
                            st.warning(
                                f"⚠️ [{i + 1}/{total}] "
                                f"Nu am putut extrage: "
                                f"{url[:80]}"
                            )

                except Exception as e:
                    with results_container:
                        st.error(
                            f"❌ [{i + 1}/{total}] "
                            f"Eroare: {str(e)[:100]}"
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

        for idx, product in enumerate(
            st.session_state.scraped_products
        ):
            # Label expander
            colors_count = len(product.get('colors', []))
            images_count = len(product.get('images', []))

            expander_label = (
                f"{'✅' if product.get('status') == 'scraped' else '⚠️'}"
                f" {product.get('name', 'N/A')} | "
                f"SKU: {product.get('sku', 'N/A')} | "
                f"Preț: {product.get('final_price', 0):.2f} LEI"
            )
            if colors_count > 0:
                expander_label += f" | 🎨 {colors_count} culori"
            if images_count > 0:
                expander_label += f" | 📷 {images_count} img"

            with st.expander(expander_label):
                col_info, col_img = st.columns([2, 1])

                with col_info:
                    st.write(
                        f"**Nume:** {product.get('name', 'N/A')}"
                    )
                    st.write(
                        f"**SKU:** {product.get('sku', 'N/A')}"
                    )
                    st.write(
                        f"**Preț original:** "
                        f"{product.get('original_price', 0):.2f} "
                        f"{product.get('currency', 'EUR')}"
                    )
                    st.write(
                        f"**Preț final (x2):** "
                        f"{product.get('final_price', 0):.2f} LEI"
                    )
                    st.write(
                        f"**Stoc:** {product.get('stock', 1)}"
                    )
                    st.write(
                        f"**Sursă:** "
                        f"{product.get('source_site', 'N/A')}"
                    )
                    st.write(
                        f"**URL:** "
                        f"{product.get('source_url', '')}"
                    )

                    if product.get('material'):
                        st.write(
                            f"**Material:** "
                            f"{product.get('material')}"
                        )
                    if product.get('dimensions'):
                        st.write(
                            f"**Dimensiuni:** "
                            f"{product.get('dimensions')}"
                        )
                    if product.get('weight'):
                        st.write(
                            f"**Greutate:** "
                            f"{product.get('weight')}"
                        )

                    # Culori
                    if product.get('colors'):
                        st.write(
                            f"**Culori "
                            f"({len(product['colors'])}):** "
                            f"{', '.join(product['colors'])}"
                        )

                    # Variante culoare cu imagini
                    if product.get('color_variants'):
                        st.write(
                            f"**Variante culoare:** "
                            f"{len(product['color_variants'])}"
                        )
                        num_cols = min(
                            len(product['color_variants']), 4
                        )
                        if num_cols > 0:
                            variant_cols = st.columns(num_cols)
                            for vi, variant in enumerate(
                                product['color_variants'][:8]
                            ):
                                col_idx = vi % num_cols
                                with variant_cols[col_idx]:
                                    v_name = variant.get(
                                        'name', 'N/A'
                                    )
                                    if variant.get('image'):
                                        try:
                                            img_url = (
                                                make_absolute_url(
                                                    variant['image'],
                                                    product.get(
                                                        'source_url',
                                                        ''
                                                    )
                                                )
                                            )
                                            st.image(
                                                img_url,
                                                caption=v_name,
                                                width=80,
                                            )
                                        except Exception:
                                            st.write(
                                                f"🎨 {v_name}"
                                            )
                                    else:
                                        st.write(f"🎨 {v_name}")

                    # Specificații
                    if product.get('specifications'):
                        st.write("**Specificații:**")
                        for k, v in (
                            product['specifications'].items()
                        ):
                            st.write(f"  - {k}: {v}")

                with col_img:
                    images = product.get('images', [])
                    if images:
                        try:
                            st.image(
                                images[0],
                                caption="Imagine principală",
                                width=250,
                            )
                        except Exception:
                            st.write(f"🖼️ {images[0][:60]}...")

                        if len(images) > 1:
                            st.write(
                                f"📷 +{len(images) - 1} imagini:"
                            )
                            thumb_count = min(
                                len(images) - 1, 3
                            )
                            thumb_cols = st.columns(thumb_count)
                            for img_i, img_url in enumerate(
                                images[1:4]
                            ):
                                with thumb_cols[
                                    img_i % thumb_count
                                ]:
                                    try:
                                        st.image(
                                            img_url, width=80
                                        )
                                    except Exception:
                                        st.write("🖼️")
                            if len(images) > 4:
                                st.write(
                                    f"... și încă "
                                    f"{len(images) - 4}"
                                )
                    else:
                        st.write("❌ Fără imagini")

                # Editare inline
                st.markdown("---")
                with st.form(key=f"edit_product_{idx}"):
                    ec1, ec2, ec3 = st.columns(3)
                    with ec1:
                        new_name = st.text_input(
                            "Editează numele:",
                            value=product.get('name', ''),
                            key=f"name_{idx}",
                        )
                    with ec2:
                        new_price = st.number_input(
                            "Editează prețul (LEI):",
                            value=float(
                                product.get('final_price', 1.0)
                            ),
                            min_value=0.01,
                            step=0.01,
                            key=f"price_{idx}",
                        )
                    with ec3:
                        new_sku = st.text_input(
                            "Editează SKU:",
                            value=product.get('sku', ''),
                            key=f"sku_{idx}",
                        )

                    new_desc = st.text_area(
                        "Editează descrierea:",
                        value=product.get(
                            'description', ''
                        )[:500],
                        height=100,
                        key=f"desc_{idx}",
                    )

                    if st.form_submit_button(
                        "💾 Salvează modificările"
                    ):
                        sp = st.session_state.scraped_products
                        sp[idx]['name'] = new_name
                        sp[idx]['final_price'] = new_price
                        sp[idx]['sku'] = new_sku
                        if new_desc:
                            sp[idx]['description'] = new_desc
                        st.success("✅ Modificări salvate!")
                        st.rerun()

        # Buton pentru a trece la pasul 2
        st.markdown("---")
        col_next1, col_next2 = st.columns(2)

        with col_next1:
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

        with col_next2:
            if st.button(
                "🗑️ Șterge toate produsele extrase",
                type="secondary",
                use_container_width=True,
            ):
                st.session_state.scraped_products = []
                st.session_state.translated_products = []
                st.rerun()

        # Export
        st.markdown("---")
        st.subheader("💾 Export Date Intermediare")

        col_exp1, col_exp2 = st.columns(2)

        with col_exp1:
            json_data = json.dumps(
                st.session_state.scraped_products,
                indent=2,
                ensure_ascii=False,
                default=str,
            )
            st.download_button(
                label="📥 Descarcă JSON",
                data=json_data,
                file_name="produse_extrase.json",
                mime="application/json",
            )

        with col_exp2:
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
                    'Descriere': re.sub(r'<[^>]+>', '', p.get('description', '') or '').strip(),
                    'Specificatii': json.dumps(p.get('specifications', {}) or {}, ensure_ascii=False),
                    'Nr Variante': len(p.get('color_variants', [])),
                    'Nr Imagini': len(p.get('images', [])),
                    'Imagini': ' | '.join(p.get('images', [])[:10]),
                    'Sursă': p.get('source_url', ''),
                    'Site': p.get('source_site', ''),
                })
            df_export = pd.DataFrame(export_data)
            excel_buffer = io.BytesIO()
            df_export.to_excel(
                excel_buffer, index=False, engine='openpyxl'
            )
            excel_buffer.seek(0)
            st.download_button(
                label="📥 Descarcă Excel",
                data=excel_buffer,
                file_name="produse_extrase.xlsx",
                mime=(
                    "application/vnd.openxmlformats-"
                    "officedocument.spreadsheetml.sheet"
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
            "⚠️ Nu ai produse de importat. "
            "Întoarce-te la Pasul 1."
        )

        st.subheader("📂 Importă din JSON salvat anterior")
        json_upload = st.file_uploader(
            "Încarcă fișier JSON cu produse",
            type=['json'],
            key="json_upload_empty",
        )
        if json_upload:
            try:
                imported = json.loads(
                    json_upload.read().decode('utf-8')
                )
                if isinstance(imported, list) and imported:
                    st.session_state.translated_products = imported
                    st.success(
                        f"✅ {len(imported)} produse "
                        f"importate din JSON"
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
            key="json_upload_step2",
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
                        f"✅ {len(imported)} produse "
                        f"importate din JSON"
                    )
                    st.rerun()
            except Exception as e:
                st.error(f"❌ Eroare citire JSON: {str(e)}")

    st.markdown("---")

    # ---- CONFIGURARE IMPORT ----
    st.subheader("⚙️ Configurare Import")

    col_cfg1, col_cfg2, col_cfg3 = st.columns(3)

    with col_cfg1:
        category_name = st.text_input(
            "📂 Categorie Gomag:",
            value="Rucsacuri Anti-Furt",
            help="Numele exact al categoriei din Gomag",
        )

    with col_cfg2:
        brand_name = st.text_input(
            "🏷️ Brand (opțional):",
            value="",
            help="Lasă gol pentru auto-detect din sursă",
        )

    with col_cfg3:
        import_method = st.selectbox(
            "📤 Metodă import:",
            options=[
                "Descarcă CSV (recomandat)",
                "Descarcă Excel",
                "Upload automat în Gomag",
            ],
            index=0,
            help=(
                "CSV/Excel: descarci fișierul și îl imporți "
                "manual în Gomag. Upload automat: se face "
                "prin browser automation."
            ),
        )

    # Opțiune variante
    import_variants = st.checkbox(
        "🎨 Importă fiecare culoare ca produs separat",
        value=False,
        help=(
            "Dacă e bifat, fiecare variantă de culoare "
            "devine un rând separat în CSV."
        ),
    )

    st.markdown("---")

    # ---- TABEL PRODUSE PENTRU VERIFICARE ----
    st.subheader(f"📋 Produse de importat ({len(products)})")

    display_data = []
    for p in products:
        colors_str = ', '.join(p.get('colors', [])[:3])
        if len(p.get('colors', [])) > 3:
            colors_str += f" +{len(p['colors']) - 3}"

        display_data.append({
            'Import': True,
            'Nume': p.get('name', 'N/A')[:60],
            'SKU': p.get('sku', 'N/A'),
            'Preț (LEI)': round(
                float(p.get('final_price', 1.0)), 2
            ),
            'Culori': colors_str or 'N/A',
            'Imagini': len(p.get('images', [])),
            'Sursă': p.get('source_site', 'N/A'),
        })

    df_display = pd.DataFrame(display_data)

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
                min_value=0.01,
                format="%.2f",
            ),
            "Imagini": st.column_config.NumberColumn(
                "Imagini",
            ),
            "Culori": st.column_config.TextColumn(
                "Culori",
            ),
        },
        hide_index=True,
    )

    st.markdown("---")

    # ---- FILTRARE PRODUSE SELECTATE ----
    products_to_import = []
    if edited_df is not None:
        for i, row in edited_df.iterrows():
            if row.get('Import', True):
                if i < len(products):
                    try:
                        new_price = float(
                            row.get('Preț (LEI)', 1.0)
                        )
                        products[i]['final_price'] = new_price
                    except (ValueError, TypeError):
                        pass
                    products_to_import.append(products[i])

    # Expandăm variante dacă necesar
    final_products = []
    if import_variants:
        for product in products_to_import:
            color_variants = product.get('color_variants', [])
            if color_variants and len(color_variants) > 1:
                for variant in color_variants:
                    vp = product.copy()
                    v_name = variant.get('name', '')
                    vp['name'] = (
                        f"{product['name']} - {v_name}"
                    )
                    vp['sku'] = (
                        f"{product['sku']}-"
                        f"{v_name.upper()[:5]}"
                        if product.get('sku')
                        else ''
                    )
                    vp['colors'] = [v_name]
                    if variant.get('image'):
                        v_img = make_absolute_url(
                            variant['image'],
                            product.get('source_url', ''),
                        )
                        vp['images'] = (
                            [v_img]
                            + [
                                img
                                for img in product.get(
                                    'images', []
                                )
                                if img != v_img
                            ]
                        )
                    final_products.append(vp)
            else:
                final_products.append(product)
    else:
        final_products = products_to_import

    st.write(
        f"**{len(final_products)} produse pregătite "
        f"pentru export/import**"
    )

    st.markdown("---")

    # ---- GENERARE & DOWNLOAD CSV/EXCEL ----
    st.subheader("📥 Generare Fișier Import Gomag")

    importer = GomagImporter()

    if import_method == "Descarcă CSV (recomandat)":
        if st.button(
            f"📥 Generează CSV Gomag "
            f"({len(final_products)} produse)",
            type="primary",
            use_container_width=True,
            disabled=len(final_products) == 0,
        ):
            csv_bytes = importer.generate_csv_file(
                final_products, category_name, brand_name
            )

            st.success(
                f"✅ CSV generat cu "
                f"{len(final_products)} produse!"
            )

            st.download_button(
                label="📥 Descarcă CSV pentru Gomag",
                data=csv_bytes,
                file_name="import_gomag.csv",
                mime="text/csv",
            )

            # Preview
            df_preview = importer.generate_gomag_csv(
                final_products, category_name, brand_name
            )
            with st.expander("👁️ Preview CSV"):
                preview_cols = [
                    'Cod Produs (SKU)',
                    'Denumire Produs',
                    'Pret Produs: Descriere',
                    'Atribute: Culoare (variante de produs)',
                    'Stoc Cantitativ',
                    'Activ in Magazin',
                    'Categorie / Categorii',
                    'Marca (Brand)',
                    'URL Poza de Produs',
                ]
                available_cols = [
                    c for c in preview_cols
                    if c in df_preview.columns
                ]
                st.dataframe(
                    df_preview[available_cols],
                    use_container_width=True,
                )

    elif import_method == "Descarcă Excel":
        if st.button(
            f"📥 Generează Excel Gomag "
            f"({len(final_products)} produse)",
            type="primary",
            use_container_width=True,
            disabled=len(final_products) == 0,
        ):
            excel_bytes = importer.generate_excel_file(
                final_products, category_name, brand_name
            )

            st.success(
                f"✅ Excel generat cu "
                f"{len(final_products)} produse!"
            )

            st.download_button(
                label="📥 Descarcă Excel pentru Gomag",
                data=excel_bytes,
                file_name="import_gomag.xlsx",
                mime=(
                    "application/vnd.openxmlformats-"
                    "officedocument.spreadsheetml.sheet"
                ),
            )

    elif import_method == "Upload automat în Gomag":
        st.warning(
            "⚠️ Upload-ul automat necesită ca Gomag să aibă "
            "funcția de import CSV activă. Recomandat: "
            "descarcă CSV și importă manual."
        )

        if st.button(
            f"🚀 Upload CSV automat "
            f"({len(final_products)} produse)",
            type="primary",
            use_container_width=True,
            disabled=len(final_products) == 0,
        ):
            csv_bytes = importer.generate_csv_file(
                final_products, category_name, brand_name
            )

            with st.spinner("Se conectează la Gomag..."):
                if importer.login():
                    success = importer.upload_csv_to_gomag(
                        csv_bytes
                    )
                    if success:
                        st.success("✅ CSV uploadat cu succes!")
                    else:
                        st.error(
                            "❌ Upload eșuat. Descarcă CSV-ul "
                            "și importă manual."
                        )
                        st.download_button(
                            label="📥 Descarcă CSV (fallback)",
                            data=csv_bytes,
                            file_name="import_gomag.csv",
                            mime="text/csv",
                        )
                else:
                    st.error("❌ Login Gomag eșuat!")

            importer.close()

    st.markdown("---")

    # ---- INSTRUCȚIUNI IMPORT MANUAL ----
    with st.expander("📖 Cum import CSV-ul în Gomag?"):
        st.markdown("""
        ### Pași pentru import manual:
        1. Descarcă fișierul CSV de mai sus
        2. Conectează-te la **Gomag Admin Panel**
        3. Navighează la **Produse → Import Produse**
        4. Selectează fișierul CSV descărcat
        5. Mapează coloanele (ar trebui să fie automat)
        6. Click **Importă**
        7. Verifică produsele importate

        ### Note:
        - Prețul include TVA 19%
        - Stocul este setat la 1 pentru toate produsele
        - Produsele sunt active imediat
        - Imaginile sunt link-uri externe (URL-uri)
        - Dacă un produs nu are preț, este setat la 1 LEU
        - Culorile sunt listate ca atribute/variante
        - Durata de livrare: 2-5 zile lucrătoare
        """)

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
    "Selenium + Cloudscraper + Streamlit | "
    "Export CSV/Excel compatibil Gomag"
    "</div>",
    unsafe_allow_html=True,
)
