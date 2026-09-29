import base64
import json
import multiprocessing
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import pytest

from core import fixed_subscriptions as fixed, generator
from core.state import StateError, write_json
from conftest import LINK

BASE = b'proxies: []\nproxy-groups: []\nrules:\n  - MATCH,DIRECT\n'


def source(name='First'):
    return dict(yaml_source='default', batch_nodes=f'US|{name}|{LINK}', aux_nodes=[],
                node_overrides={}, special_groups=[])


def parsed(config):
    return generator.parse_form_nodes(dict(batch_nodes=config['batch_nodes'],
        aux_nodes=json.dumps(config['aux_nodes']), node_overrides=json.dumps(config['node_overrides'])))


@pytest.fixture
def store(tmp_path):
    return fixed.FixedSubscriptions(tmp_path / 'state')


@pytest.fixture
def base(tmp_path):
    path = tmp_path / 'base.yaml'; path.write_bytes(BASE)
    return path


def save(store, base, key=None, config=None, custom=None, name='My Home Proxy', prefix='my-home-proxy'):
    config = config or source()
    return store.save(key, name, prefix, config, parsed(config), base, custom)


def test_source_save_url_and_stats(store, base):
    entry = save(store, base)
    slug = store.slug(entry)
    assert fixed.SLUG.fullmatch(slug)
    assert len(base64.urlsafe_b64decode(entry['token'] + '==')) == 16
    assert entry['last_access_at'] is None
    content = store.resolve(slug)
    assert b'First' in content
    before = store.get(entry['id'])
    edited = save(store, base, entry['id'], source('Second'), name='Renamed')
    assert store.slug(edited) == slug and edited['token'] == entry['token']
    assert edited['created_at'] == entry['created_at']
    assert edited['last_access_at'] == before['last_access_at']
    assert b'Second' in store.resolve(slug) and store.resolve(slug) != content
    assert edited['node_count'] == 1 and edited['group_count'] > 0 and edited['rule_count'] == 1
    assert edited['batch_nodes'] == source('Second')['batch_nodes']
    changed = save(store, base, entry['id'], prefix='new-prefix')
    assert changed['token'] == entry['token'] and store.resolve(slug) is None
    assert store.resolve(store.slug(changed))
    assert store._content(changed, 'base.yaml') == base.read_bytes()


def test_active_disable_enable_regenerate_delete_tombstone(store, base, monkeypatch):
    entry = save(store, base); slug = store.slug(entry)
    assert store.resolve('wrong-fs_' + entry['token']) is None
    assert store.resolve(entry['prefix'] + '-fs_' + 'A' * 22) is None
    store.action(entry['id'], 'disable'); assert store.resolve(slug) is None
    store.action(entry['id'], 'enable'); assert store.resolve(slug)
    changed = store.action(entry['id'], 'regenerate'); changed_slug = store.slug(changed)
    assert store.resolve(slug) is None and store.resolve(changed_slug)
    store.action(entry['id'], 'delete')
    assert store.resolve(changed_slug) is None and store.list() == []
    assert not (store.directory / entry['id']).exists()
    tokens = iter([entry['token'], changed['token'], 'B' * 22])
    monkeypatch.setattr(fixed.secrets, 'token_urlsafe', lambda n: next(tokens))
    recreated = save(store, base)
    assert recreated['token'] == 'B' * 22
    data = json.loads(store.path.read_text())
    assert set(data['retired_tokens']) == {fixed.token_hash(entry['token']), fixed.token_hash(changed['token'])}


def test_custom_persistence_and_retention_independence(store, base):
    config = dict(source(), yaml_source='custom')
    entry = save(store, base, config=config, custom=BASE)
    assert store._content(entry, 'base.yaml') == BASE
    base.unlink()
    edited = save(store, base, entry['id'], dict(config, batch_nodes=source('Updated')['batch_nodes']))
    assert store._content(edited, 'base.yaml') == BASE
    assert b'Updated' in store.resolve(store.slug(edited))
    assert len(list((store.directory / entry['id']).iterdir())) == 1


