#!/usr/bin/env bash
set -euo pipefail
if [[ "${EUID}" -ne 0 ]]; then
  echo "httpsctl requires root over SSH: sudo bash /opt/clash-yaml-manager/httpsctl.sh" >&2
  exit 1
fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
cd "${SCRIPT_DIR}"
exec python3 -B -m core.https_manager "$@"
