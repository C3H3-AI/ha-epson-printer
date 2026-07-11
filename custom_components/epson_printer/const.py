"""Constants for the Epson Printer integration.

Unified: Advanced UI (fieldset), Basic UI (li.tank), IPP monitoring, RAW 9100.
"""

from __future__ import annotations

import ssl

from datetime import timedelta
from typing import Final

DOMAIN: Final = "epson_printer"
MANUFACTURER: Final = "Epson"

# ---------------------------------------------------------------------------
# Config / options keys
# ---------------------------------------------------------------------------
CONF_HOST: Final = "host"
CONF_NAME: Final = "name"
CONF_SCHEME: Final = "scheme"
CONF_PORT: Final = "port"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_IPP_PORT: Final = "ipp_port"
CONF_RAW_PORT: Final = "raw_port"
CONF_IPP_UUID: Final = "ipp_uuid"

DEFAULT_SCHEME: Final = "http"
DEFAULT_PORT: Final = 80
DEFAULT_SCAN_INTERVAL: Final = timedelta(minutes=5)
MIN_SCAN_INTERVAL_SECONDS: Final = 30
HTTP_TIMEOUT_SECONDS: Final = 15

# ---------------------------------------------------------------------------
# Embedded web UI paths — advanced (fieldset) vs basic (li.tank)
# ---------------------------------------------------------------------------
PATH_PRODUCT_STATUS_ADV: Final = "/PRESENTATION/ADVANCED/INFO_PRTINFO/TOP"
PATH_MAINTENANCE_ADV: Final = "/PRESENTATION/ADVANCED/INFO_MENTINFO/TOP"
PATH_COMMON_ADV: Final = "/PRESENTATION/ADVANCED/COMMON/TOP"

PATH_PRODUCT_STATUS_BASIC: Final = "/PRESENTATION/HTML/TOP/PRTINFO.HTML"
PATH_MAINTENANCE_BASIC: Final = "/PRESENTATION/HTML/TOP/PRTINFO.HTML"
PATH_COMMON_BASIC: Final = "/PRESENTATION/HTML/TOP/COMMON.HTML"

PRODUCT_STATUS_PATHS: Final = (PATH_PRODUCT_STATUS_ADV, PATH_PRODUCT_STATUS_BASIC)
MAINTENANCE_PATHS: Final = (PATH_MAINTENANCE_ADV, PATH_MAINTENANCE_BASIC)
COMMON_PATHS: Final = (PATH_COMMON_ADV, PATH_COMMON_BASIC)
LANG_ENGLISH: Final = "1"

# ---------------------------------------------------------------------------
# Data dict keys
# ---------------------------------------------------------------------------
DATA_MAINTENANCE: Final = "maintenance"
DATA_PRODUCT: Final = "product"
DATA_IPP: Final = "ipp"

# ---------------------------------------------------------------------------
# Page format detection
# ---------------------------------------------------------------------------
PAGE_FORMAT_ADVANCED: Final = "advanced"
PAGE_FORMAT_BASIC: Final = "basic"

# ---------------------------------------------------------------------------
# Maintenance keys
# ---------------------------------------------------------------------------
KEY_FIRST_PRINT_DATE: Final = "first_print_date"
KEY_PAGES_TOTAL: Final = "pages_total"
KEY_PAGES_BW: Final = "pages_bw"
KEY_PAGES_COLOR: Final = "pages_color"
KEY_PAGES_DUPLEX: Final = "pages_duplex"
KEY_PAGES_SIMPLEX: Final = "pages_simplex"
KEY_PAGES_BY_SIZE: Final = "pages_by_size"
KEY_PAGES_BY_FUNCTION: Final = "pages_by_function"
KEY_PAGES_BY_LANGUAGE: Final = "pages_by_language"

FUNCTION_KEYS: Final = (
    "bw_copy", "color_copy",
    "bw_fax", "color_fax",
    "bw_scan", "color_scan",
    "bw_print", "color_print",
    "bw_other", "color_other",
)

LANGUAGE_KEYS: Final = (
    "escpr", "pcl", "postscript_pdf", "escpage", "other",
)

# ---------------------------------------------------------------------------
# Product status keys
# ---------------------------------------------------------------------------
KEY_PRINTER_STATUS: Final = "printer_status"
KEY_SCANNER_STATUS: Final = "scanner_status"
KEY_INK_LEVELS: Final = "ink_levels"
KEY_MAINTENANCE_BOX: Final = "maintenance_box"
KEY_PAPER_SOURCE: Final = "paper_source"
KEY_FIRMWARE: Final = "firmware"
KEY_SERIAL: Final = "serial"
KEY_MAC_ADDRESS: Final = "mac_address"
KEY_EPSON_CONNECT_STATUS: Final = "epson_connect_status"
KEY_MODEL: Final = "model"

INK_COLORS: Final = ("K", "C", "M", "Y", "PB", "GY", "LC", "LM", "CL")
INK_ALIAS_MAP: Final = {"BK": "K", "PBK": "PB", "PC": "LC", "PM": "LM"}
INK_FULL_HEIGHT_PX: Final = 50

# ---------------------------------------------------------------------------
# IPP interop
# ---------------------------------------------------------------------------
IPP_DOMAIN: Final = "ipp"
ZEROCONF_TXT_UUID: Final = "UUID"
ZEROCONF_TXT_MFG: Final = "usb_MFG"
ZEROCONF_TXT_MODEL: Final = "ty"
ZEROCONF_TXT_ADMIN_URL: Final = "adminurl"
EPSON_MFG_PREFIX: Final = "EPSON"

# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------
SERVICE_PRINT_TEXT: Final = "print_text"
SERVICE_PRINT_FILE: Final = "print_file"
SERVICE_CLEAN_PRINTHEAD: Final = "clean_printhead"
SERVICE_NOZZLE_CHECK: Final = "nozzle_check"
SERVICE_IPP_PRINT_FILE: Final = "ipp_print_file"
SERVICE_INITIALIZE: Final = "initialize"

# ---------------------------------------------------------------------------
# Shared SSL context (lazy singleton, reused across modules)
# ---------------------------------------------------------------------------

_INSTANCE_INSECURE_SSL_CTX: ssl.SSLContext | None = None


def get_insecure_ssl_ctx() -> ssl.SSLContext:
    """Return a shared, lazy-initialized insecure SSL context."""
    global _INSTANCE_INSECURE_SSL_CTX  # noqa: PLW0603
    if _INSTANCE_INSECURE_SSL_CTX is None:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        _INSTANCE_INSECURE_SSL_CTX = ctx
    return _INSTANCE_INSECURE_SSL_CTX


# ---------------------------------------------------------------------------
# ESC/P commands and IPP paths
# ---------------------------------------------------------------------------
IPP_PATHS: Final = (
    "/ipp/print",
    "/ipp/printer",
    "/ipp",
    "/ipp/print/default",
    "/Epson_IPP",
)

ESC_COMMANDS: Final = {
    "initialize": b"\x1b\x40",
    "printhead_clean": b"\x1b\x28\x43\x02\x00\x00\x01",
    "printhead_clean_deep": b"\x1b\x28\x43\x02\x00\x00\x02",
    "nozzle_check": b"\x1b\x28\x52\x08\x00\x00\x52\x45\x4d\x4f\x54\x45\x50",
}
