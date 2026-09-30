"""Root-operated, optional and exactly pinned Mihomo component."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.request
import zlib

from core.state import file_lock

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'v1.19.31'
MAX_BINARY_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_BYTES = 40 * 1024 * 1024
VERSION_LINE = re.compile(r'^Mihomo Meta (v[0-9]+\.[0-9]+\.[0-9]+) linux (amd64|arm64)\b')
V2_FLAGS = frozenset('cx16 lahf_lm popcnt pni ssse3 sse4_1 sse4_2'.split())
V3_FLAGS = V2_FLAGS | frozenset('avx avx2 bmi1 bmi2 fma f16c abm movbe xsave'.split())
LEVELS = ('v1', 'v2', 'v3')
MACHINE = {'x86_64':'amd64','amd64':'amd64','aarch64':'arm64','arm64':'arm64'}


class EngineError(RuntimeError):
    """Safe, fixed text only; never contain process or download output."""


class ExecutionError(EngineError):
    """A verified artifact failed to execute; a lower pinned build may work."""


def detect_amd64_level(cpuinfo_text):
    """Intersect Linux-enabled flags on every visible processor; unknown is v1.

    Linux names SSE3 'pni' and LZCNT 'abm'. OSXSAVE has no exported cpuinfo
    name; kernel-enabled XSAVE + AVX indicate OS vector-state support. The
    candidate's bounded -v remains the final OSXSAVE/XGETBV/runtime check.
    """
    if not isinstance(cpuinfo_text, str) or not cpuinfo_text.strip():
        return 'v1'
    common, processors = None, set()
    for block in re.split(r'\n\s*\n', cpuinfo_text.strip()):
        entries = {}
        for line in block.splitlines():
            if ':' not in line:
                return 'v1'
            key, value = (part.strip() for part in line.split(':', 1))
            if key in entries:
                return 'v1'
            entries[key] = value
        processor = entries.get('processor', '')
        processor_id = processor.lstrip('0') or '0'
        flag_keys = set(entries) & {'flags', 'features'}
        if (not re.fullmatch('[0-9]{1,10}', processor)
                or processor_id in processors or len(flag_keys) != 1):
            return 'v1'
        processors.add(processor_id)
        flags = set(entries[flag_keys.pop()].split())
        if not flags or any(not re.fullmatch(r'[a-z0-9_]+', flag) for flag in flags):
            return 'v1'
        common = flags if common is None else common & flags
    if V3_FLAGS <= common:
        return 'v3'
    return 'v2' if V2_FLAGS <= common else 'v1'


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EngineError('Mihomo manifest is invalid.')
        result[key] = value
    return result


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for part in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(part)
    return digest.hexdigest()


def direct_download(url, destination, maximum):
    class HttpsRedirects(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            if not newurl.startswith('https://'):
                raise EngineError('Mihomo download failed.')
            return super().redirect_request(request, fp, code, msg, headers, newurl)
    if not url.startswith('https://'):
        raise EngineError('Mihomo download failed.')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), HttpsRedirects())
    deadline = time.monotonic() + 180
    with opener.open(url, timeout=20) as response, open(destination, 'wb') as target:
        if response.geturl() != url and not response.geturl().startswith('https://'):
            raise EngineError('Mihomo download failed.')
        size = 0
        while True:
            if time.monotonic() >= deadline:
                raise EngineError('Mihomo download failed.')
            part = response.read(1024 * 1024)
            if not part:
                break
            size += len(part)
            if size > maximum:
                raise EngineError('Mihomo download failed.')
            target.write(part)


class ManagedMihomo:
    def __init__(self, root=ROOT, *, system=None, machine=None, owner_uid=0, owner_gid=0,
                 downloader=None, version_runner=None, replacer=None, cpuinfo_text=None):
        self.root = Path(root)
        self.directory = self.root / 'bin'
        self.binary = self.directory / 'mihomo'
        self.metadata = self.directory / 'mihomo.json'
        self.lock = self.directory / '.mihomoctl.lock'
        self.system = (system or platform.system()).lower()
        self.machine = machine or platform.machine()
        self.arch = MACHINE.get(self.machine.lower())
        self.owner_uid = owner_uid
        self.owner_gid = owner_gid
        self.downloader = downloader or direct_download
        self.version_runner = version_runner or self._version
        self.replacer = replacer or os.replace
        self.cpu_level = None
        if self.system == 'linux' and self.arch == 'amd64':
            if cpuinfo_text is None:
                try:
                    with open('/proc/cpuinfo', encoding='ascii') as source:
                        cpuinfo_text = source.read(16 * 1024 * 1024 + 1)
                    if len(cpuinfo_text) > 16 * 1024 * 1024:
                        cpuinfo_text = ''
                except (OSError, UnicodeError):
                    cpuinfo_text = ''
            self.cpu_level = detect_amd64_level(cpuinfo_text)
        try:
            with open(self.root / 'mihomo-manifest.json', encoding='utf-8') as source:
                self.manifest = json.load(source, object_pairs_hook=_unique_object)
            self._validate_manifest()
        except (OSError, ValueError, TypeError, AttributeError):
            raise EngineError('Mihomo manifest is invalid.') from None

    def _validate_manifest(self):
        platforms = {'linux-amd64-' + level for level in LEVELS} | {'linux-arm64'}
        if (set(self.manifest) != {'version', 'platforms', 'legacy'}
                or self.manifest['version'] != VERSION
                or set(self.manifest['platforms']) != platforms
                or set(self.manifest['legacy']) != {'linux-amd64'}):
            raise EngineError('Mihomo manifest is invalid.')
        for key, spec in list(self.manifest['platforms'].items()) + list(self.manifest['legacy'].items()):
            asset = f'mihomo-{key}-{VERSION}.gz'
            url = f'https://github.com/MetaCubeX/mihomo/releases/download/{VERSION}/{asset}'
            if (not isinstance(spec, dict)
                    or set(spec) != {'asset','url','sha256','binary_sha256','size'}
                    or spec['asset'] != asset or spec['url'] != url
                    or any(not isinstance(spec[k], str) or not re.fullmatch('[0-9a-f]{64}', spec[k])
                           for k in ('sha256','binary_sha256'))
                    or type(spec['size']) is not int or not 0 < spec['size'] <= MAX_ARCHIVE_BYTES):
                raise EngineError('Mihomo manifest is invalid.')

    def _asset(self, level=None):
        if self.system != 'linux' or not self.arch:
            raise EngineError('Unsupported Mihomo platform.')
        key = 'linux-' + self.arch
        if self.arch == 'amd64':
            key += '-' + (level or self.cpu_level)
        return self.manifest['platforms'][key]

    def _candidates(self):
        if self.arch == 'amd64':
            return [(level, self._asset(level))
                    for level in reversed(LEVELS[:LEVELS.index(self.cpu_level) + 1])]
        return [(None, self._asset())]

    def _metadata(self, spec, level):
        return dict(version=VERSION, platform='linux-' + self.arch, cpu_level=level,
                    asset=spec['asset'], archive_sha256=spec['sha256'],
                    binary_sha256=spec['binary_sha256'])

    def _directory_safe(self):
        if not self.directory.exists() and not self.directory.is_symlink():
            return False
        info = self.directory.lstat()
        return (stat.S_ISDIR(info.st_mode) and info.st_uid == self.owner_uid
                and info.st_gid == self.owner_gid
                and not info.st_mode & 0o022)

    def _safe_file(self, path, mode):
        info = path.lstat()
        return (stat.S_ISREG(info.st_mode) and info.st_uid == self.owner_uid
                and info.st_gid == self.owner_gid and stat.S_IMODE(info.st_mode) == mode)

    def _read_metadata(self):
        fd = os.open(self.metadata, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != self.owner_uid
                    or info.st_gid != self.owner_gid or stat.S_IMODE(info.st_mode) != 0o644
                    or info.st_size > 4096):
                raise EngineError('Mihomo metadata is invalid.')
            return json.loads(source.read(4097))

    @staticmethod
    def _version(path):
        result = subprocess.run([str(path), '-v'], capture_output=True, timeout=3, check=False)
        if result.returncode != 0:
            raise ExecutionError('Mihomo version check failed.')
        if len(result.stdout) > 4096 or len(result.stderr) > 4096:
            raise EngineError('Mihomo version check failed.')
        lines = result.stdout.decode('utf-8', 'strict').splitlines()
        if not lines:
            raise EngineError('Mihomo version check failed.')
        return lines[0]

    def _run_version(self, path):
        try:
            return self.version_runner(path)
        except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
            raise ExecutionError('Mihomo version check failed.') from None

    def status(self, *, verify_execution=True):
        details = dict(status='NOT INSTALLED', required=VERSION, installed=None,
                       architecture=self.arch or self.machine, cpu_level=self.cpu_level,
                       build=None, preferred_build=(self.arch + '-' + self.cpu_level
                           if self.cpu_level else self.arch))
        legacy = False
        try:
            if (self.directory.exists() or self.directory.is_symlink()) and not self._directory_safe():
                details['status'] = 'BROKEN'
                return details
            if not self.binary.exists() and not self.binary.is_symlink() and not self.metadata.exists() and not self.metadata.is_symlink():
                return details
            details['status'] = 'BROKEN'
            if not self._directory_safe() or not self._safe_file(self.binary, 0o755):
                return details
            metadata = self._read_metadata()
            if not isinstance(metadata, dict) or not isinstance(metadata.get('version'), str):
                return details
            details['installed'] = metadata['version'] if re.fullmatch(r'v\d+\.\d+\.\d+', metadata['version']) else None
            if (self.system != 'linux' or not self.arch or metadata['version'] != VERSION
                    or metadata.get('platform') != 'linux-' + self.arch):
                details['status'] = 'INCOMPATIBLE'
                return details
            level = metadata.get('cpu_level')
            if self.arch == 'amd64' and 'cpu_level' not in metadata:
                legacy = True
                level = 'v3'
                spec = self.manifest['legacy']['linux-amd64']
            elif self.arch == 'amd64' and level not in LEVELS:
                return details
            else:
                if self.arch == 'arm64' and level is not None:
                    return details
                spec = self._asset(level)
            expected = self._metadata(spec, level)
            if legacy or (self.arch == 'arm64' and 'cpu_level' not in metadata):
                expected.pop('cpu_level')
            if not verify_execution and self.binary.stat().st_size > MAX_BINARY_BYTES:
                return details
            if metadata != expected or sha256_file(self.binary) != spec['binary_sha256']:
                return details
            details['build'] = self.arch + ('-' + level if level else '')
            if self.arch == 'amd64' and LEVELS.index(level) > LEVELS.index(self.cpu_level):
                details['status'] = 'INCOMPATIBLE'
                return details
            if not verify_execution:
                # Settings verifies local pins/metadata without executing a binary.
                # CLI/probe callers retain the full execution check.
                details['status'] = 'COMPATIBLE'
                return details
            line = self._run_version(self.binary)
            match = VERSION_LINE.match(line)
            if not match:
                return details
            if match.group(1) != VERSION or match.group(2) != self.arch:
                details['status'] = 'INCOMPATIBLE'
                details['installed'] = match.group(1)
                return details
            details['status'] = 'COMPATIBLE'
            return details
        except ExecutionError:
            details['status'] = 'INCOMPATIBLE' if legacy else 'BROKEN'
            return details
        except (OSError, ValueError, TypeError, IndexError, UnicodeError, subprocess.SubprocessError, EngineError):
            details['status'] = 'BROKEN'
            return details

    def _require_root(self):
        if os.geteuid() != 0:
            raise EngineError('Run Mihomo management with sudo over SSH.')

    def _prepare_directory(self):
        if self.directory.is_symlink():
            raise EngineError('Managed Mihomo directory is unsafe.')
        if not self.directory.exists():
            self.directory.mkdir(mode=0o755)
            if (os.getuid(), os.getgid()) != (self.owner_uid, self.owner_gid):
                os.chown(self.directory, self.owner_uid, self.owner_gid)
        if not self._directory_safe():
            raise EngineError('Managed Mihomo directory is unsafe.')

    def _install_locked(self, candidates):
        for path, mode in ((self.binary,0o755),(self.metadata,0o644)):
            if (path.exists() or path.is_symlink()) and not self._safe_file(path, mode):
                raise EngineError('Existing Mihomo files are unsafe.')
        with tempfile.TemporaryDirectory(prefix='.mihomo-install-', dir=self.directory) as temporary:
            work = Path(temporary)
            archive, candidate, meta = work/'download.gz', work/'mihomo', work/'mihomo.json'
            try:
                chosen = None
                for level, spec in candidates:
                    self.downloader(spec['url'], archive, spec['size'])
                    if archive.stat().st_size != spec['size'] or sha256_file(archive) != spec['sha256']:
                        raise EngineError('Mihomo asset checksum mismatch.')
                    with gzip.open(archive, 'rb') as source, open(candidate, 'wb') as target:
                        size = 0
                        while chunk := source.read(1024 * 1024):
                            size += len(chunk)
                            if size > MAX_BINARY_BYTES:
                                raise EngineError('Mihomo binary is too large.')
                            target.write(chunk)
                    if sha256_file(candidate) != spec['binary_sha256']:
                        raise EngineError('Mihomo binary checksum mismatch.')
                    with open(candidate, 'rb') as source:
                        header = source.read(20)
                    machine = (int.from_bytes(header[18:20], 'little')
                               if len(header) == 20 and header[:6] == b'\x7fELF\x02\x01' else None)
                    if machine != {'amd64':62,'arm64':183}[self.arch]:
                        raise EngineError('Mihomo architecture mismatch.')
                    if (os.getuid(), os.getgid()) != (self.owner_uid, self.owner_gid):
                        os.chown(candidate, self.owner_uid, self.owner_gid)
                    candidate.chmod(0o755)
                    try:
                        line = self._run_version(candidate)
                    except ExecutionError:
                        continue
                    match = VERSION_LINE.match(line)
                    if not match or match.groups() != (VERSION,self.arch):
                        raise EngineError('Mihomo version mismatch.')
                    chosen = self._metadata(spec, level)
                    break
                if chosen is None:
                    raise EngineError('Mihomo execution failed for all pinned builds; previous component preserved.')
                metadata = chosen
                meta.write_text(json.dumps(metadata, sort_keys=True) + '\n', encoding='utf-8')
                if (os.getuid(), os.getgid()) != (self.owner_uid, self.owner_gid):
                    os.chown(meta, self.owner_uid, self.owner_gid)
                meta.chmod(0o644)
                old_binary, old_meta = work/'old-mihomo', work/'old-mihomo.json'
                had_binary, had_meta = self.binary.exists(), self.metadata.exists()
                if had_binary: shutil.copy2(self.binary, old_binary)
                if had_meta: shutil.copy2(self.metadata, old_meta)
                try:
                    self.replacer(candidate, self.binary)
                    self.replacer(meta, self.metadata)
                    if self.status()['status'] != 'COMPATIBLE':
                        raise EngineError('Mihomo install verification failed.')
                except (OSError, EngineError):
                    # Restore both sides after any ordinary replacement failure.
                    if had_binary: os.replace(old_binary, self.binary)
                    elif self.binary.exists(): self.binary.unlink()
                    if had_meta: os.replace(old_meta, self.metadata)
                    elif self.metadata.exists(): self.metadata.unlink()
                    raise EngineError('Mihomo update failed; previous component preserved.') from None
            except EngineError:
                raise
            except (OSError, EOFError, ValueError, zlib.error, subprocess.SubprocessError, UnicodeError):
                raise EngineError('Mihomo install failed; previous component preserved.') from None

    def install(self):
        self._require_root()
        self._asset()
        candidates = self._candidates()
        self._prepare_directory()
        with file_lock(self.lock, strict=True):
            self._install_locked(candidates)

    def remove(self):
        self._require_root()
        if not self._directory_safe():
            if not self.directory.exists() and not self.directory.is_symlink():
                return
            raise EngineError('Managed Mihomo directory is unsafe.')
        with file_lock(self.lock, strict=True):
            for path in (self.binary,self.metadata):
                if path.exists() or path.is_symlink():
                    path.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Manage the optional, pinned Mihomo component.')
    parser.add_argument('action', choices=('status','install','update','remove'))
    args = parser.parse_args(argv)
    try:
        manager = ManagedMihomo()
        if args.action == 'status':
            details = manager.status()
            print('Mihomo: ' + details['status'])
            print('Required: ' + details['required'])
            print('Installed: ' + (details['installed'] or '—'))
            print('Architecture: ' + str(details['architecture']))
            print('CPU Level: ' + (details['cpu_level'] or '—'))
            print('Build: ' + (details['build'] or '—'))
            print('Preferred Build: ' + (details['preferred_build'] or '—'))
            if details['status'] == 'INCOMPATIBLE':
                print('Run mihomoctl.sh update over SSH to select a compatible build.')
        elif args.action == 'remove':
            manager.remove()
            print('Managed Mihomo removed.')
        else:
            manager.install()
            print('Managed Mihomo ' + ('installed.' if args.action == 'install' else 'updated.'))
    except EngineError as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
