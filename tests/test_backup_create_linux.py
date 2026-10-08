"""Linux kernel evidence on synthetic tmp_path data; no updater/restore integration."""
import errno
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys
import time

import pytest

from scripts import backup_create as writer
from scripts import backup_verify as verifier


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux native kernel gate')
PROFILES = [('small-config', 32, 4096), ('state-shaped', 128, 32768),
            ('byte-heavy', 4, 16 * 1024 * 1024), ('object-heavy', 4000, 64)]


def evidence(capsys, label, values):
    # release-candidate.yml runs pytest -q: expose fixed, non-secret evidence only.
    with capsys.disabled():
        print(label + ' ' + json.dumps(values, sort_keys=True), flush=True)


@pytest.fixture
def native_tree(tmp_path):
    parent = tmp_path / 'private'
    parent.mkdir(mode=0o700)
    source = parent / 'source'
    source.mkdir(mode=0o700)
    (source / 'data').mkdir(mode=0o700)
    (source / 'empty').mkdir(mode=0o700)
    (source / 'data/synthetic.bin').write_bytes(b'\x00\xffsynthetic-only')
    (source / 'VERSION').write_bytes(b'1.7.0\n')
    return source, parent / 'snapshot'


def test_linux_native_publication_fsync_and_inode_identity(native_tree, monkeypatch, capsys):
    source, destination = native_tree
    native = writer.publication_function()
    actual_fsync = os.fsync
    synced, published = [], []
    parent_identity = writer.identity(destination.parent.stat())
    def sync(fd):
        info = os.fstat(fd)
        actual_fsync(fd)  # Real file / directory fsync; never pretend success.
        synced.append(writer.identity(info))
    def publish(parent_fd, stage, name):
        before = os.stat(stage, dir_fd=parent_fd, follow_symlinks=False)
        assert not destination.exists()
        assert writer.identity(before) in synced
        assert parent_identity in synced
        assert any(item[2] == stat.S_IFREG for item in synced)
        native(parent_fd, stage, name)  # Linux branch, libc renameat2, flags=1.
        after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        assert writer.identity(before) == writer.identity(after)
        assert not (destination.parent / stage).exists()
        published.append(writer.identity(after))
    monkeypatch.setattr(os, 'fsync', sync)
    monkeypatch.setattr(writer, 'publication_function', lambda: publish)
    result = writer.create(source, destination, 'UPDATER_SNAPSHOT')
    assert result['creation_status'] == 'CREATED'
    assert published == [writer.identity(destination.stat())]
    assert synced.count(parent_identity) == 2
    assert verifier.verify(destination)['verification_status'] == 'INTERNALLY_CONSISTENT'
    assert result['restore_proven'] is False and result['trust_anchor_verified'] is False
    evidence(capsys, 'LINUX_NATIVE_PUBLICATION', dict(result='PASS', renameat2='RENAME_NOREPLACE',
             file_fsync=True, directory_fsync=True, inode_preserved=True,
             python=platform.python_version(), kernel=platform.release(), machine=platform.machine()))


