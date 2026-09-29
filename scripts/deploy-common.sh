#!/usr/bin/env bash
# Sourced only by the root-run deployment scripts. Never source .env.
SERVICE_USER="clashyaml"
SERVICE_GROUP="clashyaml"
ACCOUNT_MARKER="${INSTALL_DIR}/.service-account"
REFRESH_SERVICE_NAME="${SERVICE_NAME}-refresh"
REFRESH_SERVICE_FILE="${SERVICE_FILE%.service}-refresh.service"
REFRESH_TIMER_FILE="${SERVICE_FILE%.service}-refresh.timer"

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
      bin|uploads|outputs|backups|logs|state|.env|.service-account|.git) continue ;;
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

backup_private_state() {
  local source_dir="$1" destination_dir="$2" item name
  mkdir -p "${destination_dir}"
  chmod 700 "${destination_dir}"
  shopt -s dotglob nullglob
  for item in "${source_dir}"/*; do
    name="$(basename "${item}")"
    # A hard-killed Web worker can leave a sensitive ephemeral Mihomo config.
    # It is runtime scratch data, not backup material.
    [[ "${name}" == .proxy-probe-* ]] && continue
    cp -a "${item}" "${destination_dir}/"
  done
  shopt -u dotglob nullglob
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
ExecStart=${INSTALL_DIR}/venv/bin/gunicorn --no-control-socket -w 2 --timeout 300 -b 0.0.0.0:\${APP_PORT} app:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  chmod 644 "${SERVICE_FILE}"
}

write_refresh_units() {
  cat > "${REFRESH_SERVICE_FILE}" <<EOF
[Unit]
Description=Refresh due Clash YAML fixed subscription sources
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=clashyaml
Group=clashyaml
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
Environment=PYTHONDONTWRITEBYTECODE=1
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${INSTALL_DIR}/.env
ExecStart=${INSTALL_DIR}/venv/bin/python -m core.auto_refresh --once
TimeoutStartSec=20min
EOF
  cat > "${REFRESH_TIMER_FILE}" <<EOF
[Unit]
Description=Schedule Clash YAML fixed subscription refreshes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
AccuracySec=30s
RandomizedDelaySec=30s
Persistent=true
Unit=${REFRESH_SERVICE_NAME}.service

[Install]
WantedBy=timers.target
EOF
  chmod 644 "${REFRESH_SERVICE_FILE}" "${REFRESH_TIMER_FILE}"
}

stop_refresh_units() {
  # Stop the timer first, then wait for the oneshot to stop before state/code changes.
  if [[ -f "${REFRESH_TIMER_FILE}" ]] || systemctl is-active --quiet "${REFRESH_SERVICE_NAME}.timer"; then
    systemctl stop "${REFRESH_SERVICE_NAME}.timer"
    if [[ "${1:-}" == disable ]]; then
      systemctl disable "${REFRESH_SERVICE_NAME}.timer"
    fi
  fi
  if [[ -f "${REFRESH_SERVICE_FILE}" ]] || systemctl is-active --quiet "${REFRESH_SERVICE_NAME}.service"; then
    systemctl stop "${REFRESH_SERVICE_NAME}.service"
  fi
}

wait_for_application() {
  # SECONDS is Bash's elapsed clock: slow HTTP attempts consume the same budget.
  # The attempt cap also bounds retries when commands return immediately.
  local max_wait="${1:-30}" attempt remaining request_timeout http_status
  local deadline=$((SECONDS + max_wait))
  echo "Waiting for application health check (up to ${max_wait}s)..."
  for ((attempt=1; attempt<=max_wait; attempt++)); do
    remaining=$((deadline - SECONDS))
    (( remaining > 0 )) || break
    request_timeout=2
    (( remaining >= request_timeout )) || request_timeout="${remaining}"
    # Do not follow redirects or use an operator's outbound HTTP proxy.
    # Silence expected connection refusals while workers are still loading.
    if http_status="$(curl --silent --fail --noproxy '*' --output /dev/null \
        --write-out '%{http_code}' --connect-timeout "${request_timeout}" \
        --max-time "${request_timeout}" "http://127.0.0.1:${APP_PORT}/healthz" 2>/dev/null)" &&
        [[ "${http_status}" == 200 ]] &&
        systemctl is-active --quiet "${SERVICE_NAME}" && (( SECONDS < deadline )); then
      echo "Health check attempt ${attempt}/${max_wait}: PASS"
      echo "Service is healthy."
      return 0
    fi
    echo "Health check attempt ${attempt}/${max_wait}: not ready"
    (( SECONDS < deadline && attempt < max_wait )) || break
    sleep 1
  done
  echo "Health check FAILED" >&2
  echo "systemctl status ${SERVICE_NAME} --no-pager -l" >&2
  systemctl status "${SERVICE_NAME}" --no-pager -l >&2 || true
  echo "journalctl -u ${SERVICE_NAME} -n 50 --no-pager" >&2
  journalctl -u "${SERVICE_NAME}" -n 50 --no-pager >&2 || true
  return 1
}
