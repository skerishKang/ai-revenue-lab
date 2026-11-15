"""#7690 admin UI static contracts: site filter and operations memo."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_admin_module_has_site_filter_and_memo():
    module = (ROOT / 'static' / 'chat-feedback-module.js').read_text(encoding='utf-8')
    for token in ('ADMIN_SITE', 'SITE_ID', 'siteOnly', 'siteFilter', 'entrySite', 'paintSiteRow',
                  'changeSiteStatus', 'saveSiteMemo', 'ADMIN_SITE + "/" + id',
                  'siteAdmin', 'siteSites', 'rebuildSiteFilter'):
        assert token in module


def test_locale_has_site_labels():
    locale = (ROOT / 'static' / 'locale.js').read_text(encoding='utf-8')
    for key in ('feedback-site-toggle', 'feedback-site-filter', 'feedback-site-all',
                'feedback-miraen-home', 'feedback-site-memo', 'feedback-site-memo-save'):
        assert key in locale