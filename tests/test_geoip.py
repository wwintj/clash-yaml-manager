"""Synthetic reader injection; no third-party geographic database is distributed."""
import base64
import copy
import io
import json
import logging
import os
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest
from werkzeug.datastructures import MultiDict

from core import geoip, geoip_store, generator, parser, source_fetch, source_parser
from core.geoip_store import GeoIPError, GeoIPStore
from core.node_identity import fingerprint
from core.state import file_lock, write_json
from conftest import LINK, post


@pytest.fixture
def readers(monkeypatch):
    state = dict(opened=[], closed=[], calls=[], country='SG', record=None, error=False)
    class Reader:
        def __init__(self, data): self.data=data
        def metadata(self): return SimpleNamespace(database_type='Synthetic-Country',ip_version=6)
        def get(self, address):
            state['calls'].append(address)
            if state['error']: raise ValueError('PRIVATE address details')
            return state['record'] if state['record'] is not None else {'country': {'iso_code':self.data.decode().split(':')[1]}}
        def close(self): state['closed'].append(self.data)
    def open_reader(data):
        if not data.startswith(b'SYNTHETIC:') or data.split(b':')[1] not in (b'SG',b'TW',b'US',b'JP'):
            raise ValueError('PRIVATE MMDB details')
        state['opened'].append(data)
        return Reader(data)
    monkeypatch.setattr(geoip,'open_reader',open_reader)
    state['factory']=open_reader
    return state


@pytest.fixture
def database(tmp_path,readers):
    state=tmp_path/'state';state.mkdir(mode=0o700)
    store=GeoIPStore(state,clock=lambda:1_800_000_000)
    store.upload('anything.mmdb',io.BytesIO(b'SYNTHETIC:SG'))
    return store


def link(server='8.8.8.8'):
    return LINK.replace('example.com', '['+server+']' if ':' in server else server)


@pytest.mark.parametrize('text,override,expected,source',[
    ('TW|Opaque|'+link(),None,'TW','Manual'),
    ('UNKNOWN|Opaque|'+link(),None,'UNKNOWN','Manual'),
    ('Singapore-01|'+link(),None,'SG','Name Detection'),
    ('Opaque|'+link(),None,'US','GeoIP'),
    ('Opaque|'+link('node.example.com'),None,'UNKNOWN','Unknown'),
    ('Opaque|'+link(),{'country':'TW'},'TW','Manual'),
    ('Opaque|'+link(),{'country':'UNKNOWN'},'UNKNOWN','Manual'),
    ('Opaque|'+link(),{'name':'Taiwan-01'},'TW','Name Detection'),
])
def test_priority_manual_name_geoip_unknown_and_same_display_name(database,readers,text,override,expected,source):
    database.upload('another.mmdb',io.BytesIO(b'SYNTHETIC:US'));readers['calls'].clear()
    with database.lookup('literal-ip') as lookup:
        name,node,info=parser.parse_node_line(text,override=override,country_lookup=lookup)
    assert info['code']==expected and info['source']==source
    assert name==node['name']==parser.build_display_name(expected,info['raw_name'])
    assert bool(readers['calls'])==(source=='GeoIP')


@pytest.mark.parametrize('address',['8.8.8.8','1.1.1.1','2001:4860:4860::8888','2606:4700:4700::1111'])
def test_public_ipv4_ipv6(database,readers,address):
    with database.lookup('literal-ip') as lookup:
        result=parser.parse_batch_nodes('Opaque|'+link(address),country_lookup=lookup)
    assert result['preview'][0]['country']=='SG' and result['preview'][0]['source']=='GeoIP'
    assert result['preview'][0]['status']=='Ready' and not result['errors']


@pytest.mark.parametrize('address',['node.example.com','localhost','192.168.1.1','10.0.0.1','172.16.1.1','127.0.0.1',
    '169.254.1.1','0.0.0.0','224.0.0.1','255.255.255.255','100.64.0.1','192.0.2.1','203.0.113.1',
    '::1','::','fe80::1','fc00::1','ff02::1','2001:db8::1','::ffff:8.8.8.8','fe80::1%eth0','[8.8.8.8]','1.2.3',' 8.8.8.8','8.8.8.8 ',None,True])
def test_non_global_hostname_malformed_and_scoped_addresses_never_lookup(database,readers,address):
    readers['calls'].clear()
    with database.lookup('literal-ip') as lookup: assert lookup.country(address) is None
    assert not readers['calls']


