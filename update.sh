#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="clash-yaml-manager"
INSTALL_DIR="/opt/clash-yaml-manager"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ "${EUID}" -ne 0 ]]; then
  echo "错误：请使用 root 权限运行此脚本：sudo bash update.sh"
  exit 1
fi

CURRENT_DIR="$(pwd -P)"

if [[ ! -f "${CURRENT_DIR}/app.py" || ! -f "${CURRENT_DIR}/requirements.txt" ]]; then
  echo "错误：请在新版 clash-yaml-manager 项目根目录下运行 update.sh。"
  exit 1
fi

if [[ ! -d "${INSTALL_DIR}" ]]; then
  echo "错误：未找到安装目录 ${INSTALL_DIR}。请先运行 install.sh 完成安装。"
  exit 1
fi

if [[ "${CURRENT_DIR}" == "$(cd "${INSTALL_DIR}" && pwd -P)" ]]; then
  echo "错误：不能在安装目录内原地升级。请将新版源码放在独立目录，再运行 update.sh。"
  exit 1
fi

if [[ ! -f "${INSTALL_DIR}/.env" ]]; then
  echo "错误：缺少现有 .env，升级已停止，服务未改动。"
  exit 1
fi

for command in python3 systemctl curl; do
  command -v "${command}" >/dev/null || { echo "缺少必要命令：${command}"; exit 1; }
done

# Validate Python syntax and existing environment before changing deployed files.
APP_PORT="$(python3 - "${CURRENT_DIR}" "${INSTALL_DIR}/.env" <<'PY'
import base64
import pathlib
import sys
try:
    source = pathlib.Path(sys.argv[1])
    for path in [source / 'app.py', *sorted((source / 'core').glob('*.py'))]:
        compile(path.read_bytes(), str(path), 'exec')
    values = {}
    for line in pathlib.Path(sys.argv[2]).read_text().splitlines():
        if line.strip() and not line.lstrip().startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip(chr(34) + chr(39))
    port = int(values.get('APP_PORT', '8899'))
    assert 1 <= port <= 65535
    assert values.get('SECRET_KEY')
    assert values.get('APP_PASSWORD_B64') or values.get('APP_PASSWORD')
    if values.get('APP_PASSWORD_B64'):
        assert base64.b64decode(values['APP_PASSWORD_B64'], validate=True).decode('utf-8')
    assert values.get('DOWNLOAD_URL_SCHEME', '') in ('', 'http', 'https')
    print(port)
except Exception:
    sys.exit('升级预检失败：请检查源码语法、APP_PORT、SECRET_KEY、密码及 URL 协议配置；未停止服务。')
PY
)"

umask 077

TIMESTAMP="$(date +"%Y%m%d_%H%M%S")"
BACKUP_DIR="$(mktemp -d "/root/${SERVICE_NAME}-update-backup-${TIMESTAMP}.XXXXXX")"

upgrade_failed() {
  echo "升级失败。备份保留于 ${BACKUP_DIR}，请勿再次运行 install.sh。" >&2
  echo "回滚：停止 ${SERVICE_NAME}；从备份恢复应用代码、venv、.env 和 defaults；将 service 文件恢复到 ${SERVICE_FILE}；daemon-reload 后重启。保留 uploads/outputs/backups/logs。" >&2
}
trap upgrade_failed ERR

echo "=========================================================="
echo "开始升级 ${SERVICE_NAME}"
echo "=========================================================="
echo "安装目录: ${INSTALL_DIR}"
echo "新版目录: ${CURRENT_DIR}"
echo "备份目录: ${BACKUP_DIR}"

echo "正在备份当前安装目录..."
mkdir -p "${BACKUP_DIR}"

for item in app.py requirements.txt install.sh uninstall.sh update.sh remote-update.sh core templates static venv; do
  if [[ -e "${INSTALL_DIR}/${item}" ]]; then
    cp -a "${INSTALL_DIR}/${item}" "${BACKUP_DIR}/"
  fi
done

if [[ -f "${SERVICE_FILE}" ]]; then
  cp -a "${SERVICE_FILE}" "${BACKUP_DIR}/${SERVICE_NAME}.service"
fi

