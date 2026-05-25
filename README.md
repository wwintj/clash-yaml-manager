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

---

## 🚀 一键安装

请通过 SSH 登录到你的 Ubuntu VPS (推荐 22.04 / 24.04)，直接复制并运行以下一键命令：

```bash
git clone [https://github.com/wwintj/clash-yaml-manager.git](https://github.com/wwintj/clash-yaml-manager.git) && cd clash-yaml-manager && sudo bash install.sh

```

> **提示**：安装过程中系统会提示你设置**运行端口**（默认 8899）和**Web管理密码**（必填）。安装完成后，即可在浏览器访问 `http://你的服务器IP:端口`。

---

## 🗑️ 一键卸载

如果你不再需要本工具，或者需要彻底清理环境，请运行以下一键卸载命令：

```bash
sudo bash /opt/clash-yaml-manager/uninstall.sh

```

> **提示**：卸载脚本会安全停止后台服务，并询问你是否需要打包备份生成的配置和历史文件。

---

## 🛠️ 服务管理常用命令

安装成功后，你可以随时使用以下系统标准命令来管理后台服务：

* **查看运行状态**：`systemctl status clash-yaml-manager`
* **重启应用服务**：`systemctl restart clash-yaml-manager`
* **停止应用服务**：`systemctl stop clash-yaml-manager`
* **查看脱敏日志**：`tail -f /opt/clash-yaml-manager/logs/app.log`

## ⚠️ 安全建议

* 请确保你的 VPS 防火墙（如 UFW 或云服务商安全组）已放行你在安装时设置的端口。
* 强烈建议搭配 Nginx 反向代理并配置 SSL 证书（HTTPS）来访问本面板，或者通过 Tailscale 组建虚拟局域网限制公网直接访问。

```

```
