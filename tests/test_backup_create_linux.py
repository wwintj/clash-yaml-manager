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
import ctypes,errno,json,os,platform,re,resource,signal,stat,sys
from pathlib import Path
from scripts import backup_create as writer
from scripts import backup_verify as verifier
def require(condition,code):
    if not condition:raise AssertionError(code)
def emit(value):
    data=json.dumps(value,sort_keys=True)
    require(len(data)<=4096,'DIAGNOSTIC_SIZE_LIMIT')
    print(data,flush=True)
def tree_state(source):
    # Only our small synthetic fixture; never print names or payload bytes.
    return {str(p.relative_to(source)):(verifier.fingerprint(p.lstat()),
            p.read_bytes() if stat.S_ISREG(p.lstat().st_mode) else None)
            for p in [source,*sorted(source.rglob('*'))]}
libc=ctypes.CDLL(None,use_errno=True)
libc.prctl.argtypes=[ctypes.c_int,ctypes.c_ulong,ctypes.c_void_p,ctypes.c_ulong,ctypes.c_ulong]
libc.prctl.restype=ctypes.c_int
libc.renameat2.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
libc.renameat2.restype=ctypes.c_int
libc.syscall.argtypes=[ctypes.c_long]  # Variadic arguments below have explicit ABI types.
libc.syscall.restype=ctypes.c_long
libc.gnu_get_libc_version.argtypes=[]
libc.gnu_get_libc_version.restype=ctypes.c_char_p
arch=platform.machine()
headers={'x86_64':('/usr/include/x86_64-linux-gnu/asm/unistd_64.h',0xc000003e),
         'aarch64':('/usr/include/asm-generic/unistd.h',0xc00000b7)}
require(arch in headers and ctypes.sizeof(ctypes.c_void_p)==8,'UNSUPPORTED_TEST_ABI')
header,audit_arch=headers[arch]
header_text=Path(header).read_text()
def syscall_number(name):
    match=re.search(r'^#define\s+__NR_'+name+r'\s+(\d+)\s*$',header_text,re.M)
    require(match is not None,'MISSING_SYSCALL_NUMBER')
    return int(match.group(1))
number=syscall_number('renameat2')
ordinary_names=('rename','renameat') if arch=='x86_64' else ('renameat',)
ordinary_numbers={name:syscall_number(name) for name in ordinary_names}
diagnostic=dict(phase='PRE_WRITER',python=platform.python_version()[:32],
    kernel=platform.release()[:128],machine=arch,audit_arch=audit_arch,
    libc_version=libc.gnu_get_libc_version().decode('ascii')[:32],
    syscall_number=number,ordinary_syscalls=ordinary_numbers)
class Filter(ctypes.Structure):
    _fields_=[('code',ctypes.c_ushort),('jt',ctypes.c_ubyte),('jf',ctypes.c_ubyte),('k',ctypes.c_uint)]
class Program(ctypes.Structure):
    _fields_=[('len',ctypes.c_ushort),('filter',ctypes.POINTER(Filter))]
require(ctypes.sizeof(Filter)==8 and ctypes.sizeof(Program)==16
        and Program.filter.offset==8 and sys.byteorder=='little','INVALID_FILTER_ABI')
diagnostic['bpf_instruction_bytes']=ctypes.sizeof(Filter)
diagnostic['filter_program_bytes']=ctypes.sizeof(Program)
# Check ABI, load syscall nr, deny renameat2 with actual kernel ENOSYS.
# linux/{filter,seccomp,prctl}.h: LD|W|ABS=0x20, JMP|JEQ|K=0x15, RET|K=0x06.
instructions=[Filter(0x20,0,0,4),Filter(0x15,1,0,audit_arch),
    Filter(0x06,0,0,0x80000000),Filter(0x20,0,0,0),Filter(0x15,0,1,number),
    Filter(0x06,0,0,0x00050000|errno.ENOSYS)]
# A real POSIX fallback would kill this child, rather than look like a refusal.
for ordinary in ordinary_numbers.values():
    instructions.extend([Filter(0x15,0,1,ordinary),Filter(0x06,0,0,0x80000000)])
