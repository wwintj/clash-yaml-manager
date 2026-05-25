# Clash YAML Manager

`clash-yaml-manager` 是一个适合部署在 Ubuntu VPS 上的轻量级 Clash/Mihomo YAML 节点管理面板。

它可以通过 Web 页面上传现有 Clash/Mihomo YAML 配置文件，自动删除原配置中的 `proxies` 节点池，清理策略组中失效的旧节点引用，然后写入新的 `vmess://` / `vless://` 节点，并尽量保留原配置中的 `rules`、`rule-providers`、`dns`、`proxy-groups` 以及其他自定义字段。

> 适用场景：你想保留朋友或第三方配置文件里的分流规则和策略组结构，但替换成自己的节点。

---

## ✨ 核心特性

- **保留原配置结构**  
  使用 `ruamel.yaml` 处理 YAML，尽量保留原文件顺序、缩进、注释和整体结构。

- **自动清理旧节点**  
  自动删除原 `proxies` 中的旧节点，并同步清理 `proxy-groups` 中失效的旧节点引用，避免出现 `proxy not found`。

- **支持节点链接解析**  
  支持解析 `vmess://` 和 `vless://` 分享链接，并转换为 Clash/Mihomo 可用的节点配置。

- **自动添加国旗和国家策略组**  
  根据输入的国家/地区代码自动生成节点显示名，例如：
  - `US|tim|vmess://...` → `🇺🇸 tim`
  - `HK|GIA|vmess://...` → `🇭🇰 GIA`

- **自动加入策略组**  
  新节点会自动加入通用策略组，例如：
  - `🚀 节点选择`
  - `🚀 手动切换`
  - `🐟 漏网之鱼`

  同时会根据国家代码加入对应国家策略组，例如：
  - `🇺🇸 美国节点`
  - `🇭🇰 香港节点`
  - `🇹🇼 台湾节点`
  - `🇯🇵 日本节点`

- **空策略组兜底处理**  
  如果清理旧节点后某些策略组变为空，会自动进行合理填充，避免 Clash/Mihomo 导入异常。

- **安全文件管理**  
  上传文件、输出文件和备份文件分目录保存：
  - `uploads/`
  - `outputs/`
  - `backups/`
  - `logs/`

- **脱敏日志**  
  日志不会记录完整节点链接、UUID、password 等敏感信息。

---

## 📁 项目结构

```text
clash-yaml-manager/
├── app.py
├── requirements.txt
├── install.sh
├── uninstall.sh
├── core/
│   ├── parser.py
│   └── yaml_utils.py
├── templates/
│   └── index.html
├── static/
├── uploads/
├── outputs/
├── backups/
└── logs/
```

---

## 🚀 安装方式一：本地上传到 VPS 后安装

如果你是在本地电脑整理好项目文件，建议使用这种方式。

### 1. 上传项目目录

把整个 `clash-yaml-manager` 文件夹上传到 VPS，例如：

```text
/root/clash-yaml-manager
```

上传后 VPS 上应该类似这样：

```text
/root/clash-yaml-manager/
├── app.py
├── requirements.txt
├── install.sh
├── uninstall.sh
├── core/
│   ├── parser.py
│   └── yaml_utils.py
└── templates/
    └── index.html
```

### 2. 登录 VPS

```bash
ssh root@你的VPS_IP
```

### 3. 进入项目目录

```bash
cd /root/clash-yaml-manager
```

### 4. 修复 Windows 换行符并添加执行权限

如果项目文件是从 Windows 上传的，建议先执行：

```bash
sed -i 's/\r$//' install.sh uninstall.sh
chmod +x install.sh uninstall.sh
```

### 5. 执行安装

```bash
bash install.sh
```

安装过程中会提示你输入：

- Web 运行端口，默认 `8899`
- Web 管理密码，必填

安装完成后，浏览器访问：

```text
http://你的VPS_IP:端口
```

例如：

```text
http://1.2.3.4:8899
```

---

## 🚀 安装方式二：GitHub 一键部署

如果项目已经上传到 GitHub，可以在 VPS 上执行下面这一条命令完成拉取和安装。

> 默认仓库地址：`https://github.com/wwintj/clash-yaml-manager.git`  
> 如果你的仓库地址不同，请把命令里的 GitHub 地址替换成你自己的仓库地址。

```bash
sudo bash -c 'apt-get update -y && apt-get install -y git ca-certificates && rm -rf /tmp/clash-yaml-manager && git clone https://github.com/wwintj/clash-yaml-manager.git /tmp/clash-yaml-manager && cd /tmp/clash-yaml-manager && bash install.sh'
```

安装过程中会提示你输入：

