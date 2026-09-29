"""Offline pinned-controller contract and bounded process-lifecycle checks."""
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import threading
import time

import pytest
from ruamel.yaml import YAML

from core import mihomo_probe as probe
from core.proxy_health import DEFAULT_PROBE


def node(index,server='public.example'):
    return dict(fingerprint=f'{index:064x}',name='SECRET-original-node-name',
                config=dict(name='SECRET-original-node-name',type='vless',server=server,port=443,
                            uuid='11111111-1111-4111-8111-111111111111'))


def test_minimal_config_opaque_alias_private_file_and_no_listeners(tmp_path):
    work=tmp_path/'private'; work.mkdir(mode=0o700)
    config=probe.write_config(work,[node(1),node(2)],34567,'PRIVATE-random-secret')
    assert config.stat().st_mode & 0o777==0o600
    data=YAML(typ='safe').load(config.read_bytes())
    assert set(data)=={'log-level','allow-lan','geo-auto-update','external-controller','secret','proxies'}
    assert data['external-controller']=='127.0.0.1:34567'
    assert data['secret']=='PRIVATE-random-secret'
    assert [p['name'] for p in data['proxies']]==['probe-0001','probe-0002']
    assert b'SECRET-original-node-name' not in config.read_bytes()
    for forbidden in ('rules','tun','mixed-port','socks-port','port','proxy-providers',
                      'rule-providers','dns','listeners','external-ui','sniffer'):
        assert forbidden not in data


def test_controller_contract_requires_auth_and_uses_localhost(monkeypatch):
    class FakeResponse:
        status=200
        def read(self,limit):
            return b'{"version":"v1.19.31"}'
    class FakeConnection:
        def __init__(self,host,port,timeout):
            assert host=='127.0.0.1' and port==32123 and 0<timeout<=1
        def request(self,method,path,headers):
            assert method=='GET' and path=='/version'
            assert headers=={'Authorization':'Bearer SECRET'}
        def getresponse(self): return FakeResponse()
        def close(self): pass
    monkeypatch.setattr(probe.http.client,'HTTPConnection',FakeConnection)
    assert probe.controller(32123,'SECRET','/version',.5)==(200,{'version':'v1.19.31'})


@pytest.mark.parametrize('delay_status,alive,expected_kind,expected_error',[
    (200,True,'success',None),(200,False,'failure','probe_status_mismatch'),
    (503,True,'failure','proxy_failed'),(504,True,'failure','timeout'),
])
def test_delay_api_status_and_extra_alive_semantics(monkeypatch,delay_status,alive,expected_kind,expected_error):
    paths=[]
    def controller(port,secret,path,timeout):
        paths.append(path)
        assert port==32123 and secret=='SECRET' and timeout>0
        if path.endswith('/delay?url=https%3A%2F%2Fwww.gstatic.com%2Fgenerate_204&timeout=8000&expected=204'):
            return delay_status, {'delay':38} if delay_status==200 else {'error':'PRIVATE'}
        if path=='/proxies/probe-0001':
            return 200, {'extra':{DEFAULT_PROBE['url']:{'alive':alive,'history':[]}}}
        if path=='/version': return 200, {'version':'v1.19.31'}
        raise AssertionError(path)
    monkeypatch.setattr(probe,'controller',controller)
    result=probe.probe_one(32123,'SECRET','probe-0001',DEFAULT_PROBE,time.monotonic()+30)
    assert result['kind']==expected_kind and result['error']==expected_error
    if expected_kind=='success': assert result['latency_ms']==38
    assert not any('PRIVATE' in part for part in paths)


@pytest.mark.parametrize('response',[(200,{'delay':'38'}),(200,{'delay':0}),(404,{}),(200,[])])
def test_malformed_controller_result_is_engine_error(monkeypatch,response):
    monkeypatch.setattr(probe,'controller',lambda *a:response)
    with pytest.raises(probe.ProbeEngineError):
        probe.probe_one(32123,'SECRET','probe-0001',DEFAULT_PROBE,time.monotonic()+30)


def test_controller_dies_during_node_error_is_engine_error(monkeypatch):
    def controller(port,secret,path,timeout):
        if path=='/version': raise ConnectionRefusedError
        return 503, {'error':'PRIVATE'}
    monkeypatch.setattr(probe,'controller',controller)
    with pytest.raises(probe.ProbeEngineError):
        probe.probe_one(32123,'SECRET','probe-0001',DEFAULT_PROBE,time.monotonic()+30)


