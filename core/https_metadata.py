"""Strict credential-free managed HTTPS metadata; safe for authenticated local views."""
from datetime import datetime
import grp
import ipaddress
import json
import os
from pathlib import Path
import re
import stat

NAME = 'HTTPS_DEPLOYMENT.json'
KEYS = ('APP_BIND_HOST','COOKIE_SECURE','TRUST_PROXY_HEADERS','DOWNLOAD_URL_SCHEME','DOWNLOAD_BASE_URL')
BACKUP_NAME = re.compile(r'clash-yaml-manager-https-backup-[0-9]{8}_[0-9]{6}\.[A-Za-z0-9_-]{6,32}')


def domain(value):
    if not isinstance(value,str) or not 3 <= len(value) <= 253 or not value.isascii():
        raise ValueError('Invalid ASCII DNS domain.')
    value = value.lower()
    labels = value.split('.')
    if len(labels) < 2 or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',label) for label in labels):
        raise ValueError('Invalid ASCII DNS domain.')
    if value.endswith(('.local','.localhost')) or labels[-1].isdigit():
        raise ValueError('Invalid ASCII DNS domain.')
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    raise ValueError('Invalid ASCII DNS domain.')


def managed_settings(host):
    return dict(APP_BIND_HOST='127.0.0.1',COOKIE_SECURE='true',TRUST_PROXY_HEADERS='true',
                DOWNLOAD_URL_SCHEME='https',DOWNLOAD_BASE_URL='https://'+domain(host))


def validate(value, backup_root=Path('/root')):
    expected = {'version','managed','domain','configured_at','cert_mode','app_port',
                'nginx_config_sha256','hook_sha256','unit_sha256','managed_settings','previous_backup'}
    if not isinstance(value,dict) or set(value) != expected or type(value['version']) is not int or value['version'] != 1 or value['managed'] is not True:
        raise ValueError('Invalid HTTPS deployment metadata.')
    if domain(value['domain']) != value['domain'] or value['cert_mode'] != 'certbot-webroot':
        raise ValueError('Invalid HTTPS deployment metadata.')
    if type(value['app_port']) is not int or not 1 <= value['app_port'] <= 65535:
        raise ValueError('Invalid HTTPS deployment metadata.')
    for key in ('nginx_config_sha256','hook_sha256','unit_sha256'):
        if not isinstance(value[key],str) or not re.fullmatch(r'[a-f0-9]{64}',value[key]):
            raise ValueError('Invalid HTTPS deployment metadata.')
    if value['managed_settings'] != managed_settings(value['domain']):
        raise ValueError('Invalid HTTPS deployment metadata.')
    if not isinstance(value['configured_at'],str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00',value['configured_at']):
        raise ValueError('Invalid HTTPS deployment metadata.')
    datetime.fromisoformat(value['configured_at'])
    previous = value['previous_backup']
    if not isinstance(previous,str):raise ValueError('Invalid HTTPS deployment metadata.')
    path = Path(previous)
    if not path.is_absolute() or path.parent != Path(backup_root) or not BACKUP_NAME.fullmatch(path.name):
        raise ValueError('Invalid HTTPS deployment metadata.')
    return value


def read(directory, *, owner_uid=0, group_gid=None, backup_root=Path('/root')):
    path = Path(directory) / NAME
    if not path.exists() and not path.is_symlink():return None
    if group_gid is None:group_gid = grp.getgrnam('clashyaml').gr_gid
    fd = os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner_uid or info.st_gid != group_gid
                or stat.S_IMODE(info.st_mode) != 0o640 or info.st_size > 8192):
            raise ValueError('Invalid HTTPS deployment metadata.')
        raw = stream.read(8193)
    def unique(pairs):
        result = {}
        for key,item in pairs:
            if key in result:raise ValueError('Invalid HTTPS deployment metadata.')
            result[key] = item
        return result
    return validate(json.loads(raw,object_pairs_hook=unique),backup_root)


def status(directory):
    try:
        value = read(directory)
        return {'status':'Configured','domain':value['domain']} if value else {'status':'Not configured'}
    except Exception:
        return {'status':'Metadata unavailable'}
