"""Pure conservative filtering, exact schema, freshness and identity boundaries."""
import copy
import json
import math
import socket
from pathlib import Path

import pytest
from werkzeug.datastructures import MultiDict

from core import health_policy as hp, policy_engine as policy
from core.node_identity import fingerprint
from core.node_health import fingerprint as old_api
from test_policy_engine import config as policies

NOW=1_800_000_000


def settings(**changes):
    return dict(dict(mode='exclude-unhealthy',max_age_seconds=172800,min_candidates=2),**changes)


def node(name):
    return dict(name=name,type='vless',server=name.lower()+'.example',port=443,uuid='test-only-uuid')


def observation(status='unhealthy', count=3, age=0):
    return dict(status=status,consecutive_failures=count,last_checked_at=NOW-age,
                last_success_at=1_700_000_000,latency_ms=None,error='proxy_failed')


def run(names=('A','B','C','D'), records=None, config=None, kind='fallback', special='select'):
    nodes=[node(name) for name in names]
    countries=[dict(node_name=name,group='country') for name in names]
    data={'proxies':nodes,'proxy-groups':[
        dict(name='country',type=kind,proxies=list(names)),
        dict(name='media',type=special,proxies=list(names)),
        dict(name='🚀 手动切换',type='select',proxies=list(names)),
        dict(name='custom',type='fallback',proxies=list(names))], 'rules':['MATCH,country']}
    before=copy.deepcopy(data)
    result=hp.apply(data,nodes,countries,['media'],policy.normalize(policies(kind,special)),
        config or settings(),dict(available=True,records={fingerprint(node(k)):v for k,v in (records or {}).items()}),NOW)
    return data,result,before


@pytest.mark.parametrize('kind',policy.AUTOMATIC)
def test_fresh_confirmed_unhealthy_only_retained_order_select_and_top_proxies(kind):
    data,result,before=run(records={'B':observation()},kind=kind)
    assert data['proxy-groups'][0]['proxies']==['A','C','D']
    assert result['groups_filtered']==1 and result['candidates_excluded']==1 and result['groups_fail_open']==0
    assert data['proxies']==before['proxies'] and data['rules']==before['rules']
    assert data['proxy-groups'][1:]==before['proxy-groups'][1:]


@pytest.mark.parametrize('status,count', [('healthy',0),('suspect',1),('suspect',2),('unknown',0),('unsupported',3),('unhealthy',1),('unhealthy',2)])
def test_conservative_status_and_confirmed_failure_threshold(status,count):
    data,result,before=run(records={'B':observation(status,count)})
    assert data==before and result['candidates_excluded']==0


@pytest.mark.parametrize('age,excluded',[(-1,False),(-60,False),(-86400,False),(0,True),(172799,True),(172800,True),(172801,False)])
def test_freshness_exact_boundary_and_future_clock_fail_open(age,excluded):
    data,result,before=run(records={'B':observation(age=age)})
    assert ('B' not in data['proxy-groups'][0]['proxies'])==excluded


@pytest.mark.parametrize('checked',[None,True,float('nan'),float('inf'),'1800000000',-1,253402300800])
def test_invalid_timestamp_is_never_confirmed_fresh(checked):
    record=observation();record['last_checked_at']=checked
    data,result,before=run(records={'B':record})
    assert data==before


def test_last_checked_not_last_success_controls_freshness_and_latency_never_ranks():
    record=observation();record['last_success_at']=None;record['latency_ms']=0
    data,_,_=run(records={'B':record,'A':observation('healthy',0),'D':observation('suspect',1)})
    assert data['proxy-groups'][0]['proxies']==['A','C','D']


@pytest.mark.parametrize('names,dead,minimum,expected,failopen',[
    (('A','B','C'),('B','C'),2,['A','B','C'],1),
    (('A','B','C','D'),('B',),2,['A','C','D'],0),
    (('A',),('A',),2,['A'],1),
    (('A','B'),('B',),1,['A'],0),
    (('A','B'),('B',),16,['A','B'],1),
    (('A','B','C'),('A','B','C'),1,['A','B','C'],1)])
def test_effective_minimum_and_per_group_fail_open(names,dead,minimum,expected,failopen):
    data,result,_=run(names=names,records={n:observation() for n in dead},config=settings(min_candidates=minimum))
    assert data['proxy-groups'][0]['proxies']==expected and result['groups_fail_open']==failopen