if [[ -f "${INSTALL_DIR}/.env" ]]; then
  cp -a "${INSTALL_DIR}/.env" "${BACKUP_DIR}/.env"
fi

if [[ -f "${INSTALL_DIR}/defaults/default.yaml" ]]; then
  mkdir -p "${BACKUP_DIR}/defaults"
  cp -a "${INSTALL_DIR}/defaults/default.yaml" "${BACKUP_DIR}/defaults/default.yaml"
fi

# Download/install dependencies before stopping the working service. The backed-up
# venv is available for manual rollback if dependency installation fails.
if [[ ! -d "${INSTALL_DIR}/venv" ]]; then
  python3 -m venv "${INSTALL_DIR}/venv"
fi
"${INSTALL_DIR}/venv/bin/pip" install -r "${CURRENT_DIR}/requirements.txt"
"${INSTALL_DIR}/venv/bin/pip" check

if [[ -f "${SERVICE_FILE}" ]]; then
  echo "正在停止服务..."
  systemctl stop "${SERVICE_NAME}"
fi

echo "正在复制新版应用代码..."
shopt -s dotglob nullglob
for item in "${CURRENT_DIR}"/*; do
  name="$(basename "${item}")"
  case "${name}" in
    .env|.git|.venv|venv|uploads|outputs|backups|logs|.last_cleanup|.pytest_cache|__pycache__)
      continue
      ;;
    defaults)
      mkdir -p "${INSTALL_DIR}/defaults"
      for default_item in "${item}"/*; do
        default_name="$(basename "${default_item}")"
        if [[ "${default_name}" == "default.yaml" && -f "${INSTALL_DIR}/defaults/default.yaml" ]]; then
          echo "保留现有默认 YAML: ${INSTALL_DIR}/defaults/default.yaml"
          continue
        fi
        rm -rf "${INSTALL_DIR}/defaults/${default_name}"
        cp -a "${default_item}" "${INSTALL_DIR}/defaults/"
      done
      ;;
    *)
      rm -rf "${INSTALL_DIR:?}/${name}"
      cp -a "${item}" "${INSTALL_DIR}/"
      ;;
  esac
done
shopt -u dotglob nullglob

echo "正在确保运行目录存在..."
mkdir -p "${INSTALL_DIR}/uploads" "${INSTALL_DIR}/outputs" "${INSTALL_DIR}/backups" "${INSTALL_DIR}/logs" "${INSTALL_DIR}/defaults"
chmod 700 "${INSTALL_DIR}/uploads" "${INSTALL_DIR}/outputs" "${INSTALL_DIR}/backups" "${INSTALL_DIR}/logs"

if [[ ! -f "${INSTALL_DIR}/defaults/default.yaml" && -f "${CURRENT_DIR}/defaults/default.yaml" ]]; then
  cp -a "${CURRENT_DIR}/defaults/default.yaml" "${INSTALL_DIR}/defaults/default.yaml"
fi

if [[ ! -f "${INSTALL_DIR}/.env" ]]; then
  echo "错误：未找到 ${INSTALL_DIR}/.env，无法保留现有配置。请检查备份目录 ${BACKUP_DIR}。"
  exit 1
fi

echo "正在刷新 systemd 服务文件..."
cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=clash-yaml-manager
After=network.target

[Service]
Type=simple
User=root
UMask=0077
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${INSTALL_DIR}/.env
ExecStart=${INSTALL_DIR}/venv/bin/gunicorn -w 2 --timeout 300 -b 0.0.0.0:\${APP_PORT} app:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

healthy=false
for attempt in {1..15}; do
  if systemctl is-active --quiet "${SERVICE_NAME}" && curl -fsS --max-time 2 "http://127.0.0.1:${APP_PORT}/" >/dev/null; then
    healthy=true
    break
  fi
  sleep 1
done
if [[ "${healthy}" != true ]]; then
  echo "错误：升级后健康检查失败，请检查 systemctl status 和 journalctl。" >&2
  upgrade_failed
  exit 1
fi

echo "=========================================================="
echo "升级完成。"
echo "已保留: .env、defaults/default.yaml、uploads、outputs、backups、logs"
echo "备份目录: ${BACKUP_DIR}"
echo "查看状态: systemctl status ${SERVICE_NAME}"
echo "=========================================================="