instructions.append(Filter(0x06,0,0,0x7fff0000))
filters=(Filter*len(instructions))(*instructions)
program=Program(len(filters),filters)
resource.setrlimit(resource.RLIMIT_CORE,(0,0))  # Only this child / its descendants.
ctypes.set_errno(0)
diagnostic['no_new_privs_rc']=libc.prctl(38,1,None,0,0)
diagnostic['no_new_privs_errno']=ctypes.get_errno()
ctypes.set_errno(0)
diagnostic['seccomp_install_rc']=libc.prctl(22,2,ctypes.cast(ctypes.pointer(program),ctypes.c_void_p),0,0)
diagnostic['seccomp_install_errno']=ctypes.get_errno()
diagnostic['no_new_privs_state']=libc.prctl(39,0,None,0,0)
diagnostic['seccomp_mode']=libc.prctl(21,0,None,0,0)
if not (diagnostic['no_new_privs_rc']==diagnostic['seccomp_install_rc']==0
        and diagnostic['no_new_privs_state']==1 and diagnostic['seccomp_mode']==2):
    emit(diagnostic)
    require(False,'SECCOMP_INSTALLATION_FAILED')
parent=Path(sys.argv[1])
with writer.root_directory(parent) as (fd,_):
    os.mkdir('raw-source',0o700,dir_fd=fd)
    os.mkdir('raw-target',0o700,dir_fd=fd)  # Protect an existing empty target too.
    before=writer.identity(os.stat('raw-source',dir_fd=fd,follow_symlinks=False))
    target_before=verifier.fingerprint(os.stat('raw-target',dir_fd=fd,follow_symlinks=False))
    ctypes.set_errno(0)
    diagnostic['raw_rc']=libc.syscall(ctypes.c_long(number),ctypes.c_int(fd),
        ctypes.c_char_p(b'raw-source'),ctypes.c_int(fd),ctypes.c_char_p(b'raw-target'),ctypes.c_uint(1))
    diagnostic['raw_errno']=ctypes.get_errno()
    ctypes.set_errno(0)
    diagnostic['wrapper_rc']=libc.renameat2(fd,b'raw-source',fd,b'raw-target',1)
    diagnostic['wrapper_errno']=ctypes.get_errno()
    diagnostic['filter_intercepted']=(diagnostic['raw_rc']==-1 and diagnostic['raw_errno']==errno.ENOSYS)
    emit(diagnostic)  # Bounded fixed technical fields BEFORE any Writer call.
    require(diagnostic['filter_intercepted'],'KERNEL_ENOSYS_NOT_PROVEN')
    # glibc may translate kernel ENOSYS to EINVAL for nonzero flags. Raw syscall
    # must still be exactly ENOSYS; the actual Writer wrapper must also refuse.
    require(diagnostic['wrapper_rc']==-1 and diagnostic['wrapper_errno'] in (errno.ENOSYS,errno.EINVAL),
            'LIBC_UNAVAILABLE_NOT_PROVEN')
    require(writer.identity(os.stat('raw-source',dir_fd=fd,follow_symlinks=False))==before,'RAW_SOURCE_CHANGED')
    require(verifier.fingerprint(os.stat('raw-target',dir_fd=fd,follow_symlinks=False))==target_before,
            'RAW_DESTINATION_CHANGED')
    require(list((parent/'raw-target').iterdir())==[],'RAW_DESTINATION_CHANGED')
    # Positive controls prove BOTH ordinary rename tripwires are active. Only
    # forked grandchildren deliberately trigger them; no runner policy changes.
    for name,ordinary in ordinary_numbers.items():
        pid=os.fork()
        if pid==0:
            if name=='rename':
                libc.syscall(ctypes.c_long(ordinary),ctypes.c_char_p(os.fsencode(parent/'tripwire-missing-source')),
                             ctypes.c_char_p(os.fsencode(parent/'tripwire-missing-target')))
            else:
                libc.syscall(ctypes.c_long(ordinary),ctypes.c_int(fd),ctypes.c_char_p(b'tripwire-missing-source'),
                             ctypes.c_int(fd),ctypes.c_char_p(b'tripwire-missing-target'))
            os._exit(99)
        _,status=os.waitpid(pid,0)
        require(os.WIFSIGNALED(status) and os.WTERMSIG(status)==signal.SIGSYS,'FALLBACK_TRIPWIRE_NOT_PROVEN')
