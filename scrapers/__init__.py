# scrapers/__init__.py
"""
Factory pentru scrapere. Folosește lazy imports pentru a evita
erori de import circular sau module lipsă.
"""


def get_scraper(scraper_name: str):
    """
    Factory: returnează instanța scraperului potrivit.
    Importă modulul doar când e nevoie (lazy import).
    """
    if scraper_name == 'xdconnects':
        from scrapers.xdconnects import XDConnectsScraper
        return XDConnectsScraper()

    elif scraper_name == 'pfconcept':
        from scrapers.pfconcept import PFConceptScraper
        return PFConceptScraper()

    elif scraper_name == 'promobox':
        from scrapers.promobox import PromoboxScraper
        return PromoboxScraper()

    elif scraper_name == 'andapresent':
        from scrapers.andapresent import AndaPresentScraper
        return AndaPresentScraper()

    elif scraper_name == 'midocean':
        from scrapers.midocean import MidoceanScraper
        return MidoceanScraper()

    elif scraper_name == 'sipec':
        from scrapers.sipec import SipecScraper
        return SipecScraper()

    elif scraper_name == 'stricker':
        from scrapers.stricker import StrickerScraper
        return StrickerScraper()

    elif scraper_name == 'stamina':
        from scrapers.stamina import StaminaScraper
        return StaminaScraper()

    elif scraper_name == 'utteam':
        from scrapers.utteam import UTTeamScraper
        return UTTeamScraper()

    elif scraper_name == 'clipper':
        from scrapers.clipper import ClipperScraper
        return ClipperScraper()

    elif scraper_name == 'psi':
        from scrapers.psi import PSIScraper
        return PSIScraper()

    else:
        from scrapers.generic import GenericScraper
        return GenericScraper()
