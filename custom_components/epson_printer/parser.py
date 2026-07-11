"""Unified HTML parser for Epson printer status pages.

Auto-detects Advanced UI (fieldset-based, /ADVANCED/INFO_PRTINFO/TOP)
vs Basic UI (li.tank / clrname-based, /HTML/TOP/PRTINFO.HTML), then
dispatches to the appropriate sub-parser.

Three ink-level formats handled:
  - img-based  (ET-2750):  <img src="Ink_BK.PNG" height="48">
  - CSS class  (L3250):    <div class='tank_3rd'>
  - style attr (WorkForce): <div style="height: 24px">
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup, Tag

from .const import (
    FUNCTION_KEYS,
    INK_ALIAS_MAP,
    INK_COLORS,
    INK_FULL_HEIGHT_PX,
    KEY_EPSON_CONNECT_STATUS,
    KEY_FIRMWARE,
    KEY_FIRST_PRINT_DATE,
    KEY_INK_LEVELS,
    KEY_MAC_ADDRESS,
    KEY_MAINTENANCE_BOX,
    KEY_MODEL,
    KEY_PAGES_BW,
    KEY_PAGES_BY_FUNCTION,
    KEY_PAGES_BY_LANGUAGE,
    KEY_PAGES_BY_SIZE,
    KEY_PAGES_COLOR,
    KEY_PAGES_DUPLEX,
    KEY_PAGES_SIMPLEX,
    KEY_PAGES_TOTAL,
    KEY_PAPER_SOURCE,
    KEY_PRINTER_STATUS,
    KEY_SCANNER_STATUS,
    KEY_SERIAL,
    LANGUAGE_KEYS,
    PAGE_FORMAT_ADVANCED,
    PAGE_FORMAT_BASIC,
)

_LOGGER = logging.getLogger(__name__)

SIZE_KEYS: tuple[str, ...] = (
    "a3_ledger", "a4_letter", "a5", "a6",
    "b4_legal", "b5", "envelope", "other",
)

_INT_RE = re.compile(r"-?\d+")
_DATE_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_INK_FILENAME_RE = re.compile(r"Ink_([A-Z]+)\.PNG", re.IGNORECASE)
_TANK_CLASS_RE = re.compile(r"tank_(\d+)(?:st|nd|rd|th)")
_FIRMWARE_RE = re.compile(r"^\d{2}\.\d{2}\.[A-Z0-9]+$")
_SERIAL_RE = re.compile(r"^[A-Z0-9]{8,}$")
_MAC_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$", re.IGNORECASE)

TANK_MAX_LEVEL = 4


# 鈹€鈹€ Page format auto-detection 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€


def detect_page_format(html: str) -> str:
    """Return PAGE_FORMAT_ADVANCED or PAGE_FORMAT_BASIC."""
    soup = BeautifulSoup(html, "html.parser")
    if soup.find("fieldset", class_="group"):
        return PAGE_FORMAT_ADVANCED
    return PAGE_FORMAT_BASIC


# 鈹€鈹€ Shared helpers 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€


def _to_int(text: str | None) -> int | None:
    if text is None:
        return None
    match = _INT_RE.search(text)
    return int(match.group(0)) if match else None


def _value_text(dd: Tag | None) -> str | None:
    if dd is None:
        return None
    inner = dd.find("div", class_="preserve-white-space")
    text = (inner or dd).get_text(strip=True)
    return text or None


def _parse_iso_date(text: str | None) -> str | None:
    if not text:
        return None
    match = _DATE_RE.search(text)
    if not match:
        return None
    year, month, day = (int(g) for g in match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


# 鈹€鈹€ Ink level extraction (shared across formats) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€


def _li_level_value(li: Tag) -> int | None:
    """0-100% from a <li class='tank'> via img height / CSS class / style."""
    img = li.find("img")
    if isinstance(img, Tag):
        height = _to_int(img.get("height"))
        if height is not None:
            return max(0, min(100, round(height * 100 / INK_FULL_HEIGHT_PX)))
    tank_div = li.find("div", class_=_TANK_CLASS_RE)
    if isinstance(tank_div, Tag):
        return _css_tank_level(tank_div)
    for d_inner in li.find_all("div"):
        if not isinstance(d_inner, Tag):
            continue
        style = d_inner.get("style")
        if not style:
            continue
        s = " ".join(style) if isinstance(style, list) else str(style)
        m = re.search(r"height\s*:\s*(\d+)", s, re.IGNORECASE)
        if m:
            px = int(m.group(1))
            return max(0, min(100, px * 2))
    return None


def _css_tank_level(tank_div: Tag) -> int | None:
    classes = tank_div.get("class") or []
    for cls in classes:
        m = _TANK_CLASS_RE.match(cls)
        if m:
            return max(0, min(100, round(int(m.group(1)) * 100 / TANK_MAX_LEVEL)))
    return None


def _parse_ink_levels(soup: BeautifulSoup) -> dict[str, Any]:
    """Return {'levels': {col: %, ...}, 'maintenance_box': int | None}.

    Searches <ul class='inksection'> first, then falls back to direct
    <li class='tank'> search for basic UIs that lack the wrapper UL.
    """
    section = soup.find("ul", class_="inksection")
    tanks: list[Tag] = []
    if isinstance(section, Tag):
        tanks = section.find_all("li", class_="tank")
    if not tanks:
        tanks = soup.find_all("li", class_="tank")

    levels: dict[str, int] = {}
    maintenance_box: int | None = None

    for li in tanks:
        is_maintenance = False
        for div_inner in li.find_all("div"):
            if isinstance(div_inner, Tag):
                inner_classes = div_inner.get("class") or []
                if any("mbicn" in (c or "").lower() for c in inner_classes):
                    is_maintenance = True
                    break

        if is_maintenance:
            pct = _li_level_value(li)
            if pct is not None:
                maintenance_box = pct
            continue

        colour = _detect_colour(li)
        if colour and colour in INK_COLORS:
            pct = _li_level_value(li)
            if pct is not None:
                levels[colour] = pct

    return {"levels": levels, "maintenance_box": maintenance_box}


def _detect_colour(li: Tag) -> str | None:
    """Detect ink colour from img src, clrname div, or fallback heuristics."""
    # img-based
    img = li.find("img")
    if isinstance(img, Tag):
        src = img.get("src") or ""
        match = _INK_FILENAME_RE.search(src)
        if match:
            raw = match.group(1).upper()
            return INK_ALIAS_MAP.get(raw, raw)

    # CSS class clrname div
    clrname_div = li.find("div", class_="clrname")
    if clrname_div:
        raw = clrname_div.get_text(strip=True).upper()
        return INK_ALIAS_MAP.get(raw, raw)

    return None


# 鈹€鈹€ Identity info (shared) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€


def _pick_firmware(values: list[str]) -> str | None:
    for v in values:
        if _FIRMWARE_RE.match(v):
            return v
    return None


def _pick_serial(values: list[str]) -> str | None:
    for v in values:
        if ":" in v or "." in v:
            continue
        if _SERIAL_RE.match(v):
            return v
    return None


def _pick_mac(values: list[str]) -> str | None:
    for v in values:
        if _MAC_RE.match(v):
            return v.upper()
    return None


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?# ADVANCED UI PARSER (fieldset-based /ADVANCED/INFO_PRTINFO/TOP etc.)
# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?

def _fieldsets_with_legend(soup: BeautifulSoup | Tag) -> list[Tag]:
    out: list[Tag] = []
    for fs in soup.find_all("fieldset"):
        classes = fs.get("class") or []
        if "no-legend" in classes:
            continue
        if fs.find("legend"):
            out.append(fs)
    return out


def _dl_values(dl: Tag) -> list[str | None]:
    return [_value_text(dd) for dd in dl.find_all("dd", recursive=False)]


def _collect_flat_dl_values(soup: BeautifulSoup) -> list[str]:
    values: list[str] = []
    for dd in soup.find_all("dd", class_="value"):
        text = _value_text(dd)
        if text:
            values.append(text)
    return values


def _pick_epson_connect(soup: BeautifulSoup) -> str | None:
    for dt in soup.find_all("dt", class_="key"):
        label = dt.get_text(" ", strip=True)
        if "epson connect" not in label.lower():
            continue
        if "mail" in label.lower() or "e-mail" in label.lower():
            continue
        dd = dt.find_next_sibling("dd")
        text = _value_text(dd)
        if text:
            return text
    return None


def _parse_size_table(fieldset: Tag) -> dict[str, dict[str, int | None]]:
    columns = ("simplex_bw", "simplex_color", "duplex_bw", "duplex_color")
    table = fieldset.find("table", class_="values")
    if table is None:
        return {}
    body = table.find("tbody")
    if body is None:
        return {}
    out: dict[str, dict[str, int | None]] = {}
    for index, row in enumerate(body.find_all("tr")):
        cells = row.find_all("td", class_="value number")
        if len(cells) < 4:
            continue
        key = SIZE_KEYS[index] if index < len(SIZE_KEYS) else f"row_{index}"
        out[key] = {
            col: _to_int(_value_text(cell))
            for col, cell in zip(columns, cells[:4])
        }
    return out


def _parse_keyed_dl(fieldset: Tag, keys: tuple[str, ...]) -> dict[str, int | None]:
    dl = fieldset.find("dl", class_="values")
    if dl is None:
        return {}
    values = [_to_int(v) for v in _dl_values(dl)]
    return {
        keys[i]: values[i] if i < len(values) else None
        for i in range(len(keys))
    }


def _parse_advanced_maintenance(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, Any] = {
        KEY_FIRST_PRINT_DATE: None,
        KEY_PAGES_TOTAL: None,
        KEY_PAGES_BW: None,
        KEY_PAGES_COLOR: None,
        KEY_PAGES_DUPLEX: None,
        KEY_PAGES_SIMPLEX: None,
        KEY_PAGES_BY_SIZE: {},
        KEY_PAGES_BY_FUNCTION: {},
        KEY_PAGES_BY_LANGUAGE: {},
    }

    section = soup.find("div", class_="section")
    if section is None:
        return result

    for dl in section.find_all("dl", class_="values", recursive=False):
        values = _dl_values(dl)
        if values:
            result[KEY_FIRST_PRINT_DATE] = _parse_iso_date(values[0])
            break

    fieldsets = _fieldsets_with_legend(section)

    totals_fs: Tag | None = None
    size_table_fs: Tag | None = None
    function_fs: Tag | None = None
    language_fs: Tag | None = None

    for fs in fieldsets:
        has_table = fs.find("table", class_="values") is not None
        has_dl = fs.find("dl", class_="values") is not None

        if not has_table and not has_dl:
            dds = [_to_int(_value_text(dd)) for dd in fs.find_all("dd")]
            numeric_count = sum(1 for v in dds if v is not None)
            if numeric_count >= 5 and totals_fs is None:
                totals_fs = fs
                continue
            if totals_fs is None and numeric_count == 1:
                totals_fs = fs
                continue

        if has_table and size_table_fs is None:
            size_table_fs = fs
            continue

        if has_dl:
            if function_fs is None:
                function_fs = fs
            elif language_fs is None:
                language_fs = fs

    if totals_fs is not None:
        totals = [_to_int(t) for t in (_value_text(dd) for dd in totals_fs.find_all("dd"))]
        totals += [None] * (5 - len(totals))
        (result[KEY_PAGES_TOTAL],
         result[KEY_PAGES_BW],
         result[KEY_PAGES_COLOR],
         result[KEY_PAGES_DUPLEX],
         result[KEY_PAGES_SIMPLEX]) = totals[:5]

    if size_table_fs is not None:
        result[KEY_PAGES_BY_SIZE] = _parse_size_table(size_table_fs)

    if function_fs is not None:
        result[KEY_PAGES_BY_FUNCTION] = _parse_keyed_dl(function_fs, FUNCTION_KEYS)

    if language_fs is not None:
        result[KEY_PAGES_BY_LANGUAGE] = _parse_keyed_dl(language_fs, LANGUAGE_KEYS)

    return result


def _parse_advanced_product_status(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, Any] = {
        KEY_MODEL: None,
        KEY_PRINTER_STATUS: None,
        KEY_SCANNER_STATUS: None,
        KEY_INK_LEVELS: {},
        KEY_MAINTENANCE_BOX: None,
        KEY_PAPER_SOURCE: {},
        KEY_FIRMWARE: None,
        KEY_SERIAL: None,
        KEY_MAC_ADDRESS: None,
        KEY_EPSON_CONNECT_STATUS: None,
    }

    title = soup.find("title")
    if title is not None:
        text = title.get_text(strip=True)
        if text:
            result[KEY_MODEL] = text

    for fs in _fieldsets_with_legend(soup):
        first_value = fs.find("li", class_="value")
        if first_value is None:
            continue
        text = _value_text(first_value)
        if text:
            result[KEY_PRINTER_STATUS] = text
            break

    fs_prt = soup.find("fieldset", id="PRT_STATUS")
    if isinstance(fs_prt, Tag) and result[KEY_PRINTER_STATUS] is None:
        txt = fs_prt.get_text(" ", strip=True)
        if txt:
            result[KEY_PRINTER_STATUS] = txt

    fs_scn = soup.find("fieldset", id="SCN_STATUS")
    if isinstance(fs_scn, Tag):
        txt = fs_scn.get_text(" ", strip=True)
        if txt:
            result[KEY_SCANNER_STATUS] = txt

    ink_data = _parse_ink_levels(soup)
    result[KEY_INK_LEVELS] = ink_data.get("levels", {})
    result[KEY_MAINTENANCE_BOX] = ink_data.get("maintenance_box")
    result[KEY_PAPER_SOURCE] = _parse_advanced_paper_source(soup)

    identity = _collect_flat_dl_values(soup)
    result[KEY_FIRMWARE] = _pick_firmware(identity)
    result[KEY_SERIAL] = _pick_serial(identity)
    result[KEY_MAC_ADDRESS] = _pick_mac(identity)
    result[KEY_EPSON_CONNECT_STATUS] = _pick_epson_connect(soup)

    return result


def _parse_advanced_paper_source(soup: BeautifulSoup) -> dict[str, str | None]:
    for fs in _fieldsets_with_legend(soup):
        dl = fs.find("dl", class_="values")
        if dl is None:
            continue
        dds = dl.find_all("dd", recursive=False)
        if len(dds) != 2:
            continue
        size = _value_text(dds[0])
        ptype = _value_text(dds[1])
        if size or ptype:
            return {"size": size, "type": ptype}
    return {}


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?# BASIC UI PARSER  (li.tank-based /HTML/TOP/PRTINFO.HTML)
# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?

def _parse_basic_product_status(html: str) -> dict[str, Any]:
    """Parse the simpler PRTINFO.HTML page (used by epsonprinter / workforce).

    This page has no fieldset.group wrappers. Ink levels are in
    <li class='tank'>. Identity info is in bare <dl>/<dd> or inline text.
    """
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, Any] = {
        KEY_MODEL: None,
        KEY_PRINTER_STATUS: None,
        KEY_SCANNER_STATUS: None,
        KEY_INK_LEVELS: {},
        KEY_MAINTENANCE_BOX: None,
        KEY_PAPER_SOURCE: {},
        KEY_FIRMWARE: None,
        KEY_SERIAL: None,
        KEY_MAC_ADDRESS: None,
        KEY_EPSON_CONNECT_STATUS: None,
    }

    # Model from title
    title = soup.find("title")
    if title is not None:
        text = title.get_text(strip=True)
        if text:
            result[KEY_MODEL] = text

    # Ink levels
    ink_data = _parse_ink_levels(soup)
    result[KEY_INK_LEVELS] = ink_data.get("levels", {})
    result[KEY_MAINTENANCE_BOX] = ink_data.get("maintenance_box")

    # Printer status: look for status table or fieldset
    status_entries: list[str] = []
    for dd in soup.find_all("dd", class_="value"):
        text = _value_text(dd)
        if text and any(kw in text.lower() for kw in ("ready", "idle", "busy", "error", "sleep", "offline", "print")):
            status_entries.append(text)
    if status_entries:
        result[KEY_PRINTER_STATUS] = "; ".join(status_entries[:3])

    # Identity from flat dd values (same as advanced)
    identity: list[str] = []
    for dd in soup.find_all("dd", class_="value"):
        text = _value_text(dd)
        if text:
            identity.append(text)
    result[KEY_FIRMWARE] = _pick_firmware(identity)
    result[KEY_SERIAL] = _pick_serial(identity)
    result[KEY_MAC_ADDRESS] = _pick_mac(identity)

    return result


def _parse_basic_maintenance(html: str) -> dict[str, Any]:
    """Basic maintenance parsing 鈥?PRTINFO.HTML has at most total page count.

    No detailed breakdown (bw/color/simplex/duplex) available in basic UI.
    """
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, Any] = {
        KEY_FIRST_PRINT_DATE: None,
        KEY_PAGES_TOTAL: None,
        KEY_PAGES_BW: None,
        KEY_PAGES_COLOR: None,
        KEY_PAGES_DUPLEX: None,
        KEY_PAGES_SIMPLEX: None,
        KEY_PAGES_BY_SIZE: {},
        KEY_PAGES_BY_FUNCTION: {},
        KEY_PAGES_BY_LANGUAGE: {},
    }

    entries: list[str] = []
    for dd in soup.find_all("dd", class_="value"):
        text = _value_text(dd)
        if text:
            entries.append(text)

    if entries:
        total = _to_int(entries[0])
        if total is not None:
            result[KEY_PAGES_TOTAL] = total

    return result


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?# PUBLIC API
# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?

def parse_product_status(html: str) -> dict[str, Any]:
    """Parse printer status. Auto-detects advanced vs basic UI."""
    fmt = detect_page_format(html)
    _LOGGER.debug("Detected page format: %s", fmt)
    if fmt == PAGE_FORMAT_ADVANCED:
        return _parse_advanced_product_status(html)
    return _parse_basic_product_status(html)


def parse_maintenance(html: str) -> dict[str, Any]:
    """Parse maintenance page (page counters). Auto-detects format."""
    fmt = detect_page_format(html)
    if fmt == PAGE_FORMAT_ADVANCED:
        return _parse_advanced_maintenance(html)
    return _parse_basic_maintenance(html)