def test_validation_bisects_one_and_multiple_unsupported(monkeypatch,tmp_path):
    sizes=[]
    def validate(binary,work,nodes,port,secret,deadline):
        sizes.append(len(nodes))
        return all(n['config']['server']!='invalid.example' for n in nodes)
    monkeypatch.setattr(probe,'validate',validate)
    nodes=[node(i,'invalid.example' if i in (17,49) else 'public.example') for i in range(1,65)]
    valid,unsupported=probe.isolate(Path('/fake'),tmp_path,nodes,12345,'secret',time.monotonic()+10)
    assert len(valid)==62 and [n['fingerprint'] for n in unsupported]==[nodes[16]['fingerprint'],nodes[48]['fingerprint']]
    assert sizes[0]==64 and max(sizes)==64 and len(sizes)<30
    assert all(n['config']['server']=='public.example' for n in valid)


@pytest.mark.parametrize('count,batches',[(1,[1]),(64,[64]),(65,[64,1]),(128,[64,64]),
    (200,[64,64,64,8]),(256,[64,64,64,64])])
def test_batches_are_sequential_and_at_most_64(monkeypatch,tmp_path,count,batches):
    calls=[]
    def run_batch(binary,nodes,settings,state,deadline):
        calls.append(len(nodes))
        return {n['fingerprint']:dict(kind='success',error=None,latency_ms=1) for n in nodes}
    monkeypatch.setattr(probe,'run_batch',run_batch)
    result=probe.run(Path('/fake'),[node(i) for i in range(count)],DEFAULT_PROBE,tmp_path)
    assert calls==batches and len(result)==count
    with pytest.raises(probe.ProbeEngineError):
        probe.run(Path('/fake'),[node(i) for i in range(257)],DEFAULT_PROBE,tmp_path)
    assert calls==batches


class FakeProcess:
    def __init__(self,pid=12345):
        self.pid=pid; self.running=True; self.wait_calls=0
    def poll(self): return None if self.running else 0
    def wait(self,timeout):
        self.wait_calls+=1
        if self.running: raise subprocess.TimeoutExpired(['fixture'],timeout)
        return 0


def test_sigterm_then_sigkill_and_reap(monkeypatch):
    process=FakeProcess(); signals=[]
    def killpg(pid,which):
        assert pid==process.pid
        signals.append(which)
        if which==signal.SIGKILL: process.running=False
    monkeypatch.setattr(probe.os,'killpg',killpg)
    probe.stop_process(process)
    assert signals==[signal.SIGTERM,signal.SIGKILL] and process.wait_calls==2


def test_readiness_rejects_early_process_exit():
    process=FakeProcess(); process.running=False
    assert probe.ready(process,32123,'SECRET',time.monotonic()+1) is False


def test_normal_subprocess_start_group_bounded_output_and_cleanup(tmp_path):
    script=tmp_path/'fake-engine'
    script.write_text('#!/bin/sh\nprintf "PRIVATE secret output\\n"\nsleep 30\n')
    script.chmod(0o755)
    process,output=probe.command(script,tmp_path,tmp_path/'config.yaml')
    try:
        assert process.pid>0 and process.poll() is None
        until=time.monotonic()+3
        while not output.buffer and time.monotonic()<until:
            time.sleep(.01)
    finally:
        probe.stop_process(process); output.finish()
    assert process.poll() is not None and len(output.buffer)<=16*1024
    assert b'PRIVATE secret output' in output.buffer


@pytest.fixture
def fake_batch(monkeypatch):
    state=dict(ready=[],ports=[],secrets=[],stopped=[],runtime=0)
    monkeypatch.setattr(probe,'validate',lambda binary,work,nodes,port,secret,deadline:True)
    def fake_port():
        value=32000+len(state['ports']); state['ports'].append(value); return value
    monkeypatch.setattr(probe,'random_port',fake_port)
    class Output:
        def finish(self): pass
    def command(binary,work,config,test=False):
        assert not test and Path(config).stat().st_mode & 0o777==0o600
        data=YAML(typ='safe').load(Path(config).read_bytes())
        state['secrets'].append(data['secret'])
        state['runtime']+=1
        return FakeProcess(20000+state['runtime']),Output()
    monkeypatch.setattr(probe,'command',command)
    def stop(process):
        if process:
            state['stopped'].append(process.pid); process.running=False
    monkeypatch.setattr(probe,'stop_process',stop)
    return state


