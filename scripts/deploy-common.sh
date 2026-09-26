#!/usr/bin/env bash
# Sourced only by the root-run deployment scripts. Never source .env.
SERVICE_USER="clashyaml"
SERVICE_GROUP="clashyaml"
ACCOUNT_MARKER="${INSTALL_DIR}/.service-account"

service_account_matches() {
  local account account_name _account_pass account_uid account_gid account_comment account_home account_shell
  [[ -f "${ACCOUNT_MARKER}" && ! -L "${ACCOUNT_MARKER}" ]] || return 1
  account="$(getent passwd "${SERVICE_USER}")" || return 1
  IFS=: read -r account_name _account_pass account_uid account_gid account_comment account_home account_shell <<< "${account}"
  [[ "${account_name}" == "${SERVICE_USER}" && "${account_uid}" =~ ^[0-9]+$ && "${account_uid}" -ne 0 &&
     "${account_comment}" == "Clash YAML Manager service" && "${account_home}" == /nonexistent &&
     "${account_shell}" == /usr/sbin/nologin &&
     "$(cat "${ACCOUNT_MARKER}")" == "${SERVICE_USER}:${account_uid}:${account_gid}" ]]
}

ensure_service_user() {
  if getent passwd "${SERVICE_USER}" >/dev/null; then
    if ! service_account_matches; then
      echo "错误：clashyaml 已存在但无法确认属于本项目，停止迁移；不会修改其他账户。" >&2
      return 1
    fi
    return
  fi
  if getent group "${SERVICE_GROUP}" >/dev/null || [[ -e "${ACCOUNT_MARKER}" || -L "${ACCOUNT_MARKER}" ]]; then
    echo "错误：服务用户/组或所有权标记不一致，请管理员核查。" >&2
    return 1
  fi
  useradd --system --user-group --home-dir /nonexistent --no-create-home \
    --shell /usr/sbin/nologin --comment "Clash YAML Manager service" "${SERVICE_USER}"
  printf '%s:%s:%s\n' "${SERVICE_USER}" "$(id -u "${SERVICE_USER}")" "$(id -g "${SERVICE_USER}")" > "${ACCOUNT_MARKER}"
  chown root:root "${ACCOUNT_MARKER}"
  chmod 600 "${ACCOUNT_MARKER}"
}

repair_permissions() {
  local entry name directory
  [[ ! -L "${INSTALL_DIR}" && ! -L "${INSTALL_DIR}/.env" ]] || return 1
  chown root:root "${INSTALL_DIR}"
  chmod 755 "${INSTALL_DIR}"
  shopt -s dotglob nullglob
  for entry in "${INSTALL_DIR}"/*; do
    name="$(basename "${entry}")"
    case "${name}" in
      uploads|outputs|backups|logs|state|.env|.service-account|.git) continue ;;
    esac
    # Do not follow symlinks into another application or the system Python.
    chown -hR root:root "${entry}"
    find "${entry}" -type d -exec chmod 755 {} +
    find "${entry}" -type f -exec chmod u=rwX,go=rX {} +
  done
  shopt -u dotglob nullglob
  for directory in uploads outputs backups logs state; do
    [[ ! -L "${INSTALL_DIR}/${directory}" ]] || { echo "拒绝迁移符号链接运行目录。" >&2; return 1; }
    mkdir -p "${INSTALL_DIR}/${directory}"
    find "${INSTALL_DIR}/${directory}" -exec chown -h "${SERVICE_USER}:${SERVICE_GROUP}" {} +
    find "${INSTALL_DIR}/${directory}" -type d -exec chmod 700 {} +
    find "${INSTALL_DIR}/${directory}" -type f -exec chmod 600 {} +
  done
  chown root:root "${INSTALL_DIR}/.env" "${ACCOUNT_MARKER}"
  chmod 600 "${INSTALL_DIR}/.env" "${ACCOUNT_MARKER}"
}

write_service_unit() {
  local bind_capability=""
  if (( APP_PORT < 1024 )); then
    # Preserve existing low-port installs without running Python as root.
    bind_capability=$'AmbientCapabilities=CAP_NET_BIND_SERVICE\nCapabilityBoundingSet=CAP_NET_BIND_SERVICE'
  fi
  cat > "${SERVICE_FILE}" <<EOF
[Unit]
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
${bind_capability}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${INSTALL_DIR}/.env
ExecStart=${INSTALL_DIR}/venv/bin/gunicorn -w 2 --timeout 300 -b 0.0.0.0:\${APP_PORT} app:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  chmod 644 "${SERVICE_FILE}"
}