def test_linux_other_process_destination_collision_preserves_inode_and_cleanup(native_tree, monkeypatch, capsys):
    source, destination = native_tree
    native = writer.publication_function()
    collision = []
    child = '''import os,sys
fd=int(sys.argv[1]); name=sys.argv[2]
os.mkdir(name,0o700,dir_fd=fd)
file=os.open('unrelated-backup',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
try:
    os.write(file,b'synthetic-unrelated-backup');os.fsync(file)
finally:os.close(file)
os.fsync(fd)
'''
    def publish(parent_fd, stage, name):
        assert not destination.exists()
        subprocess.run([sys.executable, '-c', child, str(parent_fd), name],
                       pass_fds=(parent_fd,), check=True, timeout=15, capture_output=True,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        collision.append(verifier.fingerprint(destination.stat()))
        native(parent_fd, stage, name)
    monkeypatch.setattr(writer, 'publication_function', lambda: publish)
    result = writer.create(source, destination, 'UPDATER_SNAPSHOT')
    assert result['creation_status'] == 'FAILED' and result['publication_status'] == 'NOT_PUBLISHED'
    assert 'DESTINATION_EXISTS' in result['validation_codes']
    assert result['cleanup_status'] == 'CLEANED'
    assert verifier.fingerprint(destination.stat()) == collision[0]
    assert list(destination.iterdir()) == []  # Ordinary rename could replace this empty directory.
    assert (destination.parent / 'unrelated-backup').read_bytes() == b'synthetic-unrelated-backup'
    assert not list(destination.parent.glob('.backup-create-*'))
    evidence(capsys, 'LINUX_NATIVE_COLLISION', dict(result='PASS', other_process=True,
             empty_destination=True, existing_inode_unchanged=True,
             unrelated_bytes_unchanged=True, own_staging_cleaned=True))


def test_linux_descriptor_no_follow_is_enforced_by_kernel(native_tree, capsys):
    source, destination = native_tree
    (source / 'file-link').symlink_to('VERSION')
    (source / 'directory-link').symlink_to('data', target_is_directory=True)
    before = verifier.fingerprint((source / 'VERSION').stat())
    with verifier.root_directory(source) as (fd, _):
        with pytest.raises(OSError) as file_error:
            os.open('file-link', verifier.flags(), dir_fd=fd)
        assert file_error.value.errno == errno.ELOOP
        with pytest.raises(OSError) as directory_error:
            os.open('directory-link', verifier.flags(True), dir_fd=fd)
        assert directory_error.value.errno in (errno.ELOOP, errno.ENOTDIR)
        regular = os.open('VERSION', verifier.flags(), dir_fd=fd)
        try:
            assert verifier.fingerprint(os.fstat(regular)) == before
            assert os.read(regular, 64) == b'1.7.0\n'
        finally:
            os.close(regular)
    result = writer.create(source, destination, 'UPDATER_SNAPSHOT')
    assert result['creation_status'] == 'FAILED' and 'UNSAFE_OBJECT' in result['validation_codes']
    assert result['cleanup_status'] == 'NOT_NEEDED' and not destination.exists()
    assert verifier.fingerprint((source / 'VERSION').stat()) == before
    evidence(capsys, 'LINUX_NATIVE_NOFOLLOW', dict(result='PASS', file_errno='ELOOP',
             directory_rejected=True, descriptor_identity=True, source_unchanged=True))


# Runs ONLY in a child. The test process / runner policy is never changed.
SECCOMP_CHILD = r'''
import ctypes,errno,json,os,platform,re,sys
from pathlib import Path
from scripts import backup_create as writer
libc=ctypes.CDLL(None,use_errno=True)
libc.prctl.argtypes=[ctypes.c_int,ctypes.c_ulong,ctypes.c_void_p,ctypes.c_ulong,ctypes.c_ulong]
libc.prctl.restype=ctypes.c_int
libc.renameat2.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
libc.renameat2.restype=ctypes.c_int
arch=platform.machine()
headers={'x86_64':('/usr/include/x86_64-linux-gnu/asm/unistd_64.h',0xc000003e),
         'aarch64':('/usr/include/asm-generic/unistd.h',0xc00000b7)}
assert arch in headers and ctypes.sizeof(ctypes.c_void_p)==8
header,audit_arch=headers[arch]
number=int(re.search(r'^#define\s+__NR_renameat2\s+(\d+)\s*$',Path(header).read_text(),re.M).group(1))
class Filter(ctypes.Structure):
    _fields_=[('code',ctypes.c_ushort),('jt',ctypes.c_ubyte),('jf',ctypes.c_ubyte),('k',ctypes.c_uint)]
class Program(ctypes.Structure):
    _fields_=[('len',ctypes.c_ushort),('filter',ctypes.POINTER(Filter))]
# Check ABI, load syscall nr, deny only renameat2 with actual kernel ENOSYS.
# linux/{filter,seccomp,prctl}.h: LD|W|ABS=0x20, JMP|JEQ|K=0x15, RET|K=0x06.
filters=(Filter*7)(Filter(0x20,0,0,4),Filter(0x15,1,0,audit_arch),
    Filter(0x06,0,0,0x80000000),Filter(0x20,0,0,0),Filter(0x15,0,1,number),
    Filter(0x06,0,0,0x00050000|errno.ENOSYS),Filter(0x06,0,0,0x7fff0000))
program=Program(len(filters),filters)
assert libc.prctl(38,1,None,0,0)==0,'no_new_privs failed'
assert libc.prctl(22,2,ctypes.cast(ctypes.pointer(program),ctypes.c_void_p),0,0)==0,'seccomp filter failed'
parent=Path(sys.argv[1])
with writer.root_directory(parent) as (fd,_):
    os.mkdir('raw-source',0o700,dir_fd=fd)
    before=writer.identity(os.stat('raw-source',dir_fd=fd,follow_symlinks=False))
    rc=libc.renameat2(fd,b'raw-source',fd,b'raw-target',1)
    number_errno=ctypes.get_errno()
    assert rc==-1 and number_errno==errno.ENOSYS
    assert writer.identity(os.stat('raw-source',dir_fd=fd,follow_symlinks=False))==before
    assert not (parent/'raw-target').exists()
result=writer.create(parent/'source',parent/'snapshot','UPDATER_SNAPSHOT')
assert result['creation_status']=='FAILED' and result['publication_status']=='NOT_PUBLISHED'
assert 'NO_REPLACE_UNAVAILABLE' in result['validation_codes']
assert result['cleanup_status']=='CLEANED'
assert not (parent/'snapshot').exists() and not list(parent.glob('.backup-create-*'))
print(json.dumps(dict(result='PASS',kernel_errno='ENOSYS',no_fallback=True,
    own_staging_cleaned=True,restore_proven=False,syscall_number=number,machine=arch)))
'''


def test_linux_kernel_enosys_refuses_publication_without_fallback(native_tree, capsys):
    source, destination = native_tree
    before = verifier.fingerprint(source.stat())
    result = subprocess.run([sys.executable, '-c', SECCOMP_CHILD, str(destination.parent)],
                            cwd=ROOT, capture_output=True, text=True, timeout=30,
                            env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['result'] == 'PASS' and report['kernel_errno'] == 'ENOSYS'
    assert verifier.fingerprint(source.stat()) == before
    assert not destination.exists()
    evidence(capsys, 'LINUX_NATIVE_UNAVAILABLE', report)


def benchmark_profile(parent, profile, count, size, monkeypatch):
    """Warm-cache synthetic measurements, not production throughput or an SLA."""
    parent.mkdir(mode=0o700)
    source = parent / 'source'
    source.mkdir(mode=0o700)
    (source / 'data').mkdir(mode=0o700)
    piece = b'x' * min(65536, size)
    for n in range(count):
        with (source / 'data' / f'file-{n:04d}.bin').open('wb') as stream:
            remaining = size
            while remaining:
                written = stream.write(piece[:min(len(piece), remaining)])
                remaining -= written
    timings = {}
    def wrap(name, original):
        def measured(self, *args, **kwargs):
            key = ('verify-pre' if self.stage_name and str(args[0]).endswith(self.stage_name)
                   else 'verify-post') if name == 'verify_stage' else name
            started = time.monotonic()
            try:
                return original(self, *args, **kwargs)
            finally:
                timings[key] = timings.get(key, 0) + time.monotonic() - started
        return measured
    with monkeypatch.context() as context:
        for name in ('copy', 'manifest', 'sync_directories', 'verify_stage'):
            context.setattr(writer.Writer, name, wrap(name, getattr(writer.Writer, name)))
        started = time.monotonic()
        result = writer.create(source, parent / 'snapshot', 'UPDATER_SNAPSHOT')
        elapsed = time.monotonic() - started
    if result['creation_status'] == 'CREATED':
        assert result['verification']['verification_status'] == 'INTERNALLY_CONSISTENT'
        assert all(key in timings for key in ('copy', 'manifest', 'sync_directories', 'verify-pre', 'verify-post'))
    else:
        # Resource refusal is a measured outcome, never a silently successful truncation.
        assert 'TIME_LIMIT' in result['validation_codes'], result
        assert result['publication_status'] in ('NOT_PUBLISHED', 'PUBLISHED')
        if result['publication_status'] == 'NOT_PUBLISHED':
            assert result['cleanup_status'] == 'CLEANED' and not (parent / 'snapshot').exists()
    return dict(profile=profile, files=count, payload_bytes=count*size,
                stored_objects=count+3, elapsed_seconds=round(elapsed,6),
                phases_seconds={k:round(v,6) for k,v in sorted(timings.items())},
                creation_status=result['creation_status'], publication_status=result['publication_status'],
                validation_codes=result['validation_codes'], python=platform.python_version(),
                kernel=platform.release(), machine=platform.machine())


@pytest.mark.parametrize('profile,count,size', PROFILES)
def test_linux_synthetic_resource_profiles(tmp_path, monkeypatch, capsys, profile, count, size):
    result = benchmark_profile(tmp_path / 'private-benchmark', profile, count, size, monkeypatch)
    evidence(capsys, 'LINUX_SNAPSHOT_BENCHMARK', result)
