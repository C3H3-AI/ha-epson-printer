"""Pure HTML parsing helpers for Epson printer status pages.

Handles two ink-display formats:
  - img-based (ET-2750 style): <img src="Ink_BK.PNG" height="48">
  - CSS class-based (L3250 style): <div class='tank_3rd'></div>

Both functions are intentionally side-effect free and synchronous so they can
be unit-tested directly against the HTML fixtures stored under ``docs/``.
Parsing relies on **structural position** (``<fieldset>`` order, table column
order, image filename) rather than visible labels, because the labels are
localised by the printer's UI language.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup, Tag

from .const import (
    FUNCTION_KEYS,
    INK_COLORS,
    INK_FULL_HEIGHT_PX,
    KEY_EPSON_CONNECT_STATUS,
    KEY_FIRMWARE,
    KEY_FIRST_PRINT_DATE,
    KEY_INK_LEVELS,
    KEY_MAC_ADDRESS,
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
    KEY_SERIAL,
    LANGUAGE_KEYS,
)

_LOGGER = logging.getLogger(__name__)

# Stable, normalised paper-size labels keyed by DOM row index. The maintenance
# page lists rows in this fixed order across firmware locales.
SIZE_KEYS: tuple[str, ...] = (
    "a3_ledger",
    "a4_letter",
    "a5",
    "a6",
    "b4_legal",
    "b5",
    "envelope",
    "other",
)

_INT_RE = re.compile(r"-?\d+")
_DATE_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_INK_FILENAME_RE = re.compile(r"Ink_([A-Z]+)\.PNG", re.IGNORECASE)
_TANK_CLASS_RE = re.compile(r"tank_(\d+)(?:st|nd|rd|th)")

# L3250: CSS class `tank_Nth` → N / TANK_MAX_LEVEL * 100
# Determined from Epson EcoTank firmware: typically 4 visible levels
TANK_MAX_LEVEL = 4


def _to_int(text: str | None) -> int | None:
    """Return the first integer found in ``text`` or ``None``."""
    if text is None:
        return None
    match = _INT_RE.search(text)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def _value_text(dd: Tag | None) -> str | None:
    """Extract the trimmed text inside a ``<dd class="value">`` cell."""
    if dd is None:
        return None
    inner = dd.find("div", class_="preserve-white-space")
    text = (inner or dd).get_text(strip=True)
    return text or None


def _dl_values(dl: Tag) -> list[str | None]:
    """Return the ordered ``<dd>`` text values inside a ``<dl class="values">``."""
    return [_value_text(dd) for dd in dl.find_all("dd", recursive=False)]


def _fieldsets_with_legend(soup: BeautifulSoup | Tag) -> list[Tag]:
    """Return all ``<fieldset class="group">`` elements that have a ``<legend>``.

    Fieldsets carrying the ``no-legend`` modifier (used for purely decorative
    grouping, e.g. the language selector) are skipped. The relative order of
    the remaining fieldsets is stable across firmware locales.
    """
    out: list[Tag] = []
    for fs in soup.find_all("fieldset"):
        classes = fs.get("class") or []
        if "group" not in classes or "no-legend" in classes:
            continue
        if fs.find("legend"):
            out.append(fs)
    return out


def _parse_iso_date(text: str | None) -> str | None:
    """Validate ``YYYY-M-D``-ish input and return canonical ISO date string."""
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


# ---------------------------------------------------------------------------
# Maintenance page (page counters)
# ---------------------------------------------------------------------------


def parse_maintenance(html: str) -> dict[str, Any]:
    """Parse the ``INFO_MENTINFO/TOP`` page into a structured dict.

    Missing fields are reported as ``None`` (or omitted from sub-dicts) rather
    than raising, so a slightly different firmware does not break the whole
    integration.
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

    section = soup.find("div", class_="section")
    if section is None:
        return result

    # First-print-date is the only top-level <dl class="values"> outside any
    # fieldset.
    for dl in section.find_all("dl", class_="values", recursive=False):
        values = _dl_values(dl)
        if values:
            result[KEY_FIRST_PRINT_DATE] = _parse_iso_date(values[0])
            break

    fieldsets = _fieldsets_with_legend(section)

    # Order of fieldsets on this page (firmware-stable):
    #   0 = Print information totals
    #   1 = Pages-by-size table
    #   2 = Pages-by-function
    #   3 = Pages-by-print-language
    if len(fieldsets) >= 1:
        totals = [
            _to_int(t)
            for t in (_value_text(dd) for dd in fieldsets[0].find_all("dd"))
        ]
        # Defensive padding to length 5.
        totals += [None] * (5 - len(totals))
        (
            result[KEY_PAGES_TOTAL],
            result[KEY_PAGES_BW],
            result[KEY_PAGES_COLOR],
            result[KEY_PAGES_DUPLEX],
            result[KEY_PAGES_SIMPLEX],
        ) = totals[:5]

    if len(fieldsets) >= 2:
        result[KEY_PAGES_BY_SIZE] = _parse_size_table(fieldsets[1])

    if len(fieldsets) >= 3:
        result[KEY_PAGES_BY_FUNCTION] = _parse_keyed_dl(
            fieldsets[2], FUNCTION_KEYS
        )

    if len(fieldsets) >= 4:
        result[KEY_PAGES_BY_LANGUAGE] = _parse_keyed_dl(
            fieldsets[3], LANGUAGE_KEYS
        )

    return result


