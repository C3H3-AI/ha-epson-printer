# Epson Printer

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]][license]
[![hacs][hacs-badge]][hacs]
[![Home Assistant][ha-badge]][ha]

Home Assistant integration for Epson printers — ink levels, page counters, printer status, IPP monitoring, and RAW port 9100 control.

> **Inspired by** [ha-epson-ecotank-stats](https://github.com/wwerther/ha-epson-ecotank-stats).  
> Extended with IPP monitoring, printer control services, and broader printer support.

---

## 📋 Features

- **🖨️ Ink levels** — Black / Cyan / Magenta / Yellow percentages
- **📄 Page counters** — Total, B&W, color, duplex, simplex, plus breakdowns by function (print/copy/scan/fax), by paper size, and by print language
- **✅ Printer status** — Epson Connect status, firmware version, serial, MAC, model
- **📅 First print date** — (if supported by printer; unavailable otherwise)
- **🔌 IPP monitoring** — Real-time printer state, uptime, queued jobs, accepting jobs, pages per minute (if supported by printer; unavailable otherwise)
- **🛠️ Printer control** — RAW port 9100 service actions:
  - Print text
  - Print files (PDF, images, etc.)
  - Clean printhead (light / deep)
  - Nozzle check pattern
- **⏱️ Configurable polling interval** — Default 5 min, min 30 s

---

## ✅ Supported Printers

Works with any Epson printer that has a **built-in web server** (most EcoTank, WorkForce, and Expression models).

| Printer | ink | pages | status | IPP | RAW |
|---------|:---:|:-----:|:------:|:---:|:---:|
| EcoTank L3250 | ✅ | ✅ | ✅ | ⚠️ partial | ✅ |
| EcoTank L4160 / L4260 | ✅ | ✅ | ✅ | ✅ | ✅ |
| WorkForce series | ✅ | ✅ | ✅ | ✅ | ✅ |
| Expression series | ✅ | ✅ | ✅ | ⚠️ partial | ✅ |
| Other models | ✅ | ✅ | ✅ | varies | ✅ |

> **Note**: Consumer printers may not support all IPP attributes (e.g. `printer-state`, `queued-job-count`).  
> IPP entities fall back to `unavailable` gracefully when data is missing — the integration works fully without IPP.

---

## ⚙️ Installation

### HACS (recommended)

1. Ensure [HACS](https://hacs.xyz/) is installed in your Home Assistant instance.
2. Go to **HACS → Integrations → Three-dot menu → Custom repositories**.
3. Add: `https://github.com/C3H3-AI/ha-epson-printer`
4. Category: **Integration**
5. Click **Install**.
6. Restart Home Assistant.

### Manual

1. Download the latest release ZIP.
2. Extract `custom_components/epson_printer/` into your `config/custom_components/` directory.
3. Restart Home Assistant.

---

## 🔧 Configuration

**1. Find your printer's IP address** — Check your router DHCP leases or print a network status sheet from the printer.

**2. Add the integration**

Go to **Settings → Devices & Services → Add Integration** → search for **Epson Printer**.

Or click: [![Add Integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=epson_printer)

**3. Fill in the config flow**

| Field | Default | Description |
|-------|---------|-------------|
| **Host** | — | Printer IP address (e.g. `192.168.1.100`) |
| **Name** | `Epson Printer` | Friendly name |
| **Scheme** | `http` | `http` or `https` (auto-fallback) |
| **Port** | `80` | Web UI port |

The integration auto-detects the correct URL scheme (HTTP/HTTPS fallback).

**4. Options (post-setup)**

Go to **Settings → Devices & Services → Epson Printer → Configure** to change the polling interval (default: 300 s, min: 30 s).

---

## 📊 Sensors

### Ink sensors (4)

| Entity key | Unit | Device class |
|-----------|------|--------------|
| `ink_k` | % | — |
| `ink_c` | % | — |
| `ink_m` | % | — |
| `ink_y` | % | — |

### Page counter sensors (5)

| Entity key | Unit | State class |
|-----------|------|-------------|
| `pages_total` | pages | total_increasing |
| `pages_bw` | pages | total_increasing |
| `pages_color` | pages | total_increasing |
| `pages_duplex` | pages | total_increasing |
| `pages_simplex` | pages | total_increasing |

### Page breakdown sensors (15, disabled by default)

- **By function** (10): `function_bw_print`, `function_color_print`, `function_bw_copy`, `function_color_copy`, `function_bw_scan`, `function_color_scan`, `function_bw_fax`, `function_color_fax`, `function_bw_other`, `function_color_other`
- **By size** (dynamic): `pages_by_size_*`
- **By print language** (dynamic): `pages_by_language_*`

### Product info sensors (4, diagnostic, disabled by default)

| Entity key | Device class |
|-----------|--------------|
| `firmware` | firmware |
| `serial` | — |
| `mac_address` | — |
| `first_print_date` | date |

### Status sensors (2)

| Entity key | Description |
|-----------|-------------|
| `printer_status` | Current printer state (text) |
| `epson_connect_status` | Epson Connect connectivity (text) |

### IPP sensors (7)

| Entity key | Default | Description |
|-----------|---------|-------------|
| `ipp_state` | enabled | Printer state (idle/printing/stopped) |
| `ipp_accepting_jobs` | enabled | Whether printer accepts new jobs |
| `ipp_uptime` | enabled | Seconds since printer startup |
| `ipp_queued_jobs` | enabled | Number of queued jobs |
| `ipp_state_reason` | disabled | Detailed IPP state reason |
| `ipp_model` | disabled | IPP make-and-model string |
| `ipp_pages_per_minute` | disabled | IPP-reported speed |

> ⚠️ Not all printers return every IPP attribute. Missing attributes show as `unavailable` — this is expected behavior.

---

## 🛠️ Services

| Service | Description | Fields |
|---------|-------------|--------|
| `print_text` | Send text to print via RAW 9100 | `text` (string, required) |
| `print_file` | Print a file (PDF, image) via RAW 9100 | `filepath` (string, required) |
| `clean_printhead` | Run printhead cleaning cycle | `deep` (boolean, optional, default: false) |
| `nozzle_check` | Print a nozzle check pattern | — |

**Example (Developer Tools → Services):**

```yaml
service: epson_printer.print_text
data:
  text: "Hello from Home Assistant!"
target:
  device_id: YOUR_DEVICE_ID
```

```yaml
service: epson_printer.clean_printhead
data:
  deep: true
target:
  device_id: YOUR_DEVICE_ID
```

> The RAW port (9100) must be reachable from your Home Assistant server.  
> Some printers may require enabling RAW printing in their settings.

---

## 🔄 Data Updates

The coordinator fetches three data sources in parallel every polling interval:

| Source | Protocol | Data |
|--------|----------|------|
| Maintenance page | HTTP/HTTPS (aiohttp) | Page counters, first print date |
| Product status page | HTTP/HTTPS (aiohttp) | Ink levels, status, firmware, serial |
| IPP printer attributes | IPP over TCP socket (executor) | State, uptime, jobs, speed |

Polling interval is configurable via **Options** (default: 5 minutes, minimum: 30 seconds).

The printer UI language is auto-set to English on first fetch for consistent scraping.

---

## 🔍 Troubleshooting

**"Cannot connect to printer" in config flow**

- Verify the printer IP is correct and reachable (`ping`).
- Check the printer's web UI is accessible at `http://PRINTER-IP/`.
- Try a different scheme (select `https` if the printer uses self-signed certs).

**Entities show `unavailable`**

- **IPP entities**: Your printer may not support all IPP attributes. This is normal — only `ipp_state` and `ipp_accepting_jobs` are guaranteed.
- **`first_print_date`**: Not all printers report this. Entity disabled by default on many models.

**Ink levels not updating**

- Some Epson printers only refresh ink levels after a print job. Try printing a page first.

**Services not responding (RAW port)**

- Verify the printer's RAW port 9100 is enabled in its network settings.
- Check firewall rules between HA server and printer.

---

## 🔗 Related

- [Epson Printer Support](https://epson.com/support)
- [Home Assistant IPP integration](https://www.home-assistant.io/integrations/ipp/)
- [ha-epson-ecotank-stats](https://github.com/wwerther/ha-epson-ecotank-stats) (upstream inspiration)

---

## 📜 License

MIT

---

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