def test_fail_open_is_per_group_and_counts_are_membership_counts():
    nodes=[node(n) for n in ['TW-A','TW-B','TW-C','US-A','US-B']]
    country=[dict(node_name=n['name'],group='TW' if n['name'].startswith('TW') else 'US') for n in nodes]
    data={'proxy-groups':[dict(name='TW',type='url-test',proxies=['TW-A','TW-B','TW-C']),
        dict(name='US',type='url-test',proxies=['US-A','US-B']),dict(name='media',type='fallback',proxies=[n['name'] for n in nodes])]}
    health=dict(available=True,records={fingerprint(node(n)):observation() for n in ['TW-B','US-B']})
    result=hp.apply(data,nodes,country,['media'],policy.normalize(policies('url-test','fallback')),settings(),health,NOW)
    assert data['proxy-groups'][0]['proxies']==['TW-A','TW-C']
    assert data['proxy-groups'][1]['proxies']==['US-A','US-B']
    assert data['proxy-groups'][2]['proxies']==['TW-A','TW-C','US-A']
    assert result['groups_filtered']==2 and result['candidates_excluded']==3 and result['groups_fail_open']==1


@pytest.mark.parametrize('mode',['off','exclude-unhealthy'])
@pytest.mark.parametrize('kind',['preserve','select'])
def test_preserve_select_and_off_do_not_change_membership(mode,kind):
    data,result,before=run(records={'B':observation()},config=settings(mode=mode),kind=kind,special=kind)
    assert data==before


def test_missing_observation_retained_and_name_change_uses_same_identity():
    assert fingerprint(node('B'))==old_api(node('B'))
    renamed=dict(node('B'),name='renamed')
    assert fingerprint(renamed)==fingerprint(node('B'))
    assert fingerprint(dict(renamed,uuid='changed'))!=fingerprint(node('B'))
    data,result,before=run(records={})
    assert data==before


@pytest.mark.parametrize('bad',[None,[],{},dict(settings(),extra=True),dict(settings(),fail_closed=True),
    settings(mode='unknown'),settings(mode=True),settings(mode=[]),settings(max_age_seconds=True),
    settings(max_age_seconds=172800.0),settings(max_age_seconds='172800'),settings(max_age_seconds=0),
    settings(max_age_seconds=172801),settings(max_age_seconds=float('nan')),
    settings(max_age_seconds=float('inf')),settings(min_candidates=True),settings(min_candidates=2.0),
    settings(min_candidates='2'),settings(min_candidates=0),settings(min_candidates=17),settings(min_candidates=None)])
def test_strict_health_config(bad):
    with pytest.raises(ValueError,match='Health-aware Policy settings are invalid'):hp.normalize(bad)


@pytest.mark.parametrize('age',hp.AGES)
@pytest.mark.parametrize('minimum',[1,2,16])
def test_every_supported_freshness_and_minimum(age,minimum):
    assert hp.normalize(settings(max_age_seconds=age,min_candidates=minimum))==settings(max_age_seconds=age,min_candidates=minimum)


@pytest.mark.parametrize('fields',[dict(health_policy_mode='unknown'),dict(health_policy_max_age_seconds='172800.0'),
    dict(health_policy_max_age_seconds='-1'),dict(health_policy_min_candidates='2e0'),
    dict(health_policy_min_candidates=' true'),dict(health_policy_fail_closed='true')])
def test_invalid_forms_not_coerced(fields):
    with pytest.raises(ValueError):hp.parse_form(fields)


def test_duplicate_form_values_and_defaults():
    assert hp.parse_form({})==hp.defaults()==dict(mode='off',max_age_seconds=172800,min_candidates=2)
    with pytest.raises(ValueError):hp.parse_form(MultiDict([('health_policy_mode','off'),('health_policy_mode','exclude-unhealthy')]))


def test_safe_audit_no_names_endpoints_or_credentials():
    _,summary,_=run(records={'B':observation()})
    serialized=json.dumps(hp.finish(summary,True))
    assert 'b.example' not in serialized and 'test-only-uuid' not in serialized
    assert hp.valid_audit(hp.finish(summary,True))
    assert not hp.valid_audit(dict(summary,groups_filtered=True))
    assert not hp.valid_audit(dict(summary,result='PRIVATE'))
