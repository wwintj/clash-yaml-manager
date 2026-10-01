"""Display regressions at the real HTML/API boundary, with legacy bytes retained."""
import io

import pytest
from conftest import post, LINK
from core import parser
from core.ui import display_message


@pytest.mark.parametrize('uri,english', [
    ('PRIVATE-uri', 'Unsupported protocol.'),
    ('vless://PRIVATE-invalid', 'Unable to parse the node.'),
    ('ss://PRIVATE-invalid?plugin=x', 'Shadowsocks plugins and obfuscation options are unsupported.'),
    ('ss://PRIVATE-invalid?unexpected=1', 'Shadowsocks URI query parameters are unsupported.'),
])
def test_parse_api_legacy_bytes_and_generate_english_display(logged_in, uri, english):
    legacy = parser.parse_batch_nodes(uri)
    response = post(logged_in, '/parse-nodes', {'batch_nodes': uri})
    assert response.json == {'nodes': legacy['preview'], 'errors': legacy['errors']}
    assert english in display_message(legacy['preview'][0]['message'])
    html = post(logged_in, '/process', {'batch_nodes': uri}, follow_redirects=True).text
    assert f'Line 1: {english}' in html
    assert 'PRIVATE-invalid' not in html and 'PRIVATE-uri' not in html


@pytest.mark.parametrize('source,english', [
    ('[PRIVATE-body', 'Invalid YAML.'),
    ('proxies: PRIVATE-body\n', 'proxies must be a list.'),
    ('proxy-groups: [{name: Test, proxies: PRIVATE-body}]\n', 'proxy-groups Item 1 proxies must be a list of strings.'),
    ('proxy-groups: [{name: Test, proxies: [PRIVATE-missing]}]\n', 'contains an invalid node or proxy group reference.'),
])
def test_diff_api_and_generate_same_display_without_private_errors(logged_in, source, english):
    def body():
        return dict(batch_nodes='US|UI Test|'+LINK, country_geoip='off', yaml_source='custom',
                    yaml_file=(io.BytesIO(source.encode()), 'base.yaml'))
    preview = post(logged_in, '/api/preview-yaml-diff', body())
    assert preview.status_code == 400
    generated = post(logged_in, '/process', body())
    assert generated.status_code == 400
    assert english in display_message(preview.json['error'])
    assert display_message(preview.json['error']) in generated.text
    assert 'PRIVATE-body' not in generated.text and 'PRIVATE-missing' not in generated.text


def test_user_country_aliases_special_group_values_and_escaping_unchanged(web, logged_in):
    html = logged_in.get('/').text
    assert 'lang="en"' in html
    assert '🇺🇸 US · United States' in html
    assert 'value="🎥 奈飞节点"' in html and '🎥 Netflix Nodes' in html
    for label in ['🎥 Netflix Nodes', '📹 YouTube Video', '💬 AI Platforms', '📲 Telegram Messages', '🎵 TikTok', '🎬 HBO', '🏰 Disney+', '𝕏 X/Twitter']:
        assert f'<span>{label}</span>' in html
    assert 'country_mapping' not in html
    with logged_in.session_transaction() as session:
        session['page_context'] = {'error_messages': ['<img src=x onerror=alert(1)>']}
    html = logged_in.get('/').text
    assert '&lt;img src=x onerror=alert(1)&gt;' in html
    assert '<img src=x onerror=alert(1)>' not in html
    assert parser.parse_batch_nodes('日本|test|'+LINK)['errors'] # Existing ISO-only input semantics.


def test_compound_node_validation_keeps_longest_safe_phrase():
    from core.yaml_utils import validate_new_nodes
    values = dict(name='Test', type='vless', server='example.com', uuid='test', port=0)
    message = next(error for error in validate_new_nodes([values]) if '1–65535' in error)
    assert display_message(message) == 'Item 1 port must be an integer from 1 to 65535.'
