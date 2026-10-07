"""Global feedback at the real Flask/Jinja boundary, retaining safe message semantics."""
from html.parser import HTMLParser

import pytest

from conftest import LINK, post


class GlobalFeedback(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.alerts = []
        self.current = None
        self.div_depth = 0
        # Global feedback is between the authenticated header and workspace.
        self.feed(html.split('</header>', 1)[1].split('<section', 1)[0])

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'div':
            self.div_depth += 1
            if self.div_depth == 1 and 'terminal-alert' in attributes.get('class', '').split():
                self.current = {'role': attributes.get('role'), 'tags': [], 'text': []}
                self.alerts.append(self.current)
        if self.current is not None:
            self.current['tags'].append((tag, attributes))

    def handle_endtag(self, tag):
        if tag == 'div':
            if self.div_depth == 1:
                self.current = None
            self.div_depth -= 1

    def handle_data(self, data):
        if self.current is not None and data.strip():
            self.current['text'].append(data.strip())


@pytest.mark.parametrize('messages,expected', [
    (['没有提供任何有效的新节点信息。'], ['No valid new nodes provided.']),
    (['<img src=x onerror=alert(1)>'], ['<img src=x onerror=alert(1)>']),
    (['第 1 行错误：协议不支持，仅接受 vmess:// 或 vless://。',
      '第 2 行错误：协议不支持，仅接受 vmess:// 或 vless://。'],
     ['Line 1: Unsupported protocol. Use VMess, VLESS, Trojan, Shadowsocks or Hysteria2.',
      'Line 2: Unsupported protocol. Use VMess, VLESS, Trojan, Shadowsocks or Hysteria2.']),
    (['<script>alert(1)</script>', 'Long message ' + 'x' * 900],
     ['<script>alert(1)</script>', 'Long message ' + 'x' * 900]),
])
def test_global_errors_preserve_every_message_role_and_escaping(logged_in, messages, expected):
    with logged_in.session_transaction() as session:
        session['page_context'] = {'error_messages': messages}
    html = logged_in.get('/').text
    [alert] = GlobalFeedback(html).alerts
    assert alert['role'] == 'alert' and alert['text'] == expected
    tags = alert['tags']
    assert not any('panel-subtitle' in attrs.get('class', '').split() for _, attrs in tags)
    assert sum(tag == 'li' for tag, _ in tags) == (len(messages) if len(messages) > 1 else 0)
    assert sum(tag == 'p' for tag, _ in tags) == (1 if len(messages) == 1 else 0)
    assert sum('role' in attrs for _, attrs in tags) == 1
    assert not any(tag in ('script', 'img') for tag, _ in tags)
    assert '<img src=x onerror=alert(1)>' not in html and '<script>alert(1)</script>' not in html
    for message in messages:
        if message.startswith('<'):
            assert '&lt;' in html and '&gt;' in html


@pytest.mark.parametrize('message,expected', [
    ('已成功删除 2 个服务器临时文件。', 'Deleted 2 temporary server files.'),
    ('<img src=x onerror=alert(1)>', '<img src=x onerror=alert(1)>'),
])
def test_global_success_keeps_status_and_escaped_content_without_heading(logged_in, message, expected):
    with logged_in.session_transaction() as session:
        session['page_context'] = {'success_message': message}
    html = logged_in.get('/').text
    [alert] = GlobalFeedback(html).alerts
    assert alert['role'] == 'status' and alert['text'] == [expected]
    assert sum(tag == 'p' for tag, _ in alert['tags']) == 1
    assert not any('panel-subtitle' in attrs.get('class', '').split() for _, attrs in alert['tags'])
    assert sum('role' in attrs for _, attrs in alert['tags']) == 1
    assert not any(tag in ('script', 'img', 'ul', 'li') for tag, _ in alert['tags'])


def test_no_messages_render_no_empty_global_feedback(logged_in):
    assert GlobalFeedback(logged_in.get('/').text).alerts == []


def test_generated_result_retains_its_contextual_success_and_headings(logged_in):
    response = post(logged_in, '/process', {'batch_nodes': 'US|Feedback Node|' + LINK}, follow_redirects=True)
    assert response.status_code == 200
    assert GlobalFeedback(response.text).alerts == []
    result = response.text.split('id="generate-result"', 1)[1].split('</section>', 1)[0]
    assert 'Generation Complete' in result and 'Generate Result' in result and 'Temporary Link' in result
    assert 'role="status"' in result and 'YAML generated. Download it or remove the temporary files.' in result
    assert 'YAML Changes' in response.text
