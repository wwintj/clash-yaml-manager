"""Small default-suite contract; real geometry is tested by run_preview_browser.py."""
from conftest import ROOT


def test_preview_layout_has_responsive_areas_and_wrapping(logged_in):
    response = logged_in.get('/static/ui.css')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'grid-template-areas: "name country info action"' in html
    assert '(min-width: 768px) and (max-width: 1199px)' in html
    assert 'grid-template-areas: "name country" "info action"' in html
    assert 'grid-template-areas: "name" "country" "info" "action"' in html
    assert '.preview-node > * { min-width: 0; }' in html
    assert '.preview-info { grid-area: info; overflow-wrap: anywhere; }' in html
    assert 'align-self: start; justify-self: start; white-space: nowrap;' in html
    assert '.preview-action { width: 100%; }' in html


def test_preview_dom_keeps_reading_order_and_button_semantics():
    source = (ROOT / 'static/nodes.js').read_text()
    for region in ('preview-name', 'preview-country', 'preview-info', 'preview-action'):
        assert region in source
    assert 'card.append(nameBox, countryBox, info, action)' in source
    assert "action.type = 'button'" in source
    assert "search.setAttribute('aria-label','Search preview country')" in source
    assert "select.setAttribute('aria-label','Preview country')" in source
