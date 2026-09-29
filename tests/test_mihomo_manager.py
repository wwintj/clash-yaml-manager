"""Offline supply-chain and optional-engine tests; no real /opt or root account."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from core.mihomo_manager import EngineError, ManagedMihomo, VERSION
from conftest import ROOT
from test_deployment import deployment


def digest(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def managed(tmp_path):
    root = tmp_path / 'app'; root.mkdir()
    binaries = {}
    manifest = dict(version=VERSION, platforms={})
    for arch, machine in (('amd64',62),('arm64',183)):
        elf = bytearray(64)
        elf[:4] = b'\x7fELF'; elf[4] = 2; elf[5] = 1
        elf[18:20] = machine.to_bytes(2,'little')
        elf.extend(b'controlled fixture ' + arch.encode())
        archive = gzip.compress(bytes(elf))
        asset = f'mihomo-linux-{arch}-{VERSION}.gz'
        binaries[arch] = archive
        manifest['platforms']['linux-'+arch] = dict(asset=asset,
            url=f'https://github.com/MetaCubeX/mihomo/releases/download/{VERSION}/{asset}',
            sha256=digest(archive),binary_sha256=digest(elf),size=len(archive))
    (root/'mihomo-manifest.json').write_text(json.dumps(manifest))
    def make(arch='amd64', downloader=None, version=None, replacer=None):
        machine = 'x86_64' if arch == 'amd64' else 'aarch64'
        def download(url,destination,maximum):
            assert url == manifest['platforms']['linux-'+arch]['url']
            assert maximum == len(binaries[arch])
            Path(destination).write_bytes(binaries[arch])
        manager = ManagedMihomo(root,system='linux',machine=machine,owner_uid=os.getuid(),
            owner_gid=os.getgid(),downloader=downloader or download,
            version_runner=version or (lambda path:f'Mihomo Meta {VERSION} linux {arch} with go1.25'),
            replacer=replacer)
        manager._require_root = lambda:None
        return manager
    return root, manifest, binaries, make


def test_release_manifest_matches_independently_downloaded_asset_hashes_and_architecture():
    value = json.loads((ROOT/'mihomo-manifest.json').read_text())
    assert value['version'] == VERSION
    assert value['platforms']['linux-amd64']['sha256'] == 'd5e74bbddbdfff49a1aef7775bf5911da59f0d7196ed509a0ac914b3653dd5f1'
    assert value['platforms']['linux-arm64']['sha256'] == '9e0f11afbf38426b8bd88fdc594678f8161c57eccb4e1b77acb12b493904f1d4'
    assert all('/releases/download/v1.19.31/' in part['url'] and '/latest/' not in part['url']
               for part in value['platforms'].values())


@pytest.mark.parametrize('arch',['amd64','arm64'])
def test_install_status_remove_exact_asset_and_ownership(managed,arch):
    root, manifest, _, make = managed
    manager = make(arch)
    assert manager.status()['status'] == 'NOT INSTALLED'
    manager.install()
    assert manager.status() == dict(status='COMPATIBLE',required=VERSION,installed=VERSION,architecture=arch)
    assert manager.binary.stat().st_mode & 0o777 == 0o755
    assert manager.metadata.stat().st_mode & 0o777 == 0o644
    assert manager.binary.stat().st_uid == manager.metadata.stat().st_uid == os.getuid()
    metadata = json.loads(manager.metadata.read_text())
    assert metadata['archive_sha256'] == manifest['platforms']['linux-'+arch]['sha256']
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
    spec = manifest['platforms']['linux-amd64']
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
