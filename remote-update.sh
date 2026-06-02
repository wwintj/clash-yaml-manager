#!/usr/bin/env bash
set -euo pipefail

REPO="${REPO:-https://github.com/wwintj/clash-yaml-manager.git}"
TMP="${TMP:-/tmp/clash-yaml-manager-update}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "错误：请使用 root 权限运行此脚本。"
  exit 1
fi

echo "正在准备升级环境..."
apt-get update -y
apt-get install -y git ca-certificates

echo "正在拉取最新版代码..."
rm -rf "${TMP}"
git clone --depth=1 "${REPO}" "${TMP}"

cd "${TMP}"
sed -i 's/\r$//' update.sh

echo "正在执行升级..."
bash update.sh
