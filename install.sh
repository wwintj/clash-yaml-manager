#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="clash-yaml-manager"
INSTALL_DIR="/opt/clash-yaml-manager"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ "${EUID}" -ne 0 ]]; then
  echo "错误：请使用 root 权限运行此脚本：sudo bash install.sh"
  exit 1
fi

echo "=========================================================="
echo "开始安装 clash-yaml-manager"
echo "=========================================================="

echo "正在更新包列表并安装系统依赖..."
apt-get update -y
apt-get install -y python3 python3-venv python3-pip curl iproute2 ca-certificates

CURRENT_DIR="$(pwd)"

if [[ ! -f "${CURRENT_DIR}/app.py" || ! -f "${CURRENT_DIR}/requirements.txt" ]]; then
  echo "错误：请在 clash-yaml-manager 项目根目录下运行 install.sh。"
  echo "当前目录缺少 app.py 或 requirements.txt。"
  exit 1
fi

if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
  echo "检测到已有 systemd 服务，正在停止旧服务..."
  systemctl stop "${SERVICE_NAME}" || true
fi

if [[ -d "${INSTALL_DIR}" && "${CURRENT_DIR}" != "${INSTALL_DIR}" ]]; then
  read -r -p "安装目录 ${INSTALL_DIR} 已存在，是否覆盖应用代码？backups/outputs/uploads/logs 默认保留。[y/N]: " overwrite
  if [[ ! "${overwrite}" =~ ^[Yy]$ ]]; then
    echo "安装已取消。"
    exit 0
  fi
fi

if [[ "${CURRENT_DIR}" != "${INSTALL_DIR}" ]]; then
  echo "正在复制项目文件到 ${INSTALL_DIR} ..."
  mkdir -p "${INSTALL_DIR}"

  # 保留运行数据目录，只覆盖应用代码。
  shopt -s dotglob nullglob
  for item in "${CURRENT_DIR}"/*; do
    name="$(basename "${item}")"
    case "${name}" in
      venv|uploads|outputs|backups|logs|.git|__pycache__)
        continue
        ;;
      *)
        rm -rf "${INSTALL_DIR:?}/${name}"
        cp -a "${item}" "${INSTALL_DIR}/"
        ;;
    esac
  done
  shopt -u dotglob nullglob
fi

echo "正在创建必要目录..."
mkdir -p "${INSTALL_DIR}/uploads" "${INSTALL_DIR}/outputs" "${INSTALL_DIR}/backups" "${INSTALL_DIR}/logs" "${INSTALL_DIR}/static"
chmod 700 "${INSTALL_DIR}/uploads" "${INSTALL_DIR}/outputs" "${INSTALL_DIR}/backups" "${INSTALL_DIR}/logs"

APP_PORT="8899"
while true; do
  read -r -p "请输入运行端口（默认 8899）: " input_port
  APP_PORT="${input_port:-8899}"

  if ! [[ "${APP_PORT}" =~ ^[0-9]+$ ]]; then
    echo "错误：端口必须是纯数字。"
    continue
  fi

  if (( APP_PORT < 1 || APP_PORT > 65535 )); then
    echo "错误：端口范围必须是 1-65535。"
    continue
  fi

  if ss -H -ltnu | awk '{print $5}' | grep -qE "(:|\])${APP_PORT}$"; then
    echo "错误：端口 ${APP_PORT} 已被占用，请更换端口。"
    continue
  fi

  break
done

APP_PASSWORD=""
while [[ -z "${APP_PASSWORD}" ]]; do
  read -r -s -p "请输入 Web 管理密码（必填，可包含空格和特殊字符，不显示）: " APP_PASSWORD
  echo
  if [[ -z "${APP_PASSWORD}" ]]; then
    echo "错误：密码不能为空。"
    continue
  fi
done

APP_PASSWORD_B64="$(APP_PASSWORD="${APP_PASSWORD}" python3 - <<'PY'
import base64
import os

print(base64.b64encode(os.environ["APP_PASSWORD"].encode("utf-8")).decode("ascii"))
PY
)"

echo "正在生成随机 SECRET_KEY..."
SECRET_KEY="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"

echo "正在创建 Python 虚拟环境..."
cd "${INSTALL_DIR}"
python3 -m venv venv

echo "正在安装 Python 依赖..."
"${INSTALL_DIR}/venv/bin/pip" install --upgrade pip
"${INSTALL_DIR}/venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"

echo "正在写入环境变量配置文件..."
ENV_FILE="${INSTALL_DIR}/.env"
cat > "${ENV_FILE}" <<EOF
APP_PASSWORD_B64=${APP_PASSWORD_B64}
APP_PORT=${APP_PORT}
SECRET_KEY=${SECRET_KEY}
COOKIE_SECURE=false
EOF
chmod 600 "${ENV_FILE}"

echo "正在配置 systemd 服务..."
cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=clash-yaml-manager
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${INSTALL_DIR}/venv/bin/gunicorn -w 2 --timeout 300 -b 0.0.0.0:\${APP_PORT} app:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

SERVER_IP="服务器IP"
if command -v curl >/dev/null 2>&1; then
  SERVER_IP="$(curl -s --max-time 3 https://api.ipify.org || true)"
  SERVER_IP="${SERVER_IP:-服务器IP}"
fi

echo "=========================================================="
echo "clash-yaml-manager 安装成功！"
echo "=========================================================="
echo "访问地址: http://${SERVER_IP}:${APP_PORT}"
echo ""
echo "服务管理命令:"
echo "  systemctl status ${SERVICE_NAME}"
echo "  systemctl restart ${SERVICE_NAME}"
echo "  systemctl stop ${SERVICE_NAME}"
echo ""
echo "日志查看命令:"
echo "  journalctl -u ${SERVICE_NAME} -f"
echo "  tail -f ${INSTALL_DIR}/logs/app.log"
echo ""
echo "项目目录:"
echo "  ${INSTALL_DIR}"
echo "=========================================================="
