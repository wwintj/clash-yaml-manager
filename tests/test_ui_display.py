"""Display regressions at the real HTML/API boundary, with legacy bytes retained."""
import io

import pytest
from conftest import post, LINK
from core import parser
from core.ui import display_message


@pytest.mark.parametrize('uri,english', [
    ('PRIVATE-uri', '不支援的協定'),
    ('vless://PRIVATE-invalid', '無法解析節點'),
    ('ss://PRIVATE-invalid?plugin=x', '不支援 Shadowsocks 外掛及混淆選項。'),
    ('ss://PRIVATE-invalid?unexpected=1', '不支援 Shadowsocks URI query 參數。'),
])
def test_parse_api_legacy_bytes_and_generate_traditional_display(logged_in, uri, english):
    legacy = parser.parse_batch_nodes(uri)
    response = post(logged_in, '/parse-nodes', {'batch_nodes': uri})
    assert response.json == {'nodes': legacy['preview'], 'errors': legacy['errors']}
    assert english in display_message(legacy['preview'][0]['message'])
    html = post(logged_in, '/process', {'batch_nodes': uri}, follow_redirects=True).text
    assert f'第 1 行錯誤：{english}' in html
    assert 'PRIVATE-invalid' not in html and 'PRIVATE-uri' not in html


@pytest.mark.parametrize('source,english', [
    ('[PRIVATE-body', 'YAML 格式錯誤'),
    ('proxies: PRIVATE-body\n', 'proxies 必須是清單。'),
    ('proxy-groups: [{name: Test, proxies: PRIVATE-body}]\n', 'proxy-groups 第 1 項的 proxies 必須是字串清單。'),
    ('proxy-groups: [{name: Test, proxies: [PRIVATE-missing]}]\n', '含有無效的節點或策略組引用。'),
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
    assert 'lang="zh-Hant-TW"' in html
    assert '🇺🇸 US · 美國' in html
    assert 'value="🎥 奈飞节点"' in html and '🎥 Netflix 節點' in html
    for label in ['🎥 Netflix 節點', '📹 YouTube 影片', '💬 AI 平台', '📲 Telegram 訊息', '🎵 TikTok', '🎬 HBO', '🏰 Disney+', '𝕏 X/Twitter']:
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
    assert display_message(message) == '第 1 個節點連接埠必須是 1–65535 的整數。'
