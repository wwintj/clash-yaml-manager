#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="clash-yaml-manager"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
INSTALL_DIR="/opt/clash-yaml-manager"
TIMESTAMP="$(date +"%Y%m%d_%H%M%S")"
BACKUP_DEST="/root/${SERVICE_NAME}-backup-${TIMESTAMP}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "错误：请使用 root 权限运行此脚本：sudo bash uninstall.sh"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/scripts/deploy-common.sh"
umask 077
managed_account=false
managed_uid=""
if service_account_matches; then
  managed_account=true
  managed_uid="$(id -u "${SERVICE_USER}")"
fi

echo "=========================================================="
echo "开始卸载 ${SERVICE_NAME}"
echo "=========================================================="

echo ">> 步骤 1: 停止并禁用 systemd 服务"
stop_health_units disable
stop_refresh_units disable

if [[ -f "${SERVICE_FILE}" ]] || systemctl is-active --quiet "${SERVICE_NAME}"; then
  if systemctl is-active --quiet "${SERVICE_NAME}"; then
    systemctl stop "${SERVICE_NAME}"
    echo "已停止 ${SERVICE_NAME} 服务。"
  else
    echo "${SERVICE_NAME} 服务当前未运行。"
  fi

  if systemctl is-enabled --quiet "${SERVICE_NAME}" 2>/dev/null; then
    systemctl disable "${SERVICE_NAME}"
    echo "已禁用 ${SERVICE_NAME} 开机自启。"
  else
    echo "${SERVICE_NAME} 服务未设置开机自启。"
  fi
else
  echo "未发现已注册的 ${SERVICE_NAME}.service，跳过停止/禁用。"
fi

if [[ -f "${SERVICE_FILE}" ]]; then
  rm -f "${SERVICE_FILE}"
  echo "已删除 service 文件：${SERVICE_FILE}"
else
  echo "未找到 service 文件，跳过删除：${SERVICE_FILE}"
fi

rm -f "${REFRESH_SERVICE_FILE}" "${REFRESH_TIMER_FILE}" "${HEALTH_SERVICE_FILE}" "${HEALTH_TIMER_FILE}"
systemctl daemon-reload
echo "已重新加载 systemd daemon。"

echo ""
echo ">> 步骤 2: 处理项目文件"

if [[ -d "${INSTALL_DIR}" ]]; then
  read -r -p "是否删除整个项目目录 ${INSTALL_DIR}？[y/N]: " del_dir

  if [[ "${del_dir}" =~ ^[Yy]$ ]]; then
    read -r -p "删除前是否保留 backups、outputs、state 和 .env（含恢复订阅所需密钥）？[Y/n]: " keep_data

    if [[ -z "${keep_data}" || "${keep_data}" =~ ^[Yy]$ ]]; then
      echo "正在将 backups、outputs、state 和 .env 备份至：${BACKUP_DEST}"
      mkdir -p "${BACKUP_DEST}"

      copied_any=0

      if [[ -d "${INSTALL_DIR}/backups" ]]; then
        cp -a "${INSTALL_DIR}/backups" "${BACKUP_DEST}/"
        echo "  - backups 已备份"
        copied_any=1
      else
        echo "  - 未找到 backups 目录，跳过"
      fi

      if [[ -d "${INSTALL_DIR}/outputs" ]]; then
        cp -a "${INSTALL_DIR}/outputs" "${BACKUP_DEST}/"
        echo "  - outputs 已备份"
        copied_any=1
      else
        echo "  - 未找到 outputs 目录，跳过"
      fi

      for item in state .env VERSION INSTALLATION.json; do
        if [[ -e "${INSTALL_DIR}/${item}" ]]; then
          if [[ "${item}" == state ]]; then
            backup_private_state "${INSTALL_DIR}/state" "${BACKUP_DEST}/state"
          else
            cp -a "${INSTALL_DIR}/${item}" "${BACKUP_DEST}/"
          fi
          copied_any=1
        fi
      done

      if [[ "${copied_any}" -eq 1 ]]; then
        chown -hR root:root "${BACKUP_DEST}"
        find "${BACKUP_DEST}" -type d -exec chmod 700 {} +
        find "${BACKUP_DEST}" -type f -exec chmod 600 {} +
        echo "数据备份完成：${BACKUP_DEST}"
      else
        rmdir "${BACKUP_DEST}" 2>/dev/null || true
        echo "没有可备份的数据目录。"
      fi
    else
      echo "用户选择不保留运行数据和认证状态。"
    fi

    echo "正在删除项目目录：${INSTALL_DIR}"
    rm -rf "${INSTALL_DIR}"
    echo "项目目录已删除。"

    # Only an account created and recorded by this project's scripts is eligible.
    # No -r: never remove a home directory or files outside the selected project.
    if [[ "${managed_account}" == true && "$(id -u "${SERVICE_USER}" 2>/dev/null || true)" == "${managed_uid}" ]]; then
      if pgrep -u "${managed_uid}" >/dev/null; then
        echo "clashyaml 仍有进程，保留账户，请管理员核查。"
      else
        userdel "${SERVICE_USER}"
        echo "已删除本项目专用服务账户。"
      fi
    else
      echo "未确认专用账户归属，不删除任何系统用户。"
    fi
  else
    echo "已选择保留项目目录及其所有文件：${INSTALL_DIR}"
    echo "保留服务账户及现有所有权，避免留下无法访问的 state 和运行数据。"
  fi
else
  echo "未找到项目目录 ${INSTALL_DIR}，无需清理项目文件。"
fi

echo ""
echo "=========================================================="
echo "${SERVICE_NAME} 卸载流程执行完毕"
echo "=========================================================="
echo "检查服务状态：systemctl status ${SERVICE_NAME}"
echo "如已删除项目目录，备份数据可能位于：${BACKUP_DEST}"
echo "=========================================================="
