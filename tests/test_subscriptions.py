import base64
from pathlib import Path

import pytest

from core import yaml_utils as y
from core.subscriptions import NEW_FILENAME, SubscriptionSigner


FILENAME = 'tim_20260925_36_AbCdEf0123456789_-abcd.yaml'


def test_v2_round_trip_and_signature_strength():
    signer = SubscriptionSigner(b'test-key')
    slug = signer.build_slug(FILENAME)
    assert slug.startswith('v2.20260925.10.')
    signature = slug.rsplit('.', 1)[1]
    assert len(signature) == 22
    assert len(base64.urlsafe_b64decode(signature + '==')) == 16
    assert signer.parse_slug(slug) == (FILENAME, signature)
    assert not SubscriptionSigner(b'other-key').parse_slug(slug)[0]
    assert not signer.valid_v2_signature(FILENAME, signer.full_token(FILENAME)[:22])


@pytest.mark.parametrize('part', [0, 1, 2, 3, 4])
def test_modified_v2_slug_fails(part):
    signer = SubscriptionSigner(b'test-key')
    pieces = signer.build_slug(FILENAME).split('.')
    pieces[part] = ('X' if part in (3, 4) else '9') + pieces[part][1:]
    assert signer.parse_slug('.'.join(pieces)) == ('', '')


@pytest.mark.parametrize('token', ['', '密码', 'a' * 7, 'a' * 9, 'a' * 13, 'a' * 63, 'a' * 65])
def test_token_lengths_are_explicit(token):
    signer = SubscriptionSigner(b'test-key')
    assert not signer.valid_full_token(FILENAME, token)
    assert not signer.valid_legacy_token('tim_20260925_1.yaml', token)
    assert not signer.valid_v2_signature(FILENAME, token)


def test_v2_cannot_downgrade_to_legacy():
    signer = SubscriptionSigner(b'test-key')
    full = signer.full_token(FILENAME)
    assert signer.valid_full_token(FILENAME, full)
    for size in (8, 12, 64):
        assert not signer.valid_legacy_token(FILENAME, full[:size])
        assert not signer.parse_slug(FILENAME[:-5] + '-' + full[:size])[0]
    slug = signer.build_slug(FILENAME)
    assert not signer.parse_slug(slug.replace('.10.', '.010.'))[0]
    assert not signer.parse_slug('../' + slug)[0]
    assert not signer.parse_slug(slug + '密码')[0]


def test_new_identity_survives_sequence_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(y.time, 'strftime', lambda _: '20260925')
    first = Path(y.save_new_output({'owner': 'first'}, str(tmp_path)))
    match = NEW_FILENAME.fullmatch(first.name)
    assert match and match.group(2) == '1'
    assert len(base64.urlsafe_b64decode(match.group(3) + '==')) == 16
    second = Path(y.save_new_output({'owner': 'second'}, str(tmp_path)))
    assert NEW_FILENAME.fullmatch(second.name).group(2) == '2'
    first.unlink()
    second.unlink()
    third = Path(y.save_new_output({'owner': 'third'}, str(tmp_path)))
    assert NEW_FILENAME.fullmatch(third.name).group(2) == '1'
    assert third.name not in (first.name, second.name)


@pytest.mark.parametrize('legacy', [True, False])
def test_deleted_urls_never_read_future_output(web, client, monkeypatch, legacy):
    monkeypatch.setattr(y.time, 'strftime', lambda _: '20260925')
    if legacy:
        old = Path(web.DIR_OUTPUTS) / 'tim_20260925_1.yaml'
        old.write_text('owner: old\n')
    else:
        old = Path(y.save_new_output({'owner': 'old'}, web.DIR_OUTPUTS))
    token = web.generate_download_token(old.name)
    urls = [f'/download/{old.name}?token={token}', f'/sub/{token}/{old.name}',
            '/s/' + web.build_short_subscription_slug(old.name)]
    if legacy:
        for size in (8, 12, 64):
            urls += [f'/s/{old.stem}-{token[:size]}', f'/sub/{token[:size]}/{old.name}',
                     f'/download/{old.name}?token={token[:size]}']
    for url in urls:
        response = client.get(url)
        assert response.status_code == 200, url
        assert b'old' in response.data
    old.unlink()
    assert all(client.get(url).status_code == 404 for url in urls)
    new = Path(y.save_new_output({'owner': 'future'}, web.DIR_OUTPUTS))
    assert new.name != old.name
    assert all(client.get(url).status_code == 404 for url in urls)
    assert b'future' in client.get('/s/' + web.build_short_subscription_slug(new.name)).data


def test_new_file_routes_reject_weak_and_wrong_format_tokens(web, client):
    output = Path(y.save_new_output({'private': True}, web.DIR_OUTPUTS))
    full = web.generate_download_token(output.name)
    slug = web.build_short_subscription_slug(output.name)
    for token in (full[:8], full[:12], full[:32], slug.rsplit('.', 1)[1]):
        assert client.get(f'/download/{output.name}?token={token}').status_code == 403
        assert client.get(f'/sub/{token}/{output.name}').status_code == 403
        assert client.get(f'/s/{output.stem}-{token}').status_code == 403
    response = client.get(f'/download/{output.name}?token={full}')
    assert response.status_code == 200
    assert response.headers['Content-Disposition'].startswith('attachment;')
    assert client.get('/s/' + slug).headers['Content-Type'].startswith('application/x-yaml')
    assert client.get('/download/' + output.name).status_code == 403


def test_signed_download_rejects_path_alias_and_symlink(web, client, tmp_path):
    outside = tmp_path / 'outside.yaml'
    outside.write_text('private: secret\n')
    output = Path(web.DIR_OUTPUTS) / 'link.yaml'
    output.symlink_to(outside)
    token = web.generate_download_token(output.name)
    assert client.get(f'/download/{output.name}?token={token}').status_code == 404
    assert client.get(f'/download/nested/{output.name}?token={token}').status_code == 403