- Web 运行端口，默认 `8899`
- Web 管理密码，必填

安装完成后，浏览器访问：

```text
http://你的VPS_IP:端口
```

例如：

```text
http://1.2.3.4:8899
```

### 分步安装方式

如果你想一步一步执行，也可以使用下面方式：

```bash
sudo apt-get update -y
sudo apt-get install -y git ca-certificates
rm -rf /tmp/clash-yaml-manager
git clone https://github.com/wwintj/clash-yaml-manager.git /tmp/clash-yaml-manager
cd /tmp/clash-yaml-manager
sudo bash install.sh
```

> 注意：仓库需要是公开仓库，或者你的 VPS 已经配置好 GitHub SSH Key / Token，否则 `git clone` 会失败。

不要使用下面这种 Markdown 链接格式作为 Linux 命令：

```text
git clone [https://github.com/wwintj/clash-yaml-manager.git](https://github.com/wwintj/clash-yaml-manager.git)
```

上面这种写法只适合 Markdown 文档展示，不能直接在终端执行。

---

## 🧩 节点输入格式

Web 页面支持批量输入节点，每行一个节点：

```text
国家代码|节点名称|节点链接
```

示例：

```text
US|tim|vmess://xxxx
TW|TW55|vmess://xxxx
KP|CHUNCHEON|vmess://xxxx
JP|JP2|vmess://xxxx
KR|SEOUL|vmess://xxxx
SG|US-01|vmess://xxxx
HK|GIA|vmess://xxxx
```

支持的国家/地区代码包括：

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

## 🛠️ 服务管理命令

安装完成后，服务名称为：

```text
clash-yaml-manager
```

常用命令：

```bash
systemctl status clash-yaml-manager
systemctl restart clash-yaml-manager
systemctl stop clash-yaml-manager
```

查看 systemd 日志：

```bash
journalctl -u clash-yaml-manager -f
```

查看应用日志：

```bash
tail -f /opt/clash-yaml-manager/logs/app.log
```

查看监听端口：

```bash
ss -tulnp | grep 8899
```

---

## 🗑️ 卸载

执行：

```bash
sudo bash /opt/clash-yaml-manager/uninstall.sh
```

卸载脚本会：

1. 停止 `clash-yaml-manager` 服务；
2. 禁用开机自启；
3. 删除 systemd service 文件；
4. 询问是否删除 `/opt/clash-yaml-manager`；
5. 如果选择删除项目目录，会继续询问是否保留 `backups/` 和 `outputs/`。

如果选择保留备份和输出文件，会复制到类似下面的目录：

```text
/root/clash-yaml-manager-backup-时间戳
```

---

## 🔐 安全建议

- 请设置一个足够复杂的 Web 管理密码。
- 如果直接公网访问，请在防火墙或云服务商安全组中只开放必要端口。
- 建议通过以下方式之一访问：
  - Nginx 反向代理 + HTTPS
  - Tailscale
  - WireGuard
  - SSH 隧道
- 如果启用 HTTPS，可以在 `.env` 中设置：

```text
COOKIE_SECURE=true
```

- 不建议把本工具长期暴露在公网且使用弱密码。

---

## 🔥 防火墙放行端口

如果你的系统启用了 UFW，并且安装时使用默认端口 `8899`，可以执行：

```bash
ufw allow 8899/tcp
ufw reload
```

如果你使用云服务器，请同时检查云平台安全组是否放行对应 TCP 端口。

---

## ❗ 常见问题

### 1. 浏览器打不开页面

先检查服务状态：

```bash
systemctl status clash-yaml-manager
```

查看日志：

```bash
journalctl -u clash-yaml-manager -f
```

检查端口：

```bash
ss -tulnp | grep 8899
```

### 2. 提示 `proxy not found`

说明某些策略组引用了不存在的节点或策略组。  
本工具会尽量自动清理旧节点引用，但如果原始 YAML 中存在特殊结构，需要检查生成后的 YAML 中对应策略组。

### 3. 上传后没有生成文件

请查看页面错误提示，或查看应用日志：

```bash
tail -f /opt/clash-yaml-manager/logs/app.log
```

### 4. `requirements.txt` 找不到

请确认文件名是：

```text
requirements.txt
```

不是：

```text
requirements
```

Windows 可能会隐藏扩展名，建议打开“显示文件扩展名”后检查。

---

## 📌 当前版本说明

当前版本主要用于个人 VPS 上的 Clash/Mihomo YAML 节点替换和策略组维护，不包含：

- 在线节点测速；
- 远程订阅转换；
- 自动推送到 Clash 客户端；
- 多用户权限管理；
- 数据库存储。

这些功能可以作为后续版本继续扩展。
