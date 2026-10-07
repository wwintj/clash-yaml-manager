"""Authenticated chrome contracts scoped to header DOM in the existing Flask harness."""
from html.parser import HTMLParser

import pytest


class HeaderMarkup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.inside = False
        self.tags = []
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'header' and 'app-header' in attributes.get('class', '').split():
            self.inside = True
        if self.inside:
            self.tags.append((tag, attributes))

    def handle_endtag(self, tag):
        if tag == 'header':
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.text.append(data.strip())


@pytest.mark.parametrize('path,active', [
    ('/', '/'), ('/fixed-subscriptions', '/fixed-subscriptions'),
    ('/fixed-subscriptions/new', '/fixed-subscriptions'), ('/settings', '/settings'),
])
def test_header_keeps_account_actions_and_integrated_active_navigation(logged_in, path, active):
    response = logged_in.get(path)
    assert response.status_code == 200
    header = HeaderMarkup(response.text)
    text = ' '.join(header.text)
    for label in ('Clash YAML Manager', 'Change Password', 'Logout', 'Generate YAML',
                  'Fixed Subscriptions', 'Settings'):
        assert label in text
    for removed in ('YAML NODE MANAGEMENT', 'Service', 'ONLINE', 'Mode', 'YAML',
                    'Parser', 'VMESS', 'Backend', 'FLASK'):
        assert removed not in header.text
    assert response.text.count('<h1 ') == 1
    assert any(tag == 'nav' and attrs.get('aria-label') == 'Main navigation'
               for tag, attrs in header.tags)
    links = [attrs for tag, attrs in header.tags if tag == 'a']
    assert [attrs['href'] for attrs in links] == ['/', '/fixed-subscriptions', '/settings']
    assert [attrs['href'] for attrs in links if attrs.get('aria-current') == 'page'] == [active]
    trigger = next(attrs for tag, attrs in header.tags if attrs.get('data-bs-target') == '#changePasswordModal')
    assert trigger['type'] == 'button' and trigger['data-bs-toggle'] == 'modal'
    assert 'btn-sm' in trigger['class'].split()
    assert any(tag == 'form' and attrs.get('action') == '/logout' and attrs.get('method') == 'POST'
               for tag, attrs in header.tags)
    assert any(tag == 'input' and attrs.get('type') == 'hidden' and attrs.get('name') == 'csrf_token'
               and attrs.get('value') for tag, attrs in header.tags)


@pytest.mark.parametrize('context,label,role', [
    ({'error_messages': ['Header scope test error.']}, 'Header scope test error.', 'alert'),
    ({'success_message': 'Header scope test success.'}, 'Header scope test success.', 'status'),
])
def test_authenticated_feedback_remains_outside_header(logged_in, context, label, role):
    with logged_in.session_transaction() as session:
        session['page_context'] = context
    html = logged_in.get('/').text
    assert label not in HeaderMarkup(html).text
    assert label in html[html.index('</header>'):]
    assert f'role="{role}"' in html


def test_header_logout_form_token_reaches_existing_backend(logged_in):
    header = HeaderMarkup(logged_in.get('/').text)
    token = next(attrs['value'] for tag, attrs in header.tags
                 if tag == 'input' and attrs.get('name') == 'csrf_token')
    response = logged_in.post('/logout', data={'csrf_token': token}, follow_redirects=True)
    assert response.status_code == 200 and response.history[0].status_code == 302
    assert 'login-panel' in response.text and '>Sign in</button>' in response.text
    with logged_in.session_transaction() as session:
        assert not session.get('logged_in')
