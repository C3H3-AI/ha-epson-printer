# Epson Printer

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]][license]
[![hacs][hacs-badge]][hacs]
[![Home Assistant][ha-badge]][ha]

> 📘 **[中文文档](#中文文档) | [English](#english)**

Home Assistant 爱普生打印机集成 —— 墨水量、打印页数统计、打印机状态、IPP 实时监控，以及 RAW 9100 / IPP 631 打印控制。

> **灵感来源**：[ha-epson-ecotank-stats](https://github.com/wwerther/ha-epson-ecotank-stats)。
> 在其基础上扩展了 IPP 监控、打印机控制服务（含统一打印入口），以及更广泛的机型支持。

---

<a name="中文文档"></a>
# 中文文档

## 📋 功能特性

- **🖨️ 墨水量** —— 黑 / 青 / 品红 / 黄 百分比
- **📄 打印页数** —— 总计、黑白、彩色、双面、单面，以及按功能（打印/复印/扫描/传真）、按纸张尺寸、按打印语言的细分统计
- **✅ 打印机状态** —— Epson Connect 状态、固件版本、序列号、MAC、型号、维护箱寿命、扫描仪状态
- **📅 首次打印日期** ——（打印机支持时显示，否则不可用）
- **🔌 IPP 实时监控** —— 打印机实时状态、运行时间、队列任务数、是否接受任务、每分钟页数（打印机支持时）
- **🛠️ 打印控制** —— 统一 `print` 服务（智能路由）+ 维护类服务：
  - 打印文本 / 文件（PDF、图片等）
  - 打印 Office 文档（Word / Excel 等，经 LibreOffice 转 PDF）
  - 清洗打印头（轻 / 深度）
  - 喷嘴检查图案
- **⏱️ 可配置轮询间隔** —— 默认 5 分钟，最小 30 秒
- **🔍 自动发现** —— 支持 mDNS / zeroconf 局域网发现，也可手动输入 IP
- **🎨 官方品牌图标** —— 采用爱普生官方图标（`brand/icon.png`、`brand/logo.png`）

---

## ✅ 支持的打印机

适用于任何带**内置 Web 服务器**的爱普生打印机（多数 EcoTank、WorkForce、Expression 系列）。

| 打印机 | 墨水 | 页数 | 状态 | IPP | RAW |
|---------|:---:|:-----:|:------:|:---:|:---:|
| EcoTank L3250 | ✅ | ✅ | ✅ | ⚠️ 部分 | ✅ |
| EcoTank L4160 / L4260 | ✅ | ✅ | ✅ | ✅ | ✅ |
| WorkForce 系列 | ✅ | ✅ | ✅ | ✅ | ✅ |
| Expression 系列 | ✅ | ✅ | ✅ | ⚠️ 部分 | ✅ |
| 其他型号 | ✅ | ✅ | ✅ | 视情况 | ✅ |

> **注意**：消费级打印机可能不支持全部 IPP 属性（如 `printer-state`、`queued-job-count`）。
> 缺失的属性会优雅地回退为 `unavailable` —— 即使没有 IPP，集成也能完整工作。

---

## ⚙️ 安装

### HACS（推荐）

1. 确保你的 Home Assistant 已安装 [HACS](https://hacs.xyz/)。
2. 进入 **HACS → 集成 → 右上角三个点 → 自定义仓库**。
3. 添加仓库地址：`https://github.com/C3H3-AI/ha-epson-printer`
4. 分类选择：**集成（Integration）**
5. 点击 **下载 / 安装**。
6. 重启 Home Assistant。

### 手动安装

1. 下载最新的 Release 压缩包。
2. 将 `custom_components/epson_printer/` 解压到你的 `config/custom_components/` 目录。
3. 重启 Home Assistant。

---

## 🔧 配置

**1. 找到打印机的 IP 地址** —— 在路由器 DHCP 列表查看，或从打印机打印网络状态页。

**2. 添加集成**

进入 **设置 → 设备与服务 → 添加集成** → 搜索 **Epson Printer**。
也可点击：[![添加集成](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=epson_printer)

添加时支持局域网自动发现（mDNS），也可在发现列表中选择「手动输入 IP」。

**3. 填写配置**

| 字段 | 默认值 | 说明 |
|-------|---------|-------------|
| **主机（Host）** | — | 打印机 IP 地址（如 `192.168.1.100`） |
| **名称（Name）** | `Epson Printer` | 显示名称 |
| **协议（Scheme）** | `http` | `http` 或 `https`（失败自动回退） |
| **端口（Port）** | `80` | Web 管理页端口 |

集成会自动探测正确的 URL 协议（HTTP/HTTPS 自动回退）。

**4. 选项（添加后调整）**

进入 **设置 → 设备与服务 → Epson Printer → 配置**，可调整：

| 选项 | 默认值 | 说明 |
|-------|---------|-------------|
| **轮询间隔** | `300` | 刷新间隔（秒），最小 30 |
| **转换 Office 文档** | 关闭 | 开启后可用 `print` 服务打印 Word/Excel（需安装 LibreOffice） |
| **LibreOffice 路径** | `soffice` | LibreOffice 可执行文件路径（不在 PATH 时填绝对路径） |

---

## 📊 传感器

### 墨水传感器（4，默认启用）

| 实体键 | 单位 | 说明 |
|-----------|------|------|
| `ink_k` | % | 黑色墨量 |
| `ink_c` | % | 青色墨量 |
| `ink_m` | % | 品红墨量 |
| `ink_y` | % | 黄色墨量 |

### 打印页数传感器（5）

| 实体键 | 单位 | 状态类 | 默认 |
|-----------|------|-------------|------|
| `pages_total` | pages | total_increasing | 启用 |
| `pages_bw` | pages | total_increasing | 禁用 |
| `pages_color` | pages | total_increasing | 禁用 |
| `pages_duplex` | pages | total_increasing | 禁用 |
| `pages_simplex` | pages | total_increasing | 禁用 |

### 分页统计传感器（15+，默认禁用）

- **按功能（10）**：`function_bw_print`、`function_color_print`、`function_bw_copy`、`function_color_copy`、`function_bw_scan`、`function_color_scan`、`function_bw_fax`、`function_color_fax`、`function_bw_other`、`function_color_other`
- **按尺寸（动态）**：`pages_size_*`（如 `pages_size_A4`，按打印机实际报告）
- **按打印语言（动态）**：`pages_language_*`（按打印机实际报告）

### 状态与诊断传感器

| 实体键 | 类别 | 默认 |
|-----------|--------------|------|
| `printer_status` | 诊断 | 启用 |
| `scanner_status` | 诊断 | 启用 |
| `maintenance_box` | 诊断（%） | 启用 |
| `epson_connect_status` | 诊断 | 启用 |
| `first_print_date` | 诊断（日期） | 启用 |
| `firmware` | 诊断 | 禁用 |
| `serial` | 诊断 | 启用 |
| `mac_address` | 诊断 | 启用 |

### IPP 传感器（7）

| 实体键 | 默认 | 说明 |
|-----------|---------|-------------|
| `ipp_state` | 启用 | 打印机状态（idle/printing/stopped） |
| `ipp_accepting_jobs` | 启用 | 是否接受新任务 |
| `ipp_uptime` | 启用 | 打印机开机时长（秒） |
| `ipp_queued_jobs` | 启用 | 队列任务数 |
| `ipp_state_reason` | 禁用 | IPP 状态详细原因 |
| `ipp_model` | 禁用 | IPP make-and-model 字符串 |
| `ipp_pages_per_minute` | 禁用 | IPP 报告的打印速度 |

### 纸张来源传感器（2，默认禁用）

| 实体键 | 说明 |
|-----------|-------------|
| `paper_source_size` | 当前纸张尺寸 |
| `paper_source_type` | 当前纸张类型 |

> ⚠️ 并非所有打印机都返回全部 IPP 属性。缺失属性显示为 `unavailable`，属正常现象。

---

## 🛠️ 服务

### 统一打印服务 `epson_printer.print`（推荐）

一个服务搞定所有打印，内部按内容**智能路由**。无需在「目标」中选择设备或实体，系统会自动定位打印机：

| 内容 | 路由通道 |
|------|----------|
| 纯文本 | RAW 9100（端口 9100） |
| PDF / 图片（jpg/png/bmp/tiff） | IPP 631（支持格式协商与任务状态） |
| Office 文档（doc/docx/xls/xlsx/ppt/pptx/odt…） | LibreOffice 转 PDF → IPP 631（需开启「转换 Office 文档」） |

**字段说明**

| 字段 | 必填 | 说明 |
|------|------|------|
| `content` | ✅ | 文本内容，或**文件路径**（如 `/config/www/report.pdf`） |
| `content_type` | — | `auto`（默认，自动判别）/ `text`（强制文本）/ `file`（强制按文件路径处理） |
| `job_name` | — | 打印任务名称（IPP 可见） |
| `entry_id` | — | 指定打印机（多台时；单台可省略） |
| `host` | — | 按 IP 指定打印机（与 `entry_id` 二选一） |

**示例（开发者工具 → 服务）**

```yaml
# 打印文本
service: epson_printer.print
data:
  content: "Hello from Home Assistant!"
```

```yaml
# 打印 PDF 文件
service: epson_printer.print
data:
  content: "/config/www/report.pdf"
  content_type: "file"
  job_name: "Monthly Report"
```

```yaml
# 打印 Excel（需先在"配置"中开启"转换 Office 文档"并安装 LibreOffice）
service: epson_printer.print
data:
  content: "/config/www/budget.xlsx"
```

```yaml
# 多台打印机时指定其中一台（按 IP）
service: epson_printer.print
data:
  content: "打印测试"
  host: "192.168.3.200"
```

### 其他服务（保留，供高级用法）

| 服务 | 说明 | 字段 |
|------|------|------|
| `print_text` | 经 RAW 9100 打印文本 | `text`（必填） |
| `print_file` | 经 RAW 9100 打印文件 | `filepath`（必填） |
| `ipp_print_file` | 经 IPP 631 打印文件（支持 JPEG/PNG/PDF/TIFF/BMP） | `file_path`、`job_name` |
| `clean_printhead` | 清洗打印头 | `deep`（布尔，默认 false） |
| `nozzle_check` | 打印喷嘴检查图案 | — |
| `initialize` | 发送 `ESC @` 复位打印机 | — |

> RAW 端口（9100）需从 Home Assistant 服务器可达。部分打印机需在设置中开启 RAW 打印。

---

## 🔄 数据更新

协调器在每个轮询间隔并行抓取三个数据源：

| 数据源 | 协议 | 内容 |
|--------|----------|------|
| 维护页 | HTTP/HTTPS（aiohttp） | 打印页数、首次打印日期 |
| 产品状态页 | HTTP/HTTPS（aiohttp） | 墨水量、状态、固件、序列号 |
| IPP 打印机属性 | IPP over TCP（executor） | 状态、运行时间、任务数、速度 |

轮询间隔可在**选项**中配置（默认 5 分钟，最小 30 秒）。
首次抓取会自动将打印机界面语言设为英文以保证解析稳定。

---

## 🔍 故障排查

**配置流程提示「无法连接打印机」**

- 确认打印机 IP 正确且可连通（`ping`）。
- 确认打印机 Web 界面可访问：`http://打印机IP/`。
- 若打印机使用自签名证书，尝试选择 `https`。

**实体显示 `unavailable`**

- **IPP 实体**：打印机可能不支持全部 IPP 属性，属正常 —— 仅 `ipp_state` 和 `ipp_accepting_jobs` 有保障。
- **`first_print_date`**：部分打印机不上报，多数机型默认禁用。

**墨水量不更新**

- 部分爱普生打印机仅在打印任务后才刷新墨水量，可先打印一页试试。

**打印服务无响应（RAW 端口）**

- 确认打印机网络设置中已开启 RAW 端口 9100。
- 检查 HA 服务器与打印机之间的防火墙规则。

**Office 文档打印失败**

- 确认已在集成「配置」中开启「转换 Office 文档」。
- 确认 HA 主机已安装 LibreOffice，且 `soffice` 在 PATH 中（或用 `soffice_path` 指定绝对路径）。

---

## 📜 更新日志

### v0.3.1（2026-07-11）
- 补全 **中文文档（README）** 与 **HA 界面中文翻译**（配置流程、传感器名称、服务名均中文化）
- 修复传感器 `serial` / `mac_address` / `paper_source_size` / `paper_source_type` 因硬编码英文名导致中文翻译不生效的问题
- 补全 `en.json` 缺失的 `serial` / `mac_address` / `maintenance_box` / `scanner_status` / `paper_source_*` 翻译键

### v0.3.0
- 新增统一打印服务 `print`，智能路由：文本→RAW 9100、PDF/图片→IPP 631、Office→LibreOffice 转 PDF→IPP
- 新增 Office（Word/Excel 等）转 PDF 打印选项（需 LibreOffice）
- 修复传感器因 `KEY_PAPER_SOURCE` 漏导入导致的 `NameError`（此前 0 实体）
- 采用官方爱普生品牌图标（`brand/icon.png`、`brand/logo.png`）

---

## 🔗 相关链接

- [爱普生打印支持](https://epson.com/support)
- [Home Assistant IPP 集成](https://www.home-assistant.io/integrations/ipp/)
- [ha-epson-ecotank-stats](https://github.com/wwerther/ha-epson-ecotank-stats)（上游灵感）

---

## 📜 许可证

MIT

---

## 💝 赞助

如果这个集成帮到了你，欢迎请我喝杯咖啡 ☕

| 微信支付 | 支付宝 |
|:--------:|:------:|
| ![微信](sponsor/wechat.jpg) | ![支付宝](sponsor/alipay.jpg) |

---

<a name="english"></a>
# English

## 📋 Features

- **🖨️ Ink levels** — Black / Cyan / Magenta / Yellow percentages
- **📄 Page counters** — Total, B&W, color, duplex, simplex, plus breakdowns by function (print/copy/scan/fax), by paper size, and by print language
- **✅ Printer status** — Epson Connect status, firmware version, serial, MAC, model, maintenance-box life, scanner status
- **📅 First print date** — (if supported by printer; unavailable otherwise)
- **🔌 IPP monitoring** — Real-time printer state, uptime, queued jobs, accepting jobs, pages per minute (if supported by printer)
- **🛠️ Printer control** — Unified `print` service (smart routing) + maintenance services (text/file print, Office→PDF, clean printhead, nozzle check)
- **⏱️ Configurable polling interval** — Default 5 min, min 30 s
- **🔍 Auto discovery** — mDNS / zeroconf LAN discovery, or manual IP entry
- **🎨 Official brand icons** — Epson official `brand/icon.png` and `brand/logo.png`

## ✅ Supported Printers

Any Epson printer with a **built-in web server** (most EcoTank, WorkForce, Expression models). Consumer printers may not expose every IPP attribute; missing ones fall back to `unavailable` gracefully.

## ⚙️ Installation

### HACS (recommended)
1. Install [HACS](https://hacs.xyz/). 2. **HACS → Integrations → Three-dot menu → Custom repositories**. 3. Add `https://github.com/C3H3-AI/ha-epson-printer`, category **Integration**. 4. Install & restart.

### Manual
Extract `custom_components/epson_printer/` into `config/custom_components/`, then restart.

## 🔧 Configuration

Add **Epson Printer** from **Settings → Devices & Services**. mDNS auto-discovery is supported; you can also enter the IP manually. Options (post-setup): polling interval (default 300 s, min 30), "Convert Office documents" (off; requires LibreOffice), and LibreOffice path.

## 📊 Sensors

- **Ink (4, enabled)**: `ink_k`, `ink_c`, `ink_m`, `ink_y`
- **Page counters (5)**: `pages_total` (enabled), `pages_bw` / `pages_color` / `pages_duplex` / `pages_simplex` (disabled)
- **Page breakdown (15+, disabled)**: by function (10: `function_*`), by size (`pages_size_*`), by language (`pages_language_*`)
- **Status & diagnostic**: `printer_status`, `scanner_status`, `maintenance_box`, `epson_connect_status`, `first_print_date`, `serial`, `mac_address` (enabled); `firmware` (disabled)
- **IPP (7)**: `ipp_state`, `ipp_accepting_jobs`, `ipp_uptime`, `ipp_queued_jobs` (enabled); `ipp_state_reason`, `ipp_model`, `ipp_pages_per_minute` (disabled)
- **Paper source (2, disabled)**: `paper_source_size`, `paper_source_type`

## 🛠️ Services

### Unified `epson_printer.print` (recommended)

One service for all printing with smart routing. No target device/entity selection needed — the system auto-detects your printer:

| Content | Channel |
|---------|---------|
| Plain text | RAW 9100 (port 9100) |
| PDF / image (jpg/png/bmp/tiff) | IPP 631 |
| Office (doc/docx/xls/xlsx/ppt/pptx/odt…) | LibreOffice → PDF → IPP 631 (requires "Convert Office documents") |

**Fields**: `content` (text or file path, required), `content_type` (`auto` default / `text` / `file`), `job_name` (optional), `entry_id` / `host` (target a specific printer; omit if single).

```yaml
service: epson_printer.print
data:
  content: "Hello from Home Assistant!"
```

### Other services
`print_text` (RAW text), `print_file` (RAW file), `ipp_print_file` (IPP file), `clean_printhead` (`deep` bool), `nozzle_check`, `initialize` (ESC @ reset).

## 🔍 Troubleshooting

- **"Cannot connect"**: verify IP reachability, web UI access, try `https` for self-signed certs.
- **Entities `unavailable`**: IPP attributes may be unsupported (normal); `first_print_date` often disabled.
- **Ink not updating**: some printers refresh only after a print job.
- **RAW unresponsive**: enable port 9100 and check firewall.
- **Office print fails**: enable "Convert Office documents" and ensure LibreOffice is installed.

## 📜 Changelog

### v0.3.1 (2026-07-11)
- Added Chinese README and full HA UI Chinese translations (config flow, sensor names, service names)
- Fixed `serial` / `mac_address` / `paper_source_size` / `paper_source_type` not translating due to hardcoded English names
- Added missing `en.json` translation keys

### v0.3.0
- Unified `print` service with smart routing (text→RAW, PDF/image→IPP, Office→LibreOffice→PDF→IPP)
- Office (Word/Excel) to PDF printing option
- Fixed `KEY_PAPER_SOURCE` NameError (0 entities)
- Official Epson brand icons

## 📜 License

MIT

[releases-shield]: https://img.shields.io/github/v/release/C3H3-AI/ha-epson-printer?style=flat-square
[releases]: https://github.com/C3H3-AI/ha-epson-printer/releases
[commits-shield]: https://img.shields.io/github/last-commit/C3H3-AI/ha-epson-printer?style=flat-square
[commits]: https://github.com/C3H3-AI/ha-epson-printer/commits/main
[license-shield]: https://img.shields.io/github/license/C3H3-AI/ha-epson-printer?style=flat-square
[license]: https://github.com/C3H3-AI/ha-epson-printer/blob/main/LICENSE
[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=flat-square
[hacs]: https://hacs.xyz/
[ha-badge]: https://img.shields.io/badge/Home%20Assistant-2024.1+-blue.svg?style=flat-square
[ha]: https://www.home-assistant.io/
