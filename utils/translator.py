# utils/translator.py
"""
Modul de traducere folosind deep-translator (gratuit, fără API key).
"""
import re
import time
import streamlit as st
from deep_translator import GoogleTranslator


# Cache pentru traduceri (evită re-traducerea aceluiași text)
_translation_cache = {}


def translate_text(text: str, source: str = 'auto', target: str = 'ro') -> str:
    """
    Traduce text în limba română.
    Folosește cache pentru a evita request-uri duplicate.
    """
    if not text or not text.strip():
        return text

    text = text.strip()

    # Verificăm cache
    cache_key = f"{source}_{target}_{text}"
    if cache_key in _translation_cache:
        return _translation_cache[cache_key]

    # Dacă textul e deja în română sau e foarte scurt (SKU, cod)
    if len(text) <= 3:
        return text

    try:
        # deep-translator are limită de 5000 caractere
        if len(text) > 4500:
            # Împărțim textul în bucăți
            chunks = _split_text(text, 4500)
            translated_chunks = []
            for chunk in chunks:
                translated = GoogleTranslator(
                    source=source, target=target
                ).translate(chunk)
                translated_chunks.append(translated or chunk)
                time.sleep(0.3)  # rate limiting
            result = ' '.join(translated_chunks)
        else:
            result = GoogleTranslator(
                source=source, target=target
            ).translate(text)
            if not result:
                result = text

        _translation_cache[cache_key] = result
        return result

    except Exception as e:
        st.warning(f"⚠️ Eroare traducere: {str(e)[:100]}")
        return text


def translate_html(html_text: str, source: str = 'auto', target: str = 'ro') -> str:
    """
    Traduce conținut HTML păstrând tag-urile.
    """
    if not html_text:
        return html_text

    # Extragem textul din HTML, traducem, apoi reconstruim
    # Metodă simplă: traducem totul și lăsăm Google să păstreze tag-urile
    try:
        # Extragem doar textul vizibil
        text_parts = re.split(r'(<[^>]+>)', html_text)
        translated_parts = []

        for part in text_parts:
            if part.startswith('<'):
                # Este tag HTML, îl păstrăm
                translated_parts.append(part)
            elif part.strip():
                # Este text, îl traducem
                translated_parts.append(translate_text(part, source, target))
            else:
                translated_parts.append(part)

        return ''.join(translated_parts)

    except Exception:
        return translate_text(html_text, source, target)


def _split_text(text: str, max_length: int) -> list:
    """Împarte textul în bucăți la granița propozițiilor."""
    chunks = []
    current = ""

    sentences = re.split(r'(?<=[.!?])\s+', text)

    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= max_length:
            current += (" " if current else "") + sentence
        else:
            if current:
                chunks.append(current)
            current = sentence

    if current:
        chunks.append(current)

    return chunks if chunks else [text[:max_length]]


def translate_product_data(product: dict) -> dict:
    """
    Traduce toate câmpurile relevante ale unui produs.
    """
    translated = product.copy()

    # Traducem numele
    if product.get('name'):
        translated['name_ro'] = translate_text(product['name'])
        translated['name'] = translated['name_ro']

    # Traducem descrierea
    if product.get('description'):
        translated['description_ro'] = translate_html(product['description'])
        translated['description'] = translated['description_ro']

    # Traducem specificațiile
    if product.get('specifications'):
        translated_specs = {}
        for key, value in product['specifications'].items():
            t_key = translate_text(key)
            t_value = translate_text(str(value))
            translated_specs[t_key] = t_value
        translated['specifications'] = translated_specs

    # Traducem culorile
    if product.get('colors'):
        translated['colors'] = [translate_text(c) for c in product['colors']]

    # Traducem materialul
    if product.get('material'):
        translated['material'] = translate_text(product['material'])

    return translated