@pytest.mark.parametrize('record',[{}, {'registered_country':{'iso_code':'US'}}, {'country':None},
    {'country':{'iso_code':'ZZ'}},{'country':{'iso_code':'USA'}},{'country':{'iso_code':' U'}},
    {'country':{'iso_code':True}},{'country':{'iso_code':'UNKNOWN'}},[],None])
def test_only_valid_geographic_iso_not_registered_country(record):
    assert geoip.country_iso(record) is None
    assert geoip.country_iso({'country':{'iso_code':'tw'},'registered_country':{'iso_code':'US'}})=='TW'


def test_individual_lookup_exception_and_no_dns_network(database,readers,monkeypatch,caplog):
    def forbidden(*args,**kw):raise AssertionError('network forbidden')
    import urllib.request
    for module,key in [(socket,'socket'),(socket,'getaddrinfo'),(socket,'gethostbyname'),(urllib.request,'urlopen'),
        (source_fetch,'fetch'),(source_fetch,'_resolve')]:monkeypatch.setattr(module,key,forbidden)
    readers['error']=True
    with caplog.at_level(logging.INFO),database.lookup('literal-ip') as lookup:
        result=parser.parse_batch_nodes('Opaque|'+link()+'\nOpaque2|'+link('host.example'),country_lookup=lookup)
    assert not result['errors'] and [r['country'] for r in result['preview']]==['UNKNOWN','UNKNOWN']
    assert all(r['status']=='Warning' for r in result['preview'])
    assert '8.8.8.8' not in caplog.text and 'host.example' not in caplog.text and 'PRIVATE' not in caplog.text


@pytest.mark.parametrize('payload,format',[
    (link().encode()+b'#Opaque','raw'),
    (base64.b64encode(link().encode()+b'#Opaque'),'base64'),
    (b'proxies: [{name: Opaque, type: vless, server: 8.8.8.8, port: 443, uuid: test-only}]','clash')])
def test_raw_base64_clash_use_one_shared_reader_and_priority(database,readers,payload,format):
    before=len(readers['opened'])
    with database.lookup('literal-ip') as lookup:result=source_parser.parse(payload,format,lookup)
    assert result['countries'][0]['code']=='SG' and result['nodes'][0]['name']=='🇸🇬 Opaque'
    assert len(readers['opened'])==before+1 and readers['closed'][-1]==b'SYNTHETIC:SG'


def test_off_exact_parser_and_source_golden_no_database_reads(database,readers,monkeypatch):
    inputs=['TW|Known|'+link(),'Opaque|'+link(),'Singapore-01|'+link(),link()+'#Opaque']
    expected=[parser.parse_batch_nodes(text) for text in inputs]
    payload=link().encode()+b'#Opaque';external=source_parser.parse(payload)
    def forbidden(*args):raise AssertionError('Off must not open/read database')
    monkeypatch.setattr(database,'_snapshot',forbidden)
    with database.lookup('off') as lookup:
        assert lookup is None
        assert [parser.parse_batch_nodes(text,country_lookup=lookup) for text in inputs]==expected
        assert source_parser.parse(payload,country_lookup=lookup)==external


def test_country_name_change_keeps_connection_fingerprint_and_one_open_for_many_nodes(database,readers):
    text='\n'.join('Opaque-'+str(i)+'|'+link() for i in range(80))
    old=parser.parse_batch_nodes(text);before=len(readers['opened'])
    with database.lookup('literal-ip') as lookup:new=parser.parse_batch_nodes(text,country_lookup=lookup)
    assert len(readers['opened'])==before+1 and len(new['nodes'])==80
    assert [fingerprint(n) for n in new['nodes']]==[fingerprint(n) for n in old['nodes']]
    assert readers['closed'][-1]==b'SYNTHETIC:SG'


@pytest.mark.parametrize('value',[None,{},[],{'geoip':True},{'geoip':'dns'},{'geoip':'literal-ip','extra':True}])
def test_strict_modes(value):
    with pytest.raises(ValueError):geoip.normalize(value)
    assert geoip.defaults()=={'geoip':'off'}


def test_duplicate_form_fields_and_unknown_modes():
    assert geoip.parse_form({})==geoip.defaults()
    for form in [MultiDict([('country_geoip','off'),('country_geoip','literal-ip')]),{'country_geoip':'dns'},{'country_geoip_dns':'yes'}]:
        with pytest.raises(ValueError):geoip.parse_form(form)