@pytest.mark.parametrize('failure', ['generation', 'metadata', 'current', 'base', 'metadata_after_replace'])
def test_atomic_failure_preserves_previous_bytes_and_source(store, base, monkeypatch, failure):
    config = dict(source(), yaml_source='custom')
    entry = save(store, base, config=config, custom=BASE)
    slug = store.slug(entry); old = store.resolve(slug); previous = store.get(entry['id'])
    from core import state
    original_replace, original_json = state.os.replace, fixed.write_json
    with monkeypatch.context() as injection:
        if failure == 'generation':
            injection.setattr(generator, 'generate', lambda *a: {'success': False})
        elif failure in ('metadata', 'metadata_after_replace'):
            def fail_json(path, value):
                if failure == 'metadata_after_replace':
                    original_json(path, value)
                raise OSError('disk failure with sensitive details')
            injection.setattr(fixed, 'write_json', fail_json)
        else:
            def fail_replace(temporary, path):
                if Path(path).name == failure + '.yaml':
                    raise OSError('replace failure')
                return original_replace(temporary, path)
            injection.setattr(state.os, 'replace', fail_replace)
        with pytest.raises((fixed.GenerationError, StateError, OSError)):
            save(store, base, entry['id'], config, BASE + b'# replacement\n', name='Replacement')
    assert store.get(entry['id']) == previous
    assert store.resolve(slug) == old and store._content(previous, 'base.yaml') == BASE


@pytest.mark.parametrize('bad', [b'not: [valid', b'proxies: nope', b'proxy-groups:\n- name: x\n  type: select\n  proxies: [missing]\nrules: []'])
def test_invalid_custom_save_does_not_damage_old(store, base, bad):
    entry = save(store, base); slug = store.slug(entry); old = store.resolve(slug)
    with pytest.raises(fixed.GenerationError):
        save(store, base, entry['id'], dict(source(), yaml_source='custom'), bad)
    assert store.resolve(slug) == old


def test_failed_create_leaves_no_record_or_files(store, base, monkeypatch):
    monkeypatch.setattr(generator, 'generate', lambda *a: {'success': False})
    with pytest.raises(fixed.GenerationError): save(store, base)
    assert store.list() == [] and list(store.directory.iterdir()) == []


@pytest.mark.parametrize('value,expected', [('My Home Proxy','my-home-proxy'), ('中文','subscription'),
    ('   ','subscription'), ('--','subscription'), ('A---B','a-b'), ('a'*80,'a'*64),
    ('!!!','subscription'), ('  A # B  ','a-b'), ('','subscription')])
def test_prefix_normalization(value, expected):
    assert fixed.normalize_prefix(value) == expected


def test_last_access_shared_throttle_and_updated_at(store, base, monkeypatch):
    entry = save(store, base); other = fixed.FixedSubscriptions(store.state)
    with patch.object(fixed.time, 'time', return_value=entry['updated_at'] + 1):
        other.resolve(store.slug(entry))
    first = store.get(entry['id']); raw = store.path.read_bytes()
    with patch.object(fixed.time, 'time', return_value=entry['updated_at'] + 59):
        store.resolve(store.slug(entry))
    assert store.path.read_bytes() == raw
    with patch.object(fixed.time, 'time', return_value=entry['updated_at'] + 62):
        other.resolve(store.slug(entry))
    final = store.get(entry['id'])
    assert final['updated_at'] == entry['updated_at'] and final['last_access_at'] > first['last_access_at']


def test_disk_write_failure_does_not_block_existing_subscription(store, base, monkeypatch):
    entry = save(store, base); old = store._content(entry, 'current.yaml')
    def fail(*args): raise OSError('disk full')
    monkeypatch.setattr(fixed, 'write_json', fail)
    monkeypatch.setattr(fixed, 'atomic_write', fail)
    with pytest.raises(OSError):
        save(store, base, entry['id'], source('Replacement'))
    assert store.resolve(store.slug(entry)) == old
    assert store.get(entry['id'])['last_access_at'] is None


def test_access_stat_failure_cannot_hide_corrupt_registry(store, base, monkeypatch):
    entry = save(store, base)
    def fail(*args):
        store.path.write_text('{broken')
        raise OSError('disk failure')
    monkeypatch.setattr(fixed, 'write_json', fail)
    monkeypatch.setattr(fixed, 'atomic_write', fail)
    with pytest.raises(StateError): store.resolve(store.slug(entry))


