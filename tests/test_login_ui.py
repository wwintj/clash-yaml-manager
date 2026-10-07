"""Login presentation at the existing Flask boundary; auth tests remain authoritative."""
from html.parser import HTMLParser

import pytest


class Markup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def test_password_only_login_contract(client):
    response = client.get('/')
    assert response.status_code == 200
    html = response.text
    tags = Markup(html).tags
    assert sum(tag == 'h1' for tag, _ in tags) == 1
    assert '<h1 class="login-title">Clash YAML Manager</h1>' in html
    assert '<label for="password" class="form-label">Password</label>' in html
    field = next(attrs for tag, attrs in tags if tag == 'input' and attrs.get('id') == 'password')
    assert field['type'] == field['name'] == 'password'
    assert field['placeholder'] == 'Enter password'
    assert field['autocomplete'] == 'current-password'
    assert 'required' in field and 'autofocus' in field
    assert any(tag == 'form' and attrs.get('action') == '/login' and attrs.get('method') == 'POST'
               for tag, attrs in tags)
    assert any(tag == 'input' and attrs.get('type') == 'hidden' and attrs.get('name') == 'csrf_token'
               and attrs.get('value') for tag, attrs in tags)
    assert '>Sign in</button>' in html
    for old in ('Private VPS Tool', 'ONLINE', 'ACCESS PASSWORD', 'Enter management password',
                'Enter the management password to continue.', 'ERROR LOG', '>SUCCESS<'):
        assert old not in html


@pytest.mark.parametrize('messages,expected', [
    (['登录失败，密码错误。'], ['Login failed. Incorrect password.']),
    (['登录尝试过多，请在 900 秒后重试。'], ['Too many login attempts. Try again in 900 seconds.']),
    (['<img src=x onerror=alert(1)>', 'Long message ' + 'x' * 600],
     ['&lt;img src=x onerror=alert(1)&gt;', 'Long message ' + 'x' * 600]),
])
def test_login_error_content_stays_visible_and_escaped(client, messages, expected):
    with client.session_transaction() as session:
        session['page_context'] = {'error_messages': messages}
    html = client.get('/').text
    assert 'role="alert"' in html and 'ERROR LOG' not in html
    for message in expected:
        assert message in html
    assert '<img src=x' not in html


@pytest.mark.parametrize('message,expected', [
    ('管理密码已更新，请使用新密码重新登录。', 'Password updated. Log in again with the new password.'),
    ('<script>alert(1)</script>', '&lt;script&gt;alert(1)&lt;/script&gt;'),
])
def test_login_success_path_stays_visible_and_escaped(client, message, expected):
    with client.session_transaction() as session:
        session['page_context'] = {'success_message': message}
    html = client.get('/').text
    assert 'role="status"' in html and expected in html
    assert '>SUCCESS<' not in html and '<script>alert(1)</script>' not in html


def test_login_csrf_notice_remains_in_card(client):
    with client.session_transaction() as session:
        session['csrf_notice'] = 'Security token refreshed. <script>private</script>'
    html = client.get('/').text
    card = html.index('terminal-panel login-panel')
    notice = html.index('Security token refreshed.')
    form = html.index('<form action="/login"')
    assert card < notice < form
    assert 'role="status"' in html and '&lt;script&gt;private&lt;/script&gt;' in html


def test_authenticated_header_navigation_and_password_dialog_remain(logged_in):
    html = logged_in.get('/').text
    for text in ('Clash YAML Manager', 'Change Password', 'Logout',
                 'Generate YAML', 'Fixed Subscriptions', 'Settings'):
        assert text in html
    assert 'class="login-page"' not in html and 'class="login-heading"' not in html
    for component in ('app-header', 'app-header-main', 'brand-title', 'changePasswordModal'):
        assert component in html