@pytest.mark.parametrize('bad',[b'',b'PRIVATE-invalid',b'\xab\xcd\xefMaxMind.com',b'\0'*128])
def test_actual_reader_rejects_invalid_or_truncated_bytes(bad):
    import maxminddb
    # Call the genuine adapter even when other tests use an injected reader.
    with pytest.raises((maxminddb.InvalidDatabaseError,ValueError)):
        with io.BytesIO(bad) as stream:maxminddb.open_database(stream,maxminddb.MODE_FD)


@pytest.mark.parametrize('name,payload',[('bad.yaml',b'SYNTHETIC:TW'),('bad.mmdb',b'PRIVATE-invalid'),('empty.mmdb',b'')])
def test_invalid_upload_keeps_old_database_and_metadata(database,name,payload):
    before=(database.path.read_bytes(),database.settings.read_bytes())
    with pytest.raises(GeoIPError):database.upload(name,io.BytesIO(payload))
    assert (database.path.read_bytes(),database.settings.read_bytes())==before
    assert database.status()['status']=='Ready'


def test_upload_controls_path_and_permissions_remove_no_auto_create(database):
    database.upload('../../secret.mmdb',io.BytesIO(b'SYNTHETIC:TW'))
    assert database.path.read_bytes()==b'SYNTHETIC:TW' and database.status()['database_type']=='Synthetic-Country'
    assert database.directory.stat().st_mode&0o777==0o700 and database.path.stat().st_mode&0o777==0o600
    assert database.settings.stat().st_mode&0o777==0o600
    raw=json.loads(database.settings.read_bytes());assert raw['version']==1 and raw['geoip']['size']==12
    assert b'SYNTHETIC' not in database.settings.read_bytes() and 'country' not in raw['geoip']
    database.remove();assert not database.path.exists() and database.status()=={'status':'Not installed'}
    with database.lookup('literal-ip') as lookup:assert lookup.country('8.8.8.8') is None
    assert not database.path.exists()


@pytest.mark.parametrize('fault',['json','permissions','symlink','fifo','directory','truncated','hash','settings-permissions','settings-json','directory-permissions','busy'])
def test_corruption_unsafe_files_and_busy_fail_open_without_repair(database,fault):
    if fault in ('json','truncated'):database.path.write_bytes(b'broken')
    elif fault=='permissions':database.path.chmod(0o644)
    elif fault in ('symlink','fifo','directory'):
        database.path.unlink()
        if fault=='symlink':database.path.symlink_to(database.settings)
        elif fault=='fifo':os.mkfifo(database.path,0o600)
        else:database.path.mkdir(mode=0o700)
    elif fault=='hash':
        meta=json.loads(database.settings.read_bytes());meta['geoip']['sha256']='0'*64;write_json(database.settings,meta)
    elif fault=='settings-permissions':database.settings.chmod(0o644)
    elif fault=='settings-json':database.settings.write_bytes(b'PRIVATE broken')
    elif fault=='directory-permissions':database.directory.chmod(0o755)
    before=database.path.read_bytes() if database.path.is_file() and not database.path.is_symlink() else None
    def check():
        assert database.status()=={'status':'Unavailable / Invalid'}
        with database.lookup('literal-ip') as lookup:
            result=parser.parse_batch_nodes('Opaque|'+link(),country_lookup=lookup)
        assert not result['errors'] and result['preview'][0]['country']=='UNKNOWN'
    if fault=='busy':
        with file_lock(database.lock):check()
    else:check()
    if before is not None:assert database.path.read_bytes()==before
    if fault=='fifo':assert database.path.is_fifo()
    if fault=='symlink':assert database.path.is_symlink()


@pytest.mark.parametrize('failure',['database-before','database-after','metadata-before','metadata-after'])
def test_atomic_replacement_failure_restores_previous_pair(database,monkeypatch,failure):
    before=(database.path.read_bytes(),database.settings.read_bytes())
    original_atomic=geoip_store.atomic_write;original_json=geoip_store.write_json;failed=[]
    def atomic(path,data):
        if Path(path)==database.path and failure.startswith('database') and not failed:
            failed.append(True)
            if failure.endswith('after'):original_atomic(path,data)
            raise OSError('PRIVATE disk error')
        return original_atomic(path,data)
    def json_write(path,data):
        if failure.startswith('metadata') and not failed:
            failed.append(True)
            if failure.endswith('after'):original_json(path,data)
            raise OSError('PRIVATE disk error')
        return original_json(path,data)
    monkeypatch.setattr(geoip_store,'atomic_write',atomic);monkeypatch.setattr(geoip_store,'write_json',json_write)
    with pytest.raises(GeoIPError):database.upload('new.mmdb',io.BytesIO(b'SYNTHETIC:TW'))
    assert (database.path.read_bytes(),database.settings.read_bytes())==before and database.status()['status']=='Ready'


