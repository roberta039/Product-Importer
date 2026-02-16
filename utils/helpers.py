# utils/helpers.py
"""
Funcții helper generale pentru proiect.
"""
import re
import os
import hashlib
from urllib.parse import urlparse


def get_domain(url: str) -> str:
    """Extrage domeniul din URL."""
    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "").lower()
    return domain


def clean_price(price_str: str) -> float:
    """
    Curăță un string de preț și returnează float.
    Gestionează formate: 12.50, 12,50, 1.234,56, 1,234.56
    """
    if not price_str:
        return 0.0

    price_str = str(price_str).strip()
    # Eliminăm simboluri monetare și spații
    price_str = re.sub(r'[€$£RON\s]', '', price_str, flags=re.IGNORECASE)
    price_str = price_str.strip()

    if not price_str:
        return 0.0

    # Detectăm formatul
    # Format: 1.234,56 (european)
    if re.match(r'^\d{1,3}(\.\d{3})*(,\d{1,2})?$', price_str):
        price_str = price_str.replace('.', '').replace(',', '.')
    # Format: 1,234.56 (american)
    elif re.match(r'^\d{1,3}(,\d{3})*(\.\d{1,2})?$', price_str):
        price_str = price_str.replace(',', '')
    # Format: 12,50 (european simplu)
    elif ',' in price_str and '.' not in price_str:
        price_str = price_str.replace(',', '.')
    # Format: 12.50 (simplu)
    # nu facem nimic

    try:
        return float(price_str)
    except (ValueError, TypeError):
        return 0.0


def double_price(price: float) -> float:
    """Dublează prețul (adaugă 100%)."""
    if price <= 0:
        return 1.0  # preț minim 1 LEU
    return round(price * 2, 2)


def generate_sku(source_sku: str, url: str = "") -> str:
    """Generează SKU bazat pe SKU-ul sursă sau URL."""
    if source_sku and source_sku.strip():
        return source_sku.strip().upper().replace(" ", "-")

    if url:
        # Generăm din URL
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8].upper()
        return f"IMP-{url_hash}"

    return f"IMP-{hashlib.md5(os.urandom(8)).hexdigest()[:8].upper()}"


def sanitize_filename(name: str) -> str:
    """Curăță un string pentru a fi folosit ca nume de fișier."""
    name = re.sub(r'[^\w\s\-.]', '', name)
    name = re.sub(r'\s+', '_', name)
    return name[:100]


def match_scraper(url: str) -> str:
    """
    Determină care scraper să fie folosit pe baza URL-ului.
    Returnează numele scraperului.
    """
    domain = get_domain(url)

    scraper_map = {
        'xdconnects.com': 'xdconnects',
        'pfconcept.com': 'pfconcept',
        'promobox.com': 'promobox',
        'andapresent.com': 'andapresent',
        'midocean.com': 'midocean',
        'sipec.com': 'sipec',
        'stricker-europe.com': 'stricker',
        'stamina-shop.eu': 'stamina',
        'utteam.com': 'utteam',
        'clipperinterall.com': 'clipper',
        'psiproductfinder.de': 'psi',
    }

    for key, value in scraper_map.items():
        if key in domain:
            return value

    return 'generic'


def format_product_for_display(product: dict) -> dict:
    """Formatează un produs pentru afișare în Streamlit."""
    return {
        'Nume': product.get('name', 'N/A'),
        'SKU': product.get('sku', 'N/A'),
        'Preț Original': f"{product.get('original_price', 0):.2f}",
        'Preț Final (x2)': f"{product.get('final_price', 0):.2f} LEI",
        'Culori': ', '.join(product.get('colors', [])) if product.get('colors') else 'N/A',
        'Imagini': len(product.get('images', [])),
        'Sursă': product.get('source_url', 'N/A'),
        'Status': product.get('status', 'pending'),
    }
