"""Offline supply-chain and optional-engine tests; no real /opt or root account."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from core.mihomo_manager import (EngineError, ExecutionError, ManagedMihomo, VERSION,
                                 detect_amd64_level)
from conftest import ROOT
from test_deployment import deployment


def digest(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def managed(tmp_path):
    root = tmp_path / 'app'; root.mkdir()
    binaries = {}
    manifest = dict(version=VERSION, platforms={}, legacy={})
    for key, machine in (("amd64-v1",62),("amd64-v2",62),("amd64-v3",62),("arm64",183),("amd64",62)):
        elf = bytearray(64)
        elf[:4] = b'\x7fELF'; elf[4] = 2; elf[5] = 1
        elf[18:20] = machine.to_bytes(2,'little')
        elf.extend(b'controlled fixture ' + key.encode())
        archive = gzip.compress(bytes(elf))
        asset = f'mihomo-linux-{key}-{VERSION}.gz'
        binaries[key] = archive
        section = 'legacy' if key == 'amd64' else 'platforms'
        manifest[section]['linux-'+key] = dict(asset=asset,
            url=f'https://github.com/MetaCubeX/mihomo/releases/download/{VERSION}/{asset}',
            sha256=digest(archive),binary_sha256=digest(elf),size=len(archive))
    (root/'mihomo-manifest.json').write_text(json.dumps(manifest))
    def make(arch='amd64', downloader=None, version=None, replacer=None, cpuinfo='processor : 0\nflags : sse sse2'):
        machine = 'x86_64' if arch == 'amd64' else 'aarch64'
        def download(url,destination,maximum):
            key = next(key.removeprefix('linux-') for key,spec in manifest['platforms'].items()
                       if spec['url'] == url)
            assert maximum == len(binaries[key])
            Path(destination).write_bytes(binaries[key])
        manager = ManagedMihomo(root,system='linux',machine=machine,owner_uid=os.getuid(),
            owner_gid=os.getgid(),downloader=downloader or download,
            version_runner=version or (lambda path:f'Mihomo Meta {VERSION} linux {arch} with go1.25'),
            replacer=replacer, cpuinfo_text=cpuinfo)
        manager._require_root = lambda:None
        return manager
    return root, manifest, binaries, make


def test_release_manifest_matches_independently_downloaded_asset_hashes_and_architecture():
    value = json.loads((ROOT/'mihomo-manifest.json').read_text())
    assert value['version'] == VERSION
    assert value['legacy']['linux-amd64']['sha256'] == 'd5e74bbddbdfff49a1aef7775bf5911da59f0d7196ed509a0ac914b3653dd5f1'
    expected = {
        'v1': ('d4304c546c3cddcb6fafd4b4fddb0ba1a95ffa36606fda56d75db2e59ad24114', '12d97b7b7fa22cb4456e62c6e35db4be952dbb1c53eacaa9ef437c95d5068a9d', 22821828),
        'v2': ('560a14ba51482e85e90b6c9b141f3b7b1543795f9ecd82eb9a6c5153a1b7960b', '8a9d3e867c422605bb61f572636f1e50b05c16f6b78b4eabff9857947ad2eb35', 22805792),
        'v3': ('4e8808e79f1e452a0300ce1ee89fcaf2cccd5249a100f2238877214e5ca316b3', '81d4e533a66d17b8ac12b92e1891d681d2a34c788dfaf57f8b1bd0bb22a34cec', 22789796),
    }
    for level, pins in expected.items():
        spec = value['platforms']['linux-amd64-'+level]
        assert (spec['sha256'],spec['binary_sha256'],spec['size']) == pins
    assert value['platforms']['linux-arm64']['sha256'] == '9e0f11afbf38426b8bd88fdc594678f8161c57eccb4e1b77acb12b493904f1d4'
    assert all('/releases/download/v1.19.31/' in part['url'] and '/latest/' not in part['url']
               for part in value['platforms'].values())


@pytest.mark.parametrize('arch',['amd64','arm64'])
def test_install_status_remove_exact_asset_and_ownership(managed,arch):
    root, manifest, _, make = managed
    manager = make(arch)
    assert manager.status()['status'] == 'NOT INSTALLED'
    manager.install()
    level = 'v1' if arch == 'amd64' else None
    build = 'amd64-v1' if arch == 'amd64' else 'arm64'
    assert manager.status() == dict(status='COMPATIBLE',required=VERSION,installed=VERSION,architecture=arch,
                                   cpu_level=level,build=build,preferred_build=build)
    assert manager.binary.stat().st_mode & 0o777 == 0o755
    assert manager.metadata.stat().st_mode & 0o777 == 0o644
    assert manager.binary.stat().st_uid == manager.metadata.stat().st_uid == os.getuid()
    metadata = json.loads(manager.metadata.read_text())
    assert metadata['archive_sha256'] == manifest['platforms']['linux-'+build]['sha256']
    manager.remove()
    assert manager.status()['status'] == 'NOT INSTALLED'
    assert manager.directory.is_dir() and not manager.binary.exists()


@pytest.mark.parametrize('machine',['mips','i386'])
def test_unsupported_arch_rejected_without_mutation(managed,machine):
    root, _, _, make = managed
    manager = make()
    manager.machine = machine; manager.arch = None
    with pytest.raises(EngineError,match='Unsupported'):
        manager.install()
    assert not manager.directory.exists()


def test_bad_download_hash_and_bad_gzip_keep_old_binary(managed):
    _, manifest, _, make = managed
    manager = make(); manager.install()
    before = (manager.binary.read_bytes(),manager.metadata.read_bytes())
    with pytest.raises(EngineError,match='checksum'):
        make(downloader=lambda u,d,m:Path(d).write_bytes(b'x'*m)).install()
    assert (manager.binary.read_bytes(),manager.metadata.read_bytes()) == before
    archive = b'not gzip'
    spec = manifest['platforms']['linux-amd64-v1']
    spec.update(sha256=digest(archive),size=len(archive))
    (manager.root/'mihomo-manifest.json').write_text(json.dumps(manifest))
    bad = make(downloader=lambda u,d,m:Path(d).write_bytes(archive))
    with pytest.raises(EngineError,match='install failed'):
        bad.install()
    assert (manager.binary.read_bytes(),manager.metadata.read_bytes()) == before


def test_wrong_version_and_failed_second_replace_preserve_existing(managed):
    _, _, _, make = managed
    manager = make(); manager.install()
    before = (manager.binary.read_bytes(),manager.metadata.read_bytes())
    wrong = make(version=lambda path:'Mihomo Meta v1.19.30 linux amd64 with go')
    with pytest.raises(EngineError,match='version mismatch'):
        wrong.install()
    assert (manager.binary.read_bytes(),manager.metadata.read_bytes()) == before
    calls = []
    def fail_second(src,dst):
        calls.append((src,dst))
        if len(calls) == 2:
            raise OSError('PRIVATE replacement error')
        os.replace(src,dst)
    with pytest.raises(EngineError,match='previous component preserved'):
        make(replacer=fail_second).install()
    assert (manager.binary.read_bytes(),manager.metadata.read_bytes()) == before
    assert manager.status()['status'] == 'COMPATIBLE'


def test_engine_status_broken_and_incompatible_cases(managed):
    _, _, _, make = managed
    manager = make(); manager.install()
    original = manager.binary.read_bytes()
    metadata = json.loads(manager.metadata.read_text())
    metadata['version'] = 'v1.19.30'; manager.metadata.write_text(json.dumps(metadata))
    assert manager.status()['status'] == 'INCOMPATIBLE'
    manager.metadata.write_text('PRIVATE invalid json')
    assert manager.status()['status'] == 'BROKEN'
    manager.metadata.unlink(); manager.install()
    manager.binary.write_bytes(original + b'drift')
    assert manager.status()['status'] == 'BROKEN'
    manager.binary.write_bytes(original); manager.binary.chmod(0o777)
    assert manager.status()['status'] == 'BROKEN'
    manager.binary.chmod(0o755); manager.binary.unlink(); manager.binary.symlink_to(manager.metadata)
    assert manager.status()['status'] == 'BROKEN'
    manager.binary.unlink(); manager.install()
    assert make(version=lambda path:(_ for _ in ()).throw(subprocess.TimeoutExpired(['mihomo'],3))).status()['status'] == 'BROKEN'
    assert make(version=lambda path:(_ for _ in ()).throw(EngineError('PRIVATE crash'))).status()['status'] == 'BROKEN'
    manager.owner_uid = os.getuid()+1
    assert manager.status()['status'] == 'BROKEN'


def test_unsafe_existing_binary_rejected(managed):
    _, _, _, make = managed
    manager = make(); manager.directory.mkdir(mode=0o755)
    manager.binary.symlink_to(manager.root/'mihomo-manifest.json')
    with pytest.raises(EngineError,match='unsafe'):
        manager.install()
    assert manager.binary.is_symlink()


def test_main_update_preserves_managed_binary_and_metadata(deployment):
    installed, source, _, _, _, run = deployment
    for root, binary in ((installed,b'installed-engine'),(source,b'UNTRUSTED-source-engine')):
        directory = root/'bin'; directory.mkdir()
        (directory/'mihomo').write_bytes(binary)
        (directory/'mihomo.json').write_text('{"version":"v1.19.31"}')
        (directory/'.mihomoctl.lock').write_bytes(b'')
        (directory/'.mihomoctl.lock').chmod(0o600)
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert (installed/'bin/mihomo').read_bytes() == b'installed-engine'
    assert (installed/'bin/mihomo.json').read_text() == '{"version":"v1.19.31"}'
    assert (installed/'bin/.mihomoctl.lock').stat().st_mode & 0o777 == 0o600
    assert (installed/'mihomoctl.sh').exists()
    assert (installed/'mihomo-manifest.json').exists()


# Independent fixtures from the Go runtime requirements and Linux flag names;
# do not derive test expectations from the detector's feature constants.
V2_FLAGS = frozenset('cx16 lahf_lm popcnt pni ssse3 sse4_1 sse4_2'.split())
V3_FLAGS = V2_FLAGS | frozenset('avx avx2 bmi1 bmi2 fma f16c abm movbe xsave'.split())


def cpuinfo(*flags, model='Intel Xeon SierraForest'):
    return '\n\n'.join(f'processor : {i}\nmodel name : {model}\nflags : ' + ' '.join(sorted(values))
                       for i,values in enumerate(flags))


TIM_FLAGS = frozenset('fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pat pse36 clflush mmx fxsr sse sse2 ht syscall nx pdpe1gb rdtscp lm constant_tsc rep_good nopl xtopology cpuid tsc_known_freq pni pclmulqdq ssse3 cx16 pcid sse4_1 sse4_2 x2apic popcnt tsc_deadline_timer aes xsave avx f16c rdrand hypervisor lahf_lm cpuid_fault pti ssbd ibrs ibpb fsgsbase smep erms xsaveopt arat umip arch_capabilities'.split())


@pytest.mark.parametrize('flags,level', [(frozenset({'sse','sse2'}),'v1'), (V2_FLAGS,'v2'),
                                        (TIM_FLAGS,'v2'), (V3_FLAGS,'v3')])
def test_cpu_level_and_explicit_pinned_selection(managed, flags, level):
    _, _, _, make = managed
    text = cpuinfo(flags)
    assert detect_amd64_level(text) == level
    manager = make(cpuinfo=text); manager.install()
    metadata = json.loads(manager.metadata.read_text())
    assert metadata['cpu_level'] == level
    assert metadata['asset'] == f'mihomo-linux-amd64-{level}-{VERSION}.gz'
    assert manager.status()['build'] == 'amd64-' + level


@pytest.mark.parametrize('missing', sorted(V2_FLAGS))
def test_every_go_v2_required_linux_flag_is_required(missing):
    assert detect_amd64_level(cpuinfo(V3_FLAGS - {missing})) == 'v1'


@pytest.mark.parametrize('missing', sorted(V3_FLAGS - V2_FLAGS))
def test_every_go_v3_requirement_including_f16c_and_os_vector_support(missing):
    assert detect_amd64_level(cpuinfo(V3_FLAGS - {missing})) == 'v2'


def test_cpu_intersection_ignores_model_and_hypervisor_claims():
    assert detect_amd64_level(cpuinfo(V3_FLAGS, TIM_FLAGS)) == 'v2'
    assert detect_amd64_level(cpuinfo(TIM_FLAGS, V3_FLAGS)) == 'v2'
    assert detect_amd64_level(cpuinfo(V3_FLAGS, {'sse','sse2'})) == 'v1'
    assert detect_amd64_level(cpuinfo(V3_FLAGS - {'avx2'}, V3_FLAGS - {'bmi2'})) == 'v2'
    assert detect_amd64_level(cpuinfo(V3_FLAGS, V3_FLAGS)) == 'v3'
    assert detect_amd64_level(cpuinfo(V3_FLAGS, model='ancient unknown CPU')) == 'v3'
    # Linux does not print an osxsave flag; AVX+XSAVE is the kernel-enabled signal.
    assert 'osxsave' not in V3_FLAGS
    assert detect_amd64_level(cpuinfo(V3_FLAGS | {'osxsave'})) == 'v3'


@pytest.mark.parametrize('text', [None, 123, '', 'not cpuinfo', 'flags: '+ ' '.join(V3_FLAGS),
    'processor: 0\nmodel name: Modern CPU', 'processor: 0\nflags:',
    'processor: 0\nflags: avx\nflags: avx2', 'processor: x\nflags: avx',
    'processor: 0\nflags: AVX', 'processor: 0\nflags: avx\nfeatures: avx',
    cpuinfo(V3_FLAGS) + '\n\nprocessor: 1\nmodel name: masked CPU',
    cpuinfo(V3_FLAGS) + '\n\n' + cpuinfo(V3_FLAGS),
    cpuinfo(V3_FLAGS) + '\nmalformed line'])
def test_unknown_or_incomplete_cpuinfo_uses_portable_v1(text):
    assert detect_amd64_level(text) == 'v1'


@pytest.mark.parametrize('failure', [FileNotFoundError, PermissionError, UnicodeError])
def test_proc_cpuinfo_read_failure_is_local_v1(managed, monkeypatch, failure):
    import builtins
    root, _, _, _ = managed
    original = builtins.open
    def read(path, *args, **kwargs):
        if str(path) == '/proc/cpuinfo':
            raise failure('private')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(builtins, 'open', read)
    manager = ManagedMihomo(root,system='linux',machine='x86_64')
    assert manager.cpu_level == 'v1'


@pytest.mark.parametrize('preferred,failed,chosen', [('v3',{'v3'},'v2'), ('v2',{'v2'},'v1'),
                                                    ('v3',{'v3','v2'},'v1')])
@pytest.mark.parametrize('failure', ['sigill','nonzero','timeout','execerror'])
def test_verified_execution_failure_tries_only_lower_pinned_builds(managed, preferred, failed, chosen, failure):
    _, _, binaries, make = managed
    attempted = []
    def version(path):
        level = next(key.removeprefix('amd64-') for key,archive in binaries.items()
                     if key.startswith('amd64-') and gzip.decompress(archive) == path.read_bytes())
        attempted.append(level)
        if level in failed:
            if failure == 'timeout':
                raise subprocess.TimeoutExpired(['PRIVATE'],3)
            if failure == 'execerror':
                raise OSError('PRIVATE runtime failure')
            raise subprocess.CalledProcessError(-4 if failure == 'sigill' else 1, ['PRIVATE'])
        return f'Mihomo Meta {VERSION} linux amd64 with go'
    manager = make(cpuinfo=cpuinfo(V3_FLAGS if preferred == 'v3' else TIM_FLAGS),version=version)
    manager.install()
    assert attempted == (['v3','v2'] if chosen == 'v2' else ['v3','v2','v1'] if preferred == 'v3' else ['v2','v1']) + [chosen]
    assert json.loads(manager.metadata.read_text())['cpu_level'] == chosen
    status = manager.status()
    assert status['status'] == 'COMPATIBLE' and status['build'] == 'amd64-' + chosen
    assert status['cpu_level'] == preferred and status['preferred_build'] == 'amd64-' + preferred
    assert not list(manager.directory.glob('.mihomo-install-*'))


def test_all_execution_candidates_fail_preserves_both_old_files(managed):
    _, _, binaries, make = managed
    manager = make(); manager.install()
    before = manager.binary.read_bytes(), manager.metadata.read_bytes()
    attempts = []
    def fail(path):
        attempts.append(path.read_bytes())
        assert (manager.binary.read_bytes(),manager.metadata.read_bytes()) == before
        raise ExecutionError('PRIVATE execution failure')
    with pytest.raises(EngineError, match='all pinned builds') as error:
        make(cpuinfo=cpuinfo(V3_FLAGS),version=fail).install()
    assert 'PRIVATE' not in str(error.value)
    assert attempts == [gzip.decompress(binaries['amd64-'+level]) for level in ('v3','v2','v1')]
    assert (manager.binary.read_bytes(),manager.metadata.read_bytes()) == before
    assert not list(manager.directory.glob('.mihomo-install-*'))


@pytest.mark.parametrize('fault', ['compressed_hash','binary_hash','gzip','elf','size','download','wrong_version','unknown_version','output_error'])
def test_supply_chain_and_unknown_version_errors_never_downgrade(managed, fault):
    root, manifest, binaries, make = managed
    manager = make(); manager.install()
    before = manager.binary.read_bytes(),manager.metadata.read_bytes()
    spec = manifest['platforms']['linux-amd64-v3']
    archive = binaries['amd64-v3']
    if fault == 'binary_hash': spec['binary_sha256'] = '0'*64
    if fault in ('gzip','elf'):
        data = b'not gzip' if fault == 'gzip' else gzip.compress(b'not ELF')
        archive = data
        spec.update(size=len(data),sha256=digest(data))
        if fault == 'elf': spec['binary_sha256'] = digest(b'not ELF')
    (root/'mihomo-manifest.json').write_text(json.dumps(manifest))
    calls, executions = [], []
    def download(url, path, maximum):
        calls.append(url)
        if fault == 'download': raise OSError('PRIVATE download failed')
        path.write_bytes(b'x'*maximum if fault == 'compressed_hash' else archive + b'x' if fault == 'size' else archive)
    def version(path):
        executions.append(path)
        if fault == 'output_error': raise EngineError('Mihomo version check failed.')
        return 'Mihomo Meta v1.19.30 linux amd64' if fault == 'wrong_version' else 'unknown version'
    with pytest.raises(EngineError):
        make(cpuinfo=cpuinfo(V3_FLAGS),downloader=download,version=version).install()
    assert calls == [spec['url']]
    assert bool(executions) == (fault in ('wrong_version','unknown_version','output_error'))
    assert (manager.binary.read_bytes(),manager.metadata.read_bytes()) == before


@pytest.mark.parametrize('key', ['linux-amd64-v1','linux-amd64-v2','linux-amd64-v3','linux-arm64'])
@pytest.mark.parametrize('fault', ['missing','asset','url','sha256','binary_sha256','size','boolean_size','extra'])
def test_every_manifest_build_is_strict_even_when_not_selected(managed, key, fault):
    root, manifest, _, make = managed
    if fault == 'missing': del manifest['platforms'][key]
    elif fault == 'extra': manifest['platforms'][key]['unexpected'] = 'x'
    else:
        field = 'size' if fault == 'boolean_size' else fault
        manifest['platforms'][key][field] = True if fault == 'boolean_size' else 0 if fault == 'size' else 'invalid'
    (root/'mihomo-manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(EngineError, match='manifest is invalid'):
        make()
    assert not (root/'bin').exists()


def test_duplicate_manifest_json_keys_are_rejected(managed):
    root, _, _, make = managed
    text = (root/'mihomo-manifest.json').read_text()
    (root/'mihomo-manifest.json').write_text(text.replace('"version":', '"version": "v1.19.31", "version":',1))
    with pytest.raises(EngineError, match='manifest is invalid'):
        make()


@pytest.mark.parametrize('legacy', [False,True])
def test_cpu_downgrade_status_does_not_execute_high_build_and_update_migrates(managed,legacy):
    _, manifest, binaries, make = managed
    manager = make(cpuinfo=cpuinfo(V3_FLAGS)); manager.install()
    if legacy:
        spec = manifest['legacy']['linux-amd64']
        manager.binary.write_bytes(gzip.decompress(binaries['amd64']))
        manager.metadata.write_text(json.dumps(dict(version=VERSION,platform='linux-amd64',asset=spec['asset'],
            archive_sha256=spec['sha256'],binary_sha256=spec['binary_sha256'])))
    calls = []
    migrated = make(cpuinfo=cpuinfo(TIM_FLAGS),version=lambda path:calls.append(path))
    assert migrated.status()['status'] == 'INCOMPATIBLE'
    assert migrated.status()['build'] == 'amd64-v3'
    assert not calls
    make(cpuinfo=cpuinfo(TIM_FLAGS)).install()
    metadata = json.loads(manager.metadata.read_text())
    assert metadata['cpu_level'] == 'v2' and metadata['asset'] == f'mihomo-linux-amd64-v2-{VERSION}.gz'
    assert make(cpuinfo=cpuinfo(TIM_FLAGS)).status()['status'] == 'COMPATIBLE'


def test_legacy_exact_generic_v3_recognition_runtime_failure_and_explicit_update(managed):
    _, manifest, binaries, make = managed
    manager = make(cpuinfo=cpuinfo(V3_FLAGS)); manager.install()
    spec = manifest['legacy']['linux-amd64']
    manager.binary.write_bytes(gzip.decompress(binaries['amd64']))
    metadata = dict(version=VERSION,platform='linux-amd64',asset=spec['asset'],
                    archive_sha256=spec['sha256'],binary_sha256=spec['binary_sha256'])
    manager.metadata.write_text(json.dumps(metadata))
    assert manager.status()['status'] == 'COMPATIBLE'
    assert manager.status()['build'] == 'amd64-v3'
    fail = make(cpuinfo=cpuinfo(V3_FLAGS),version=lambda p:(_ for _ in ()).throw(ExecutionError('private')))
    assert fail.status()['status'] == 'INCOMPATIBLE'
    metadata['archive_sha256'] = '0'*64
    manager.metadata.write_text(json.dumps(metadata))
    assert manager.status()['status'] == 'BROKEN'
    manager.install()
    assert json.loads(manager.metadata.read_text())['asset'] == f'mihomo-linux-amd64-v3-{VERSION}.gz'


def test_old_arm64_metadata_remains_compatible_without_cpu_detection(managed):
    _, _, _, make = managed
    manager = make('arm64',cpuinfo='not cpuinfo'); manager.install()
    metadata = json.loads(manager.metadata.read_text()); metadata.pop('cpu_level')
    manager.metadata.write_text(json.dumps(metadata))
    assert manager.cpu_level is None
    assert manager.status()['status'] == 'COMPATIBLE'
    assert manager.status()['build'] == 'arm64'


@pytest.mark.parametrize('returncode', [-4,1])
def test_real_version_runner_classifies_nonzero_without_raw_output(monkeypatch, returncode):
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:subprocess.CompletedProcess(a,returncode,b'PRIVATE',b'PRIVATE'))
    with pytest.raises(ExecutionError) as error:
        ManagedMihomo._version(Path('/fixture'))
    assert 'PRIVATE' not in str(error.value)


def test_post_replace_verification_failure_rolls_back_old_engine(managed):
    _, _, _, make = managed
    manager = make(); manager.install()
    before = manager.binary.read_bytes(),manager.metadata.read_bytes()
    def version(path):
        if path == manager.binary: raise ExecutionError('private')
        return f'Mihomo Meta {VERSION} linux amd64'
    with pytest.raises(EngineError,match='previous component preserved'):
        make(version=version).install()
    assert (manager.binary.read_bytes(),manager.metadata.read_bytes()) == before


def test_unusual_processor_id_does_not_raise_and_numeric_duplicates_are_unknown():
    text = cpuinfo(V3_FLAGS)
    assert detect_amd64_level(text.replace('processor : 0','processor : '+'9'*5000)) == 'v1'
    assert detect_amd64_level(text + '\n\n' + text.replace('processor : 0','processor : 00')) == 'v1'


@pytest.mark.parametrize('arch',['amd64','arm64'])
def test_cli_displays_host_level_installed_build_and_preferred(managed,monkeypatch,capsys,arch):
    import core.mihomo_manager as module
    _, _, _, make = managed
    manager = make(arch,cpuinfo=cpuinfo(TIM_FLAGS)); manager.install()
    monkeypatch.setattr(module,'ManagedMihomo',lambda:manager)
    module.main(['status'])
    output = capsys.readouterr().out
    assert 'Mihomo: COMPATIBLE' in output
    if arch == 'amd64':
        assert 'CPU Level: v2\nBuild: amd64-v2\nPreferred Build: amd64-v2' in output
    else:
        assert 'CPU Level: —\nBuild: arm64\nPreferred Build: arm64' in output


@pytest.mark.parametrize('output', [b'',b'PRIVATE'*1000,b'\xff'])
def test_real_runner_success_with_invalid_output_is_not_fallback_signal(monkeypatch, output):
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:subprocess.CompletedProcess(a,0,output,b''))
    with pytest.raises((EngineError,UnicodeError)) as error:
        ManagedMihomo._version(Path('/fixture'))
    assert not isinstance(error.value,ExecutionError)


def test_downgrade_with_binary_hash_drift_is_broken_without_execution(managed):
    _, _, _, make = managed
    manager = make(cpuinfo=cpuinfo(V3_FLAGS)); manager.install()
    manager.binary.write_bytes(manager.binary.read_bytes()+b'drift')
    calls = []
    assert make(cpuinfo=cpuinfo(TIM_FLAGS),version=lambda p:calls.append(p)).status()['status'] == 'BROKEN'
    assert not calls