def test_reader_snapshot_survives_replace_and_remove(database,readers):
    with database.lookup('literal-ip') as old:
        database.upload('new.mmdb',io.BytesIO(b'SYNTHETIC:TW'))
        assert old.country('8.8.8.8')=='SG'
        with database.lookup('literal-ip') as new:assert new.country('8.8.8.8')=='TW'
        database.remove();assert old.country('8.8.8.8')=='SG'
    with database.lookup('literal-ip') as missing:assert missing.country('8.8.8.8') is None


def test_missing_database_reads_do_not_create_files(tmp_path):
    state=tmp_path/'state';state.mkdir(mode=0o700);store=GeoIPStore(state)
    assert store.status()=={'status':'Not installed'}
    with store.lookup('literal-ip') as lookup:assert lookup.country('8.8.8.8') is None
    assert list(state.iterdir())==[]


def test_pre_feature_off_parser_golden():
    import hashlib
    value=link()
    text='\n'.join(['TW|Known|'+value,'Singapore-01|'+value,'Opaque|'+value,
        'Opaque domain|'+value.replace('8.8.8.8','node.example.com'),value+'#NoCountry','bad'])
    assert hashlib.sha256(json.dumps(parser.parse_batch_nodes(text),sort_keys=True,ensure_ascii=True).encode()).hexdigest()=='87846180e8e41a305c0247e359c9a08aaa3adf31e63048080f4d06da727a6ab4'


def test_actual_adapter_uses_verified_bytes_and_closes_input_stream(monkeypatch):
    import maxminddb
    opened=[];result=object()
    def open_database(stream,mode):
        assert mode==maxminddb.MODE_FD and stream.read()==b'verified bytes'
        opened.append(stream);return result
    monkeypatch.setattr(maxminddb,'open_database',open_database)
    assert geoip.open_reader(b'verified bytes') is result and opened[0].closed


def test_oversized_upload_rejected_without_reading_unbounded_or_replacing(database):
    before=(database.path.read_bytes(),database.settings.read_bytes());requested=[]
    class Oversized:
        def read(self,size):requested.append(size);return b'x'*(geoip_store.MAX_DATABASE+1)
    with pytest.raises(GeoIPError):database.upload('big.mmdb',Oversized())
    assert requested==[geoip_store.MAX_DATABASE+1] and (database.path.read_bytes(),database.settings.read_bytes())==before


@pytest.mark.parametrize('type_name',['GeoIP2-ASN','PRIVATE://secret','Country\nPRIVATE','x'*81])
def test_invalid_metadata_types_not_exposed_or_accepted(database,monkeypatch,type_name):
    reader=SimpleNamespace(metadata=lambda:SimpleNamespace(database_type=type_name,ip_version=6),close=lambda:None)
    monkeypatch.setattr(database,'reader_factory',lambda data:reader)
    with pytest.raises(GeoIPError):database.upload('new.mmdb',io.BytesIO(b'SYNTHETIC:TW'))
    assert database.status()=={'status':'Unavailable / Invalid'}


def test_failed_remove_restores_pair(database,monkeypatch):
    before=(database.path.read_bytes(),database.settings.read_bytes())
    monkeypatch.setattr(geoip_store,'write_json',lambda *args:(_ for _ in ()).throw(OSError('PRIVATE')))
    with pytest.raises(GeoIPError):database.remove()
    assert (database.path.read_bytes(),database.settings.read_bytes())==before


def test_first_upload_metadata_failure_leaves_no_active_database(tmp_path,readers,monkeypatch):
    state=tmp_path/'state';state.mkdir(mode=0o700);database=GeoIPStore(state)
    original=geoip_store.write_json
    def fail_after_replace(path,data):original(path,data);raise OSError('PRIVATE disk error')
    monkeypatch.setattr(geoip_store,'write_json',fail_after_replace)
    with pytest.raises(GeoIPError):database.upload('country.mmdb',io.BytesIO(b'SYNTHETIC:SG'))
    assert not database.path.exists() and not database.settings.exists() and database.status()=={'status':'Not installed'}
