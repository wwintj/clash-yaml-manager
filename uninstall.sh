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

echo "=========================================================="
echo "开始卸载 ${SERVICE_NAME}"
echo "=========================================================="

echo ">> 步骤 1: 停止并禁用 systemd 服务"

if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
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

systemctl daemon-reload
echo "已重新加载 systemd daemon。"

echo ""
echo ">> 步骤 2: 处理项目文件"

if [[ -d "${INSTALL_DIR}" ]]; then
  read -r -p "是否删除整个项目目录 ${INSTALL_DIR}？[y/N]: " del_dir

  if [[ "${del_dir}" =~ ^[Yy]$ ]]; then
    read -r -p "删除前是否保留 backups 和 outputs？[Y/n]: " keep_data

    if [[ -z "${keep_data}" || "${keep_data}" =~ ^[Yy]$ ]]; then
      echo "正在将 backups 和 outputs 备份至：${BACKUP_DEST}"
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

      if [[ "${copied_any}" -eq 1 ]]; then
        chmod -R go-rwx "${BACKUP_DEST}" || true
        echo "数据备份完成：${BACKUP_DEST}"
      else
        rmdir "${BACKUP_DEST}" 2>/dev/null || true
        echo "没有可备份的数据目录。"
      fi
    else
      echo "用户选择不保留 backups 和 outputs。"
    fi

    echo "正在删除项目目录：${INSTALL_DIR}"
    rm -rf "${INSTALL_DIR}"
    echo "项目目录已删除。"
  else
    echo "已选择保留项目目录及其所有文件：${INSTALL_DIR}"
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
