# utils/image_handler.py
"""
Handler pentru descărcare și procesare imagini.
"""
import os
import io
import time
import base64
import hashlib
import requests
from PIL import Image
from urllib.parse import urljoin, urlparse
import streamlit as st


def download_image(url: str, timeout: int = 30) -> dict | None:
    """
    Descarcă o imagine și returnează dict cu datele ei.
    """
    if not url:
        return None

    try:
        headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
            'Accept': 'image/*, */*',
        }

        response = requests.get(url, headers=headers, timeout=timeout, stream=True)
        response.raise_for_status()

        content = response.content
        content_type = response.headers.get('Content-Type', '')

        # Determinăm extensia
        if 'png' in content_type:
            ext = '.png'
        elif 'gif' in content_type:
            ext = '.gif'
        elif 'webp' in content_type:
            ext = '.webp'
        else:
            ext = '.jpg'

        # Verificăm că e o imagine validă
        img = Image.open(io.BytesIO(content))
        img.verify()

        # Generăm nume unic
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        filename = f"img_{url_hash}{ext}"

        return {
            'url': url,
            'content': content,
            'filename': filename,
            'content_type': content_type,
            'size': len(content),
            'base64': base64.b64encode(content).decode('utf-8'),
        }

    except Exception as e:
        st.warning(f"⚠️ Nu pot descărca imaginea {url[:80]}: {str(e)[:80]}")
        return None


def download_images_parallel(urls: list, max_images: int = 10) -> list:
    """
    Descarcă mai multe imagini secvențial (cu delay).
    """
    results = []
    urls = urls[:max_images]  # limităm numărul

    for i, url in enumerate(urls):
        if not url:
            continue

        result = download_image(url)
        if result:
            results.append(result)

        if i < len(urls) - 1:
            time.sleep(0.5)  # delay între descărcări

    return results


def make_absolute_url(url: str, base_url: str) -> str:
    """Convertește URL relativ în absolut."""
    if not url:
        return ""
    if url.startswith(('http://', 'https://')):
        return url
    if url.startswith('//'):
        return 'https:' + url
    return urljoin(base_url, url)
