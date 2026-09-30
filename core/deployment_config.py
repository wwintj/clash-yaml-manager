"""Shared pure deployment validation/rendering; never executes or sources environment data."""
from pathlib import Path

BIND_HOSTS = ('0.0.0.0', '127.0.0.1')


def bind_host(value='0.0.0.0'):
    if value not in BIND_HOSTS:
        raise ValueError('APP_BIND_HOST must be 0.0.0.0 or 127.0.0.1.')
    return value


def service_unit(directory, port, host='0.0.0.0'):
    host = bind_host(host)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Invalid application port.')
    directory = str(Path(directory))
    if any(c in directory for c in '\r\n%') or not directory.startswith('/'):
        raise ValueError('Invalid deployment directory.')
    capability = ('AmbientCapabilities=CAP_NET_BIND_SERVICE\nCapabilityBoundingSet=CAP_NET_BIND_SERVICE\n'
                  if port < 1024 else '')
    return f'''[Unit]
Description=clash-yaml-manager
After=network.target

[Service]
Type=simple
User=clashyaml
Group=clashyaml
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
Environment=PYTHONDONTWRITEBYTECODE=1
{capability}WorkingDirectory={directory}
EnvironmentFile={directory}/.env
ExecStart={directory}/venv/bin/gunicorn --no-control-socket -w 2 --timeout 300 -b {host}:${{APP_PORT}} app:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
'''