def test_port_collision_bounded_retry_and_temp_cleanup(monkeypatch,tmp_path,fake_batch):
    attempts=[]
    def readiness(process,port,secret,deadline):
        attempts.append(port)
        return len(attempts)==5
    monkeypatch.setattr(probe,'ready',readiness)
    monkeypatch.setattr(probe,'probe_one',lambda *a:dict(kind='success',error=None,latency_ms=7))
    result=probe.run_batch(Path('/fake'),[node(1)],DEFAULT_PROBE,tmp_path,time.monotonic()+200)
    assert len(attempts)==5 and len(set(attempts))==5
    assert result[node(1)['fingerprint']]['latency_ms']==7
    assert len(fake_batch['stopped'])==5 and not list(tmp_path.glob('.proxy-probe-*'))
    assert len(set(fake_batch['secrets']))==1 and len(fake_batch['secrets'][0])>=43


def test_controller_start_failure_is_engine_error_and_cleans_temp(monkeypatch,tmp_path,fake_batch):
    monkeypatch.setattr(probe,'ready',lambda *a:False)
    with pytest.raises(probe.ProbeEngineError,match='startup failed'):
        probe.run_batch(Path('/fake'),[node(1)],DEFAULT_PROBE,tmp_path,time.monotonic()+200)
    assert fake_batch['runtime']==5 and len(fake_batch['stopped'])==5
    assert not list(tmp_path.glob('.proxy-probe-*'))


def test_temp_cleanup_even_if_process_stop_fails(monkeypatch,tmp_path,fake_batch):
    monkeypatch.setattr(probe,'ready',lambda *a:True)
    monkeypatch.setattr(probe,'probe_one',lambda *a:dict(kind='success',error=None,latency_ms=2))
    monkeypatch.setattr(probe,'stop_process',lambda process: (_ for _ in ()).throw(
        probe.ProbeEngineError('Proxy probe process cleanup failed.')))
    with pytest.raises(probe.ProbeEngineError,match='cleanup failed'):
        probe.run_batch(Path('/fake'),[node(1)],DEFAULT_PROBE,tmp_path,time.monotonic()+200)
    assert not list(tmp_path.glob('.proxy-probe-*'))


def test_controller_exit_after_responses_is_engine_error(monkeypatch,tmp_path,fake_batch):
    monkeypatch.setattr(probe,'ready',lambda *a:True)
    def answer(*args):
        fake_batch['last_process'].running=False
        return dict(kind='success',error=None,latency_ms=2)
    original=probe.command
    def command(*args,**kwargs):
        process, output=original(*args,**kwargs)
        fake_batch['last_process']=process
        return process, output
    monkeypatch.setattr(probe,'command',command)
    monkeypatch.setattr(probe,'probe_one',answer)
    with pytest.raises(probe.ProbeEngineError,match='controller unavailable'):
        probe.run_batch(Path('/fake'),[node(1)],DEFAULT_PROBE,tmp_path,time.monotonic()+200)
    assert not list(tmp_path.glob('.proxy-probe-*'))


def test_16_concurrent_probes_and_unique_secret_per_batch(monkeypatch,tmp_path,fake_batch):
    monkeypatch.setattr(probe,'ready',lambda *a:True)
    started,resume=threading.Event(),threading.Event()
    lock=threading.Lock(); active=0; maximum=0
    def slow(*args):
        nonlocal active,maximum
        with lock:
            active+=1; maximum=max(maximum,active)
            if active==16: started.set()
        assert resume.wait(5)
        with lock: active-=1
        return dict(kind='success',error=None,latency_ms=2)
    monkeypatch.setattr(probe,'probe_one',slow)
    errors=[]
    def run():
        try: probe.run_batch(Path('/fake'),[node(i) for i in range(32)],DEFAULT_PROBE,tmp_path,time.monotonic()+200)
        except BaseException as error: errors.append(error)
    thread=threading.Thread(target=run); thread.start()
    try: assert started.wait(3)
    finally: resume.set(); thread.join(6)
    assert not errors and maximum==16
    assert len(fake_batch['stopped'])==1 and not list(tmp_path.glob('.proxy-probe-*'))
    monkeypatch.setattr(probe,'probe_one',lambda *a:dict(kind='success',error=None,latency_ms=1))
    probe.run_batch(Path('/fake'),[node(33)],DEFAULT_PROBE,tmp_path,time.monotonic()+200)
    assert len(set(fake_batch['secrets']))==2
