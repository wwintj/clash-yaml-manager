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
MACHINE = {'x86_64':'amd64','amd64':'amd64','aarch64':'arm64','arm64':'arm64'}


class EngineError(RuntimeError):
    """Safe, fixed text only; never contain process or download output."""


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
                 downloader=None, version_runner=None, replacer=None):
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
        with open(self.root / 'mihomo-manifest.json', encoding='utf-8') as source:
            self.manifest = json.load(source)
        if (self.manifest.get('version') != VERSION
                or set(self.manifest.get('platforms', {})) != {'linux-amd64','linux-arm64'}):
            raise EngineError('Mihomo manifest is invalid.')

    def _asset(self):
        if self.system != 'linux' or not self.arch:
            raise EngineError('Unsupported Mihomo platform.')
        spec = self.manifest['platforms']['linux-' + self.arch]
        asset = f'mihomo-linux-{self.arch}-{VERSION}.gz'
        url = f'https://github.com/MetaCubeX/mihomo/releases/download/{VERSION}/{asset}'
        if (spec.get('asset') != asset or spec.get('url') != url
                or any(not re.fullmatch('[0-9a-f]{64}', spec.get(key, ''))
                       for key in ('sha256','binary_sha256'))
                or type(spec.get('size')) is not int or not 0 < spec['size'] <= MAX_ARCHIVE_BYTES):
            raise EngineError('Mihomo manifest is invalid.')
        return spec

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
        if result.returncode != 0 or len(result.stdout) > 4096 or len(result.stderr) > 4096:
            raise EngineError('Mihomo version check failed.')
        lines = result.stdout.decode('utf-8', 'strict').splitlines()
        if not lines:
            raise EngineError('Mihomo version check failed.')
        return lines[0]

    def status(self):
        details = dict(status='NOT INSTALLED', required=VERSION, installed=None,
                       architecture=self.arch or self.machine)
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
            if self.system != 'linux' or not self.arch or metadata['version'] != VERSION:
                details['status'] = 'INCOMPATIBLE'
                return details
            spec = self._asset()
            if metadata != dict(version=VERSION, platform='linux-' + self.arch, asset=spec['asset'],
                                archive_sha256=spec['sha256'], binary_sha256=spec['binary_sha256']):
                return details
            if sha256_file(self.binary) != spec['binary_sha256']:
                return details
            line = self.version_runner(self.binary)
            match = VERSION_LINE.match(line)
            if not match:
                return details
            if match.group(1) != VERSION or match.group(2) != self.arch:
                details['status'] = 'INCOMPATIBLE'
                details['installed'] = match.group(1)
                return details
            details['status'] = 'COMPATIBLE'
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

    def _install_locked(self, spec):
        for path, mode in ((self.binary,0o755),(self.metadata,0o644)):
            if (path.exists() or path.is_symlink()) and not self._safe_file(path, mode):
                raise EngineError('Existing Mihomo files are unsafe.')
        with tempfile.TemporaryDirectory(prefix='.mihomo-install-', dir=self.directory) as temporary:
            work = Path(temporary)
            archive, candidate, meta = work/'download.gz', work/'mihomo', work/'mihomo.json'
            try:
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
                machine = int.from_bytes(header[18:20], 'little') if header[:4] == b'\x7fELF' else None
                if machine != {'amd64':62,'arm64':183}[self.arch]:
                    raise EngineError('Mihomo architecture mismatch.')
                if (os.getuid(), os.getgid()) != (self.owner_uid, self.owner_gid):
                    os.chown(candidate, self.owner_uid, self.owner_gid)
                candidate.chmod(0o755)
                line = self.version_runner(candidate)
                match = VERSION_LINE.match(line)
                if not match or match.groups() != (VERSION,self.arch):
                    raise EngineError('Mihomo version mismatch.')
                metadata = dict(version=VERSION, platform='linux-' + self.arch, asset=spec['asset'],
                                archive_sha256=spec['sha256'], binary_sha256=spec['binary_sha256'])
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
                except OSError:
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
        spec = self._asset()
        self._prepare_directory()
        with file_lock(self.lock, strict=True):
            self._install_locked(spec)
        if self.status()['status'] != 'COMPATIBLE':
            raise EngineError('Mihomo install verification failed.')

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
