# Clash YAML Manager

一个适合部署在 Ubuntu VPS 上的轻量级 Clash/Mihomo YAML 节点管理面板。

上传 YAML 或使用内置默认 YAML，输入 `vmess://` / `vless://` 节点后，自动替换 `proxies`、清理旧节点引用、补齐策略组，并生成新的 Clash/Mihomo 配置文件。

**Contact:** wwintj@gmail.com

**GitHub About 建议：**

- Description: `轻量级 Clash/Mihomo YAML 节点管理面板，支持默认规则、一键安装、一键升级、vmess/vless 节点注入。`
- Topics: `clash`, `mihomo`, `yaml`, `flask`, `proxy`, `vmess`, `vless`, `vps`

---

## 一键安装

在 Ubuntu VPS 上执行：

```bash
sudo bash -c 'apt-get update -y && apt-get install -y git ca-certificates && rm -rf /tmp/clash-yaml-manager && git clone https://github.com/wwintj/clash-yaml-manager.git /tmp/clash-yaml-manager && cd /tmp/clash-yaml-manager && bash install.sh'
```

安装时会提示输入：

- Web 端口，默认 `8899`
- Web 管理密码

安装完成后访问：

```text
http://你的VPS_IP:端口
```

例如：

```text
http://1.2.3.4:8899
```

---

## 一键升级

适用于已经安装过的 VPS。升级会保留 `.env`、默认 YAML、上传文件、输出文件、备份和日志。

```bash
sudo bash -c 'apt-get update -y && apt-get install -y git ca-certificates && rm -rf /tmp/clash-yaml-manager-update && git clone https://github.com/wwintj/clash-yaml-manager.git /tmp/clash-yaml-manager-update && cd /tmp/clash-yaml-manager-update && bash update.sh'
```

保留内容：

- `/opt/clash-yaml-manager/.env`
- `/opt/clash-yaml-manager/defaults/default.yaml`
- `/opt/clash-yaml-manager/uploads/`
- `/opt/clash-yaml-manager/outputs/`
- `/opt/clash-yaml-manager/backups/`
- `/opt/clash-yaml-manager/logs/`

---

## 一键卸载

```bash
sudo bash /opt/clash-yaml-manager/uninstall.sh
```

卸载脚本会停止服务、禁用开机自启、删除 systemd service，并询问是否删除项目目录。选择删除目录时，可以继续选择是否保留 `backups/` 和 `outputs/`。

---

## Releases

当前版本发布说明见 [CHANGELOG.md](CHANGELOG.md)。

建议首个 GitHub Release：

- Tag: `v1.0.0`
- Title: `v1.0.0 - Default YAML and Update Flow`
- Notes: 复制 [CHANGELOG.md](CHANGELOG.md) 中 `v1.0.0` 小节

---

## 常用命令

```bash
systemctl status clash-yaml-manager
systemctl restart clash-yaml-manager
systemctl stop clash-yaml-manager
journalctl -u clash-yaml-manager -f
tail -f /opt/clash-yaml-manager/logs/app.log
```

如果使用默认端口 `8899` 且启用了 UFW：

```bash
ufw allow 8899/tcp
ufw reload
```

---

## 手动安装

如果你想先把项目上传到 VPS，再手动安装：

```bash
cd /root/clash-yaml-manager
sed -i 's/\r$//' install.sh uninstall.sh update.sh
chmod +x install.sh uninstall.sh update.sh
sudo bash install.sh
```

---

## 节点输入格式

Web 页面支持批量输入节点，每行一个：

```text
国家代码|节点名称|节点链接
```

示例：

```text
US|tim|vmess://xxxx
TW|TW55|vmess://xxxx
JP|JP2|vless://xxxx
HK|GIA|vmess://xxxx
```

支持的国家/地区代码：

| 代码 | 策略组 |
|---|---|
| US | 🇺🇸 美国节点 |
| HK | 🇭🇰 香港节点 |
| TW | 🇹🇼 台湾节点 |
| JP | 🇯🇵 日本节点 |
| KR | 🇰🇷 韩国节点 |
| SG | 🇸🇬 狮城节点 |
| KP | 🇰🇵 朝鲜节点 |
| MY | 🇲🇾 马来西亚节点 |
| DE | 🇩🇪 德国节点 |
| GB | 🇬🇧 英国节点 |
| CA | 🇨🇦 加拿大节点 |

---

## 功能说明

- 可以上传现有 Clash/Mihomo YAML，也可以不上传，直接使用内置默认 YAML。
- 自动删除原 `proxies` 中的旧节点。
- 自动清理 `proxy-groups` 里失效的旧节点引用。
- 支持解析 `vmess://` 和 `vless://`。
- 自动给节点名添加国旗。
- 自动把节点加入通用策略组和对应国家/地区策略组。
- 可选加入 Netflix、YouTube、AI、Telegram、TikTok、HBO、X/Twitter 等特殊策略组。
- 尽量保留原配置里的 `rules`、`rule-providers`、`dns`、`proxy-groups` 和其他自定义字段。
- 上传、输出、备份、日志分目录保存。
- 日志不会记录完整节点链接、UUID 或密码。

---

## 项目结构

```text
clash-yaml-manager/
├── app.py
├── requirements.txt
├── install.sh
├── update.sh
├── uninstall.sh
├── core/
│   ├── parser.py
│   └── yaml_utils.py
├── defaults/
│   └── default.yaml
└── templates/
    └── index.html
```

运行后会自动创建：

```text
uploads/
outputs/
backups/
logs/
```

---

## 安全建议

- 建议使用复杂密码。
- 不建议长期把面板直接暴露在公网。
- 推荐通过 Nginx HTTPS、Tailscale、WireGuard 或 SSH 隧道访问。
- 如果启用 HTTPS，可以在 `/opt/clash-yaml-manager/.env` 中设置：

```text
COOKIE_SECURE=true
```

---

## 常见问题

### 浏览器打不开

```bash
systemctl status clash-yaml-manager
journalctl -u clash-yaml-manager -f
ss -tulnp | grep 8899
```

### 提示 `proxy not found`

说明策略组里还有不存在的节点或策略组引用。工具会尽量自动清理，但遇到特殊 YAML 结构时，建议检查生成后的 `proxy-groups`。

### 想修改默认 YAML

修改：

```text
/opt/clash-yaml-manager/defaults/default.yaml
```

然后重启：

```bash
systemctl restart clash-yaml-manager
```

### 想修改页面样式

修改：

```text
/opt/clash-yaml-manager/templates/index.html
```

然后重启：

```bash
systemctl restart clash-yaml-manager
```