@pytest.mark.parametrize('field,value', [('version', 99), ('subscriptions', []), ('retired_tokens',['invalid'])])
def test_corrupt_registry_fail_closed(store, field, value):
    data = {'version':1,'subscriptions':{},'retired_tokens':[]}; data[field] = value
    write_json(store.path, data); old = store.path.read_bytes()
    with pytest.raises(StateError): store.list()
    assert store.path.read_bytes() == old


@pytest.mark.parametrize('field,value', [('id','../../bad'), ('revision','../../bad'), ('token','short'),
    ('prefix','../bad'), ('status','unknown'), ('node_count',-1), ('updated_at',float('nan')),
    ('updated_at',1e300),
    ('aux_nodes',['bad']), ('node_overrides',[]), ('yaml_source','bad')])
def test_invalid_record_schema(store, base, field, value):
    entry = save(store, base); data = json.loads(store.path.read_text())
    data['subscriptions'][entry['id']][field] = value; write_json(store.path, data)
    with pytest.raises(StateError): store.list()


def test_private_modes_and_symlink_rejection(store, base, tmp_path):
    entry = save(store, base, config=dict(source(), yaml_source='custom'), custom=BASE)
    for path in store.state.rglob('*'):
        assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)
    yaml = store.directory / entry['id'] / entry['revision'] / 'current.yaml'
    yaml.unlink(); yaml.symlink_to(base)
    assert store.resolve(store.slug(entry)) is None
    store.path.unlink(); store.path.symlink_to(base)
    with pytest.raises(StateError): store.list()
    outside = tmp_path / 'outside'; outside.mkdir()
    link = tmp_path / 'link'; link.symlink_to(outside)
    with pytest.raises(StateError): fixed.FixedSubscriptions(link)


def test_token_generation_requests_128_bits_and_small_unique_sample(store, base, monkeypatch):
    original = fixed.secrets.token_urlsafe
    sizes = []
    def token(size):
        sizes.append(size)
        return original(size)
    # Isolate this module's token source; yaml_utils also generates output nonces.
    monkeypatch.setattr(fixed, 'secrets', SimpleNamespace(token_urlsafe=token))
    entries = [save(store, base) for _ in range(4)]
    assert sizes == [16] * 4
    assert len({e['token'] for e in entries}) == len({e['id'] for e in entries}) == 4


@pytest.mark.parametrize('target', ['record','revision','state','registry'])
def test_replaced_symlink_or_public_permissions_fail_closed(store, base, tmp_path, target):
    entry = save(store, base)
    if target == 'registry':
        store.path.chmod(0o644)
        with pytest.raises(StateError): store.list()
        return
    path = {'record':store.directory / entry['id'],
            'revision':store.directory / entry['id'] / entry['revision'], 'state':store.state}[target]
    original = path.with_name(path.name + '-original'); path.rename(original)
    outside = tmp_path / 'outside'; outside.mkdir(); path.symlink_to(outside)
    if target == 'state':
        with pytest.raises(StateError): store.resolve(store.slug(entry))
        assert list(outside.iterdir()) == []
    else:
        assert store.resolve(store.slug(entry)) is None


def _worker(state, base, entry, action, start, queue):
    try:
        store = fixed.FixedSubscriptions(state); start.wait(10)
        if action == 'save': save(store, base, entry['id'], source('Second'))
        elif action != 'read': store.action(entry['id'], action)
        for _ in range(8):
            content = store.resolve(store.slug(entry))
            if content is not None:
                assert b'First' in content or b'Second' in content
                assert content.endswith(b'\n')
        queue.put('ok')
    except Exception as error:
        queue.put(type(error).__name__)


@pytest.mark.parametrize('action', ['read','save','regenerate','delete'])
def test_process_shared_read_mutation_races(store, base, action):
    entry = save(store, base); store.resolve(store.slug(entry))
    ctx = multiprocessing.get_context('fork'); start = ctx.Event(); queue = ctx.Queue()
    workers = [ctx.Process(target=_worker,args=(store.state,base,entry,a,start,queue))
               for a in [action,'read','read','read']]
    for p in workers: p.start()
    start.set()
    for p in workers: p.join(20); assert p.exitcode == 0
    assert [queue.get(timeout=2) for _ in workers] == ['ok'] * len(workers)
    if action in ('regenerate','delete'): assert store.resolve(store.slug(entry)) is None
    if action == 'save': assert b'Second' in store.resolve(store.slug(entry))
    assert json.loads(store.path.read_text())['version'] == 2
