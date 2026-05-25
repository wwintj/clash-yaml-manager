没问题，这里是纯净的 Markdown 版本。你可以点击代码块右上角的“复制”按钮，然后直接粘贴到你 GitHub 仓库里的 `README.md` 文件中：

```markdown
# Clash YAML Manager

这是一个专为部署在 VPS 上的轻量级 Clash/Mihomo YAML 节点管理面板。

它可以让你通过 Web 界面安全、无损地更新你的代理节点。系统会自动替换 `proxies` 节点池，智能清理失效的策略组引用，并**完美保留**你原有的 `rules`、`rule-providers`、`dns` 以及复杂的策略组拓扑结构。

## ✨ 核心特性

* **无损更新**：基于 `ruamel.yaml` 解析，完美保留原配置文件的注释、缩进和排序。
* **智能解析**：原生支持 `vmess://` 和 `vless://` (包含 Reality/TLS) 分享链接解析。
* **自动化编排**：自动根据节点国家代码添加 🇺🇸 🇭🇰 🇯🇵 等国旗 Emoji，并自动归类到对应的国家策略组与通用测速组。
* **安全隔离**：独立管理上传文件与生成文件，自动完成原始 YAML 配置的安全备份。
* **脱敏日志**：完善的错误校验与提示机制，日志彻底脱敏，不记录任何敏感节点链接和 UUID。

## 🚀 快速部署

本项目提供了一键部署脚本，支持 Ubuntu 22.04 / 24.04，自动配置 Python 虚拟环境并使用 Systemd + Gunicorn 进行服务守护。

### 1. 克隆仓库
```bash
git clone [https://github.com/wwintj/clash-yaml-manager.git](https://github.com/wwintj/clash-yaml-manager.git)
cd clash-yaml-manager

```

### 2. 执行一键安装

```bash
sudo bash install.sh

```

安装过程中，系统会提示你设置：

* **运行端口**（默认 8899）
* **Web 管理面板密码**（必填，请务必设置强密码）

安装完成后，直接在浏览器访问 `http://你的服务器IP:端口` 即可使用。

## 🛠️ 服务管理命令

安装成功后，你可以使用系统标准的 `systemctl` 命令来管理服务：

* **查看服务状态**：`systemctl status clash-yaml-manager`
* **重启服务**：`systemctl restart clash-yaml-manager`
* **停止服务**：`systemctl stop clash-yaml-manager`
* **查看运行日志**：`journalctl -u clash-yaml-manager -f`
* **查看应用业务日志**：`tail -f /opt/clash-yaml-manager/logs/app.log`

## 🗑️ 彻底卸载

如果你不再需要本工具，或者需要彻底清理重装，只需在项目目录下执行：

```bash
sudo bash uninstall.sh

```

卸载脚本会引导你停止并清理后台服务，同时你可以选择是否保留 `backups/`（原始配置备份）和 `outputs/`（生成文件）目录的数据。

## ⚠️ 安全建议

* 请确保你的 VPS 防火墙（如 UFW）已放行你在安装时设置的端口。
* 强烈建议通过 Nginx 反向代理并配置 SSL 证书（HTTPS）来访问本面板，或者通过 Tailscale 等虚拟局域网限制公网直接访问。

```

```