source_before=tree_state(parent/'source')
sentinel=parent/'unrelated-backup'
sentinel_before=(verifier.fingerprint(sentinel.stat()),sentinel.read_bytes())
result=writer.create(parent/'source',parent/'snapshot','UPDATER_SNAPSHOT')
require(result['creation_status']=='FAILED' and result['publication_status']=='NOT_PUBLISHED','WRITER_PUBLISHED')
require('NO_REPLACE_UNAVAILABLE' in result['validation_codes'],'WRITER_REFUSAL_NOT_PROVEN')
require(result['cleanup_status']=='CLEANED','WRITER_CLEANUP_FAILED')
require(not (parent/'snapshot').exists() and not list(parent.glob('.backup-create-*')),'WRITER_RESIDUE')
require(tree_state(parent/'source')==source_before,'WRITER_SOURCE_CHANGED')
require((verifier.fingerprint(sentinel.stat()),sentinel.read_bytes())==sentinel_before,'UNRELATED_BACKUP_CHANGED')
require(verifier.fingerprint((parent/'raw-target').stat())==target_before,'EXISTING_DESTINATION_CHANGED')
require(result['restore_proven'] is False and result['MANIFEST_SHA256'] is None,'INVALID_RESTORE_OR_DIGEST')
emit(dict(result='PASS',kernel_errno='ENOSYS',writer_executed=True,
    creation_status=result['creation_status'],publication_status=result['publication_status'],
    refusal_code='NO_REPLACE_UNAVAILABLE',no_fallback=True,tripwires_proven=len(ordinary_numbers),
    own_staging_cleaned=True,source_unchanged=True,existing_destination_unchanged=True,
    unrelated_backup_unchanged=True,restore_proven=False,syscall_number=number,machine=arch))
'''


def test_linux_kernel_enosys_refuses_publication_without_fallback(native_tree, capsys):
    source, destination = native_tree
    def tree_state():
        return {p.relative_to(source):(verifier.fingerprint(p.lstat()),
                p.read_bytes() if p.is_file() else None) for p in [source, *sorted(source.rglob('*'))]}
    before = tree_state()
    sentinel = destination.parent / 'unrelated-backup'
    sentinel.write_bytes(b'synthetic-only-unrelated-backup')
    sentinel.chmod(0o600)
    sentinel_before = (verifier.fingerprint(sentinel.stat()), sentinel.read_bytes())
    result = subprocess.run([sys.executable, '-c', SECCOMP_CHILD, str(destination.parent)],
                            cwd=ROOT, capture_output=True, text=True, timeout=30,
                            env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    assert len(result.stdout) <= 8192, 'DIAGNOSTIC_SIZE_LIMIT'
    records = [json.loads(line) for line in result.stdout.splitlines()]
    if records:
        diagnostic = records[0]
        evidence(capsys, 'LINUX_ENOSYS_DIAGNOSTIC', diagnostic)
    return_code = result.returncode
    assert return_code == 0, 'GATE_NOT_PROVEN'
    assert len(records) == 2
    diagnostic, report = records
    assert diagnostic['raw_rc'] == -1 and diagnostic['raw_errno'] == errno.ENOSYS
    assert diagnostic['filter_intercepted'] is True
    assert diagnostic['wrapper_rc'] == -1 and diagnostic['wrapper_errno'] in (errno.ENOSYS, errno.EINVAL)
    assert diagnostic['no_new_privs_rc'] == diagnostic['seccomp_install_rc'] == 0
    assert diagnostic['no_new_privs_state'] == 1 and diagnostic['seccomp_mode'] == 2
    assert report['result'] == 'PASS' and report['kernel_errno'] == 'ENOSYS'
    assert report['writer_executed'] is True and report['no_fallback'] is True
    assert report['tripwires_proven'] == len(diagnostic['ordinary_syscalls'])
    assert report['creation_status'] == 'FAILED' and report['publication_status'] == 'NOT_PUBLISHED'
    assert report['refusal_code'] == 'NO_REPLACE_UNAVAILABLE' and report['own_staging_cleaned'] is True
    assert report['source_unchanged'] is True and report['existing_destination_unchanged'] is True
    assert report['unrelated_backup_unchanged'] is True and report['restore_proven'] is False
    assert tree_state() == before
    assert (verifier.fingerprint(sentinel.stat()), sentinel.read_bytes()) == sentinel_before
    assert not destination.exists()
    assert not list(destination.parent.glob('.backup-create-*'))
    evidence(capsys, 'LINUX_NATIVE_UNAVAILABLE: PASS', report)


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
