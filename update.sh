#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="clash-yaml-manager"
INSTALL_DIR="/opt/clash-yaml-manager"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ "${EUID}" -ne 0 ]]; then
  echo "错误：请使用 root 权限运行此脚本：sudo bash update.sh"
  exit 1
fi

CURRENT_DIR="$(pwd)"

if [[ ! -f "${CURRENT_DIR}/app.py" || ! -f "${CURRENT_DIR}/requirements.txt" ]]; then
  echo "错误：请在新版 clash-yaml-manager 项目根目录下运行 update.sh。"
  exit 1
fi

if [[ ! -d "${INSTALL_DIR}" ]]; then
  echo "错误：未找到安装目录 ${INSTALL_DIR}。请先运行 install.sh 完成安装。"
  exit 1
fi

TIMESTAMP="$(date +"%Y%m%d_%H%M%S")"
BACKUP_DIR="/root/${SERVICE_NAME}-update-backup-${TIMESTAMP}"

echo "=========================================================="
echo "开始升级 ${SERVICE_NAME}"
echo "=========================================================="
echo "安装目录: ${INSTALL_DIR}"
echo "新版目录: ${CURRENT_DIR}"
echo "备份目录: ${BACKUP_DIR}"

echo "正在备份当前安装目录..."
mkdir -p "${BACKUP_DIR}"

for item in app.py requirements.txt install.sh uninstall.sh update.sh core templates; do
  if [[ -e "${INSTALL_DIR}/${item}" ]]; then
    cp -a "${INSTALL_DIR}/${item}" "${BACKUP_DIR}/"
  fi
done

if [[ -f "${INSTALL_DIR}/.env" ]]; then
  cp -a "${INSTALL_DIR}/.env" "${BACKUP_DIR}/.env"
fi

if [[ -f "${INSTALL_DIR}/defaults/default.yaml" ]]; then
  mkdir -p "${BACKUP_DIR}/defaults"
  cp -a "${INSTALL_DIR}/defaults/default.yaml" "${BACKUP_DIR}/defaults/default.yaml"
fi

if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
  echo "正在停止服务..."
  systemctl stop "${SERVICE_NAME}" || true
fi

echo "正在复制新版应用代码..."
shopt -s dotglob nullglob
for item in "${CURRENT_DIR}"/*; do
  name="$(basename "${item}")"
  case "${name}" in
    .git|venv|uploads|outputs|backups|logs|__pycache__)
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

if [[ ! -d "${INSTALL_DIR}/venv" ]]; then
  echo "未找到虚拟环境，正在创建..."
  python3 -m venv "${INSTALL_DIR}/venv"
fi

echo "正在更新 Python 依赖..."
"${INSTALL_DIR}/venv/bin/pip" install --upgrade pip
"${INSTALL_DIR}/venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"

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

echo "=========================================================="
echo "升级完成。"
echo "已保留: .env、defaults/default.yaml、uploads、outputs、backups、logs"
echo "备份目录: ${BACKUP_DIR}"
echo "查看状态: systemctl status ${SERVICE_NAME}"
echo "=========================================================="
