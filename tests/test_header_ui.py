"""Authenticated chrome contracts scoped to header DOM in the existing Flask harness."""
from html.parser import HTMLParser

import pytest


class HeaderMarkup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.inside = False
        self.tags = []
        self.text = []
        self.alerts = []
        self.after_header = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'section':
            self.after_header = False
        if self.after_header and tag == 'div' and {'terminal-alert', 'error'} <= set(attributes.get('class', '').split()):
            self.alerts.append(attributes)
        if tag == 'header' and 'app-header' in attributes.get('class', '').split():
            self.inside = True
        if self.inside:
            self.tags.append((tag, attributes))

    def handle_endtag(self, tag):
        if tag == 'header':
            self.inside = False
            self.after_header = True

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


def test_process_invalid_mode_keeps_generate_navigation_and_alert(logged_in):
    header = HeaderMarkup(logged_in.get('/').text)
    token = next(attrs['value'] for tag, attrs in header.tags
                 if tag == 'input' and attrs.get('name') == 'csrf_token')
    response = logged_in.post('/process', data={
        'csrf_token': token, 'node_update_mode': 'invalid',
    }, follow_redirects=False)
    assert response.status_code == 400
    assert not response.history and 'Location' not in response.headers
    assert 'Node Update Mode is invalid. Choose Replace or Merge.' in response.text
    page = HeaderMarkup(response.text)
    assert [alert.get('role') for alert in page.alerts] == ['alert']
    links = [attrs for tag, attrs in page.tags if tag == 'a']
    assert [attrs['href'] for attrs in links] == ['/', '/fixed-subscriptions', '/settings']
    assert [attrs['href'] for attrs in links if attrs.get('aria-current') == 'page'] == ['/']
    assert all('aria-current' not in attrs for attrs in links if attrs['href'] != '/')
    # A direct error response must not alter the next normal GET's active page.
    home = HeaderMarkup(logged_in.get('/').text)
    assert [attrs['href'] for tag, attrs in home.tags
            if tag == 'a' and attrs.get('aria-current') == 'page'] == ['/']


def test_login_page_has_no_authenticated_navigation(client):
    response = client.get('/')
    assert response.status_code == 200
    assert not HeaderMarkup(response.text).tags
    assert 'aria-label="Main navigation"' not in response.text
    assert 'aria-current="page"' not in response.text
    assert '<label for="password" class="form-label">Password</label>' in response.text
    assert '>Sign in</button>' in response.text
