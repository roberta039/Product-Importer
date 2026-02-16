# scrapers/__init__.py
from scrapers.base_scraper import BaseScraper
from scrapers.xdconnects import XDConnectsScraper
from scrapers.pfconcept import PFConceptScraper
from scrapers.promobox import PromoboxScraper
from scrapers.andapresent import AndaPresentScraper
from scrapers.midocean import MidoceanScraper
from scrapers.sipec import SipecScraper
from scrapers.stricker import StrickerScraper
from scrapers.stamina import StaminaScraper
from scrapers.utteam import UTTeamScraper
from scrapers.clipper import ClipperScraper
from scrapers.psi import PSIScraper
from scrapers.generic import GenericScraper


def get_scraper(scraper_name: str) -> BaseScraper:
    """Factory: returnează instanța scraperului potrivit."""
    scrapers = {
        'xdconnects': XDConnectsScraper,
        'pfconcept': PFConceptScraper,
        'promobox': PromoboxScraper,
        'andapresent': AndaPresentScraper,
        'midocean': MidoceanScraper,
        'sipec': SipecScraper,
        'stricker': StrickerScraper,
        'stamina': StaminaScraper,
        'utteam': UTTeamScraper,
        'clipper': ClipperScraper,
        'psi': PSIScraper,
        'generic': GenericScraper,
    }

    scraper_class = scrapers.get(scraper_name, GenericScraper)
    return scraper_class()