def _parse_size_table(fieldset: Tag) -> dict[str, dict[str, int | None]]:
    """Parse the per-paper-size table.

    The table has 4 numeric columns per row, in the order:
    simplex_bw, simplex_color, duplex_bw, duplex_color.
    """
    columns = ("simplex_bw", "simplex_color", "duplex_bw", "duplex_color")
    table = fieldset.find("table", class_="values")
    out: dict[str, dict[str, int | None]] = {}
    if table is None:
        return out
    body = table.find("tbody")
    if body is None:
        return out
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
    """Map the ordered ``<dd>`` values of a ``<dl>`` to ``keys``."""
    dl = fieldset.find("dl", class_="values")
    if dl is None:
        return {}
    values = [_to_int(v) for v in _dl_values(dl)]
    out: dict[str, int | None] = {}
    for index, key in enumerate(keys):
        out[key] = values[index] if index < len(values) else None
    return out


# ---------------------------------------------------------------------------
# Product-status page (printer status, ink levels, identity)
# ---------------------------------------------------------------------------


def parse_product_status(html: str) -> dict[str, Any]:
    """Parse the ``INFO_PRTINFO/TOP`` page."""
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, Any] = {
        KEY_MODEL: None,
        KEY_PRINTER_STATUS: None,
        KEY_INK_LEVELS: {},
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

    # Printer status: first <fieldset class="group"> with a legend that
    # contains a single value list.
    for fs in _fieldsets_with_legend(soup):
        first_value = fs.find("li", class_="value")
        if first_value is None:
            continue
        text = _value_text(first_value)
        if text:
            result[KEY_PRINTER_STATUS] = text
            break

    result[KEY_INK_LEVELS] = _parse_ink_levels(soup)
    result[KEY_PAPER_SOURCE] = _parse_paper_source(soup)

    # Identity / connect-status: the page exposes several flat <dl class="values">
    # blocks. Iterate them and pick known fields by their adjacency. To stay
    # locale-agnostic, prefer regex shape detection on the raw values.
    identity = _collect_flat_dl_values(soup)
    result[KEY_FIRMWARE] = _pick_firmware(identity)
    result[KEY_SERIAL] = _pick_serial(identity)
    result[KEY_MAC_ADDRESS] = _pick_mac(identity)
    result[KEY_EPSON_CONNECT_STATUS] = _pick_epson_connect(soup)

    return result


def _parse_ink_levels(soup: BeautifulSoup) -> dict[str, int]:
    """Return a ``{colour: percent}`` mapping for the visible ink tanks.

    Tries two approaches:
      1. img-based (ET-2750): <img src="Ink_BK.PNG" height="48">
      2. CSS class-based (L3250): <div class='tank_3rd'></div>
    """
    section = soup.find("ul", class_="inksection")
    if section is None:
        return {}

    levels: dict[str, int] = {}

    for li in section.find_all("li", class_="tank"):
        # Approach 1: img-based (EcoTank ET series)
        img = li.find("img")
        if img is not None:
            src = img.get("src") or ""
            match = _INK_FILENAME_RE.search(src)
            if match:
                colour_raw = match.group(1).upper()
                # Some firmwares prefix with multi-letter codes (e.g. "BK")
                colour = colour_raw[:1] if len(colour_raw) > 1 else colour_raw
                if colour not in INK_COLORS:
                    continue
                height = _to_int(img.get("height"))
                if height is None:
                    continue
                percent = max(0, min(100, round(height * 100 / INK_FULL_HEIGHT_PX)))
                levels[colour] = percent
                continue

        # Approach 2: CSS class-based (L3250 / newer EcoTank)
        tank_div = li.find("div", class_=_TANK_CLASS_RE)
        if tank_div is not None:
            classes = tank_div.get("class") or []
            level_num = None
            for cls in classes:
                m = _TANK_CLASS_RE.match(cls)
                if m:
                    level_num = int(m.group(1))
                    break

            if level_num is not None:
                # Map tank_N → percentage
                percent = max(0, min(100, round(level_num * 100 / TANK_MAX_LEVEL)))

                # Get colour from clrname div or fallback to position
                clrname_div = li.find("div", class_="clrname")
                if clrname_div:
                    colour_raw = clrname_div.get_text(strip=True).upper()
                    # Map "BK" → "K", "Y" → "Y", "M" → "M", "C" → "C"
                    if colour_raw == "BK":
                        colour = "K"
                    elif colour_raw in INK_COLORS:
                        colour = colour_raw
                    else:
                        colour = colour_raw[:1] if colour_raw else None
                else:
                    colour = None

                if colour and colour in INK_COLORS:
                    levels[colour] = percent

    return levels


def _parse_paper_source(soup: BeautifulSoup) -> dict[str, str | None]:
    """Return the configured paper size / type for the rear feeder, if shown."""
    for fs in _fieldsets_with_legend(soup):
        dl = fs.find("dl", class_="values")
        if dl is None:
            continue
        # Heuristic: the paper-source block has exactly two dd entries (size + type)
        # and is the only such block following the printer-status section.
        dds = dl.find_all("dd", recursive=False)
        if len(dds) != 2:
            continue
        size = _value_text(dds[0])
        ptype = _value_text(dds[1])
        if size or ptype:
            return {"size": size, "type": ptype}
    return {}


def _collect_flat_dl_values(soup: BeautifulSoup) -> list[str]:
    """Return all non-empty ``<dd>`` value strings from the page."""
    values: list[str] = []
    for dd in soup.find_all("dd", class_="value"):
        text = _value_text(dd)
        if text:
            values.append(text)
    return values


_FIRMWARE_RE = re.compile(r"^\d{2}\.\d{2}\.[A-Z0-9]+$")
_SERIAL_RE = re.compile(r"^[A-Z0-9]{8,}$")
_MAC_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$", re.IGNORECASE)


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


def _pick_epson_connect(soup: BeautifulSoup) -> str | None:
    """Best-effort extraction of the Epson Connect status string.

    Looks for a ``<dt>`` whose text contains "Epson Connect" (case-insensitive)
    -- the substring "Epson Connect" is itself not localised by the firmware.
    """
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
