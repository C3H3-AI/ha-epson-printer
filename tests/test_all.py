"""Tests for Epson Printer integration — pure logic tests.
Loads modules with importlib to bypass homeassistant-dependent __init__.py."""
from __future__ import annotations

import sys
import os
import importlib.util

_test_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_test_dir)
_cc_path = os.path.join(_project_root, "custom_components")
_pkg_path = os.path.join(_cc_path, "epson_printer")

# Pre-load internal modules into sys.modules so relative imports resolve
def _preload(name, filename):
    """Load a module and register it as 'epson_printer.<name>'."""
    full_name = f"epson_printer.{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    spec = importlib.util.spec_from_file_location(full_name, filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod

_const = _preload("const", os.path.join(_pkg_path, "const.py"))
_parser = _preload("parser", os.path.join(_pkg_path, "parser.py"))
_ipl = _preload("ipp_client", os.path.join(_pkg_path, "ipp_client.py"))
_ctrl = _preload("control", os.path.join(_pkg_path, "control.py"))

from epson_printer.const import (
    KEY_PAGES_TOTAL, KEY_PAGES_BW, KEY_PAGES_COLOR,
    KEY_PAGES_DUPLEX, KEY_PAGES_SIMPLEX,
    KEY_FIRST_PRINT_DATE, KEY_PAGES_BY_FUNCTION, KEY_PAGES_BY_SIZE,
    KEY_PAGES_BY_LANGUAGE,
    KEY_INK_LEVELS, KEY_MAINTENANCE_BOX,
    KEY_PRINTER_STATUS, KEY_SCANNER_STATUS,
    KEY_FIRMWARE, KEY_SERIAL, KEY_MAC_ADDRESS, KEY_PAPER_SOURCE,
    KEY_MODEL, ESC_COMMANDS,
)
from epson_printer.control import EpsonPrinterControl
import pytest
from bs4 import BeautifulSoup, Tag


# ── Aliases for readability ────────────────────────────────────────────────
parse_maintenance = _parser.parse_maintenance
parse_product_status = _parser.parse_product_status
_to_int = _parser._to_int
_parse_iso_date = _parser._parse_iso_date
_li_level_value = _parser._li_level_value
_css_tank_level = _parser._css_tank_level
_pick_firmware = _parser._pick_firmware
_pick_serial = _parser._pick_serial
_pick_mac = _parser._pick_mac
EpsonIppClient = _ipl.EpsonIppClient

# sensor.py has HA dependency — skip for now
# _format_printer_state = _sensor._format_printer_state
# _parse_date = _sensor._parse_date
# _icon_for_function = _sensor._icon_for_function


# ── _to_int ────────────────────────────────────────────────────────────────

class TestToInt:
    def test_normal(self):    assert _to_int("42") == 42
    def test_trailing(self):  assert _to_int("123 pages") == 123
    def test_negative(self):  assert _to_int("-5") == -5
    def test_none(self):      assert _to_int(None) is None
    def test_no_digits(self): assert _to_int("N/A") is None
    def test_empty(self):     assert _to_int("") is None


# ── _parse_iso_date ────────────────────────────────────────────────────────

class TestParseIsoDate:
    def test_standard(self):     assert _parse_iso_date("2024-3-15") == "2024-03-15"
    def test_padded(self):       assert _parse_iso_date("2024-03-15") == "2024-03-15"
    def test_invalid_month(self): assert _parse_iso_date("2024-13-01") is None
    def test_none(self):         assert _parse_iso_date(None) is None
    def test_garbage(self):      assert _parse_iso_date("xyz") is None


# ── Identity field recognition ─────────────────────────────────────────────

class TestPickFirmware:
    def test_match(self):  assert _pick_firmware(["12.34.ABCDE"]) == "12.34.ABCDE"
    def test_none(self):   assert _pick_firmware(["plain"]) is None
    def test_empty(self):  assert _pick_firmware([]) is None

class TestPickSerial:
    def test_match(self):     assert _pick_serial(["ABC12345DE"]) == "ABC12345DE"
    def test_dot(self):       assert _pick_serial(["12.34.A", "ABC12345DE"]) == "ABC12345DE"
    def test_too_short(self): assert _pick_serial(["SHORT"]) is None
    def test_empty(self):     assert _pick_serial([]) is None

class TestPickMac:
    def test_upper(self):  assert _pick_mac(["00:1B:44:11:3A:B7"]) == "00:1B:44:11:3A:B7"
    def test_lower(self):  assert _pick_mac(["00:1b:44:11:3a:b7"]) == "00:1B:44:11:3A:B7"
    def test_none(self):   assert _pick_mac(["foo"]) is None


# ── Ink level helpers (pure HTML parsing) ──────────────────────────────────

class TestLiLevelValue:
    def test_img_100(self):
        li = BeautifulSoup('<li class="tank"><img src="Ink_BK.PNG" height="50"></li>', "html.parser").find("li")
        assert _li_level_value(li) == 100
    def test_img_50(self):
        li = BeautifulSoup('<li class="tank"><img src="Ink_BK.PNG" height="25"></li>', "html.parser").find("li")
        assert _li_level_value(li) == 50
    def test_img_0(self):
        li = BeautifulSoup('<li class="tank"><img src="Ink_BK.PNG" height="0"></li>', "html.parser").find("li")
        assert _li_level_value(li) == 0
    def test_img_clamp(self):
        li = BeautifulSoup('<li class="tank"><img src="Ink_BK.PNG" height="99"></li>', "html.parser").find("li")
        assert _li_level_value(li) == 100  # clamped
    def test_css_full(self):
        li = BeautifulSoup('<li class="tank"><div class="tank_4th"></div></li>', "html.parser").find("li")
        assert _li_level_value(li) == 100
    def test_css_half(self):
        li = BeautifulSoup('<li class="tank"><div class="tank_2nd"></div></li>', "html.parser").find("li")
        assert _li_level_value(li) == 50
    def test_style(self):
        li = BeautifulSoup('<li class="tank"><div style="height:25px"></div></li>', "html.parser").find("li")
        assert _li_level_value(li) == 50
    def test_no_data(self):
        li = BeautifulSoup('<li class="tank"><span>X</span></li>', "html.parser").find("li")
        assert _li_level_value(li) is None

class TestCssTankLevel:
    def test_4th(self):  assert _css_tank_level(self._m("tank_4th")) == 100
    def test_3rd(self):  assert _css_tank_level(self._m("tank_3rd")) == 75
    def test_2nd(self):  assert _css_tank_level(self._m("tank_2nd")) == 50
    def test_1st(self):  assert _css_tank_level(self._m("tank_1st")) == 25
    def test_0th(self):  assert _css_tank_level(self._m("tank_0th")) == 0
    def test_none(self): assert _css_tank_level(self._m("other")) is None
    @staticmethod
    def _m(c): return BeautifulSoup(f'<div class="{c}"></div>', "html.parser").find("div")


# ── parse_maintenance ──────────────────────────────────────────────────────

FULL_HTML = """<html><body><div class="section">
  <dl class="values"><dd class="value"><div class="preserve-white-space">2024-3-15</div></dd></dl>
  <fieldset class="group"><legend>Counter</legend>
    <dd class="value"><div class="preserve-white-space">1234</div></dd>
    <dd class="value"><div class="preserve-white-space">800</div></dd>
    <dd class="value"><div class="preserve-white-space">434</div></dd>
    <dd class="value"><div class="preserve-white-space">600</div></dd>
    <dd class="value"><div class="preserve-white-space">634</div></dd>
  </fieldset>
  <fieldset class="group"><legend>Size</legend><table class="values"><tbody>
    <tr><td class="value number">10</td><td class="value number">20</td><td class="value number">30</td><td class="value number">40</td></tr>
  </tbody></table></fieldset>
  <fieldset class="group"><legend>Function</legend><dl class="values">
    <dd class="value"><div class="preserve-white-space">100</div></dd>
    <dd class="value"><div class="preserve-white-space">200</div></dd>
    <dd class="value"><div class="preserve-white-space">300</div></dd>
    <dd class="value"><div class="preserve-white-space">400</div></dd>
    <dd class="value"><div class="preserve-white-space">500</div></dd>
    <dd class="value"><div class="preserve-white-space">600</div></dd>
    <dd class="value"><div class="preserve-white-space">700</div></dd>
    <dd class="value"><div class="preserve-white-space">800</div></dd>
    <dd class="value"><div class="preserve-white-space">900</div></dd>
    <dd class="value"><div class="preserve-white-space">1000</div></dd>
  </dl></fieldset>
  <fieldset class="group"><legend>Language</legend><dl class="values">
    <dd class="value"><div class="preserve-white-space">50</div></dd>
    <dd class="value"><div class="preserve-white-space">60</div></dd>
    <dd class="value"><div class="preserve-white-space">70</div></dd>
    <dd class="value"><div class="preserve-white-space">80</div></dd>
    <dd class="value"><div class="preserve-white-space">90</div></dd>
  </dl></fieldset>
</div></body></html>"""

PARTIAL_HTML = """<html><body><div class="section">
  <fieldset class="group"><legend>P</legend>
    <dd class="value"><div class="preserve-white-space">999</div></dd>
  </fieldset>
</div></body></html>"""

EMPTY_HTML = "<html><body></body></html>"

# Real-world EcoTank / L-series layout: per-size (simplex/duplex × bw/color)
# table, a function dl, and a language dl — but NO dedicated "totals" fieldset.
# Totals must be derived from pages_by_size.
L3250_HTML = """<html><body><div class="section">
  <dl class="values"><dd class="value"><div class="preserve-white-space">2025-3-1</div></dd></dl>
  <fieldset class="group"><legend>Size</legend><table class="values"><tbody>
    <tr><td class="value number">0</td><td class="value number">0</td><td class="value number">0</td><td class="value number">0</td></tr>
    <tr><td class="value number">229</td><td class="value number">2180</td><td class="value number">0</td><td class="value number">0</td></tr>
    <tr><td class="value number">0</td><td class="value number">26</td><td class="value number">0</td><td class="value number">0</td></tr>
    <tr><td class="value number">0</td><td class="value number">3</td><td class="value number">0</td><td class="value number">0</td></tr>
    <tr><td class="value number">0</td><td class="value number">0</td><td class="value number">0</td><td class="value number">0</td></tr>
    <tr><td class="value number">0</td><td class="value number">0</td><td class="value number">0</td><td class="value number">0</td></tr>
    <tr><td class="value number">0</td><td class="value number">0</td><td class="value number">0</td><td class="value number">0</td></tr>
    <tr><td class="value number">0</td><td class="value number">68</td><td class="value number">0</td><td class="value number">0</td></tr>
  </tbody></table></fieldset>
  <fieldset class="group"><legend>Function</legend><dl class="values">
    <dd class="value"><div class="preserve-white-space">2506</div></dd>
    <dd class="value"><div class="preserve-white-space">229</div></dd>
    <dd class="value"><div class="preserve-white-space">2277</div></dd>
    <dd class="value"><div class="preserve-white-space">0</div></dd>
    <dd class="value"><div class="preserve-white-space">2506</div></dd>
    <dd class="value"><div class="preserve-white-space"></div></dd>
    <dd class="value"><div class="preserve-white-space"></div></dd>
    <dd class="value"><div class="preserve-white-space"></div></dd>
    <dd class="value"><div class="preserve-white-space"></div></dd>
    <dd class="value"><div class="preserve-white-space"></div></dd>
  </dl></fieldset>
  <fieldset class="group"><legend>Language</legend><dl class="values">
    <dd class="value"><div class="preserve-white-space">124</div></dd>
    <dd class="value"><div class="preserve-white-space">52</div></dd>
    <dd class="value"><div class="preserve-white-space">0</div></dd>
    <dd class="value"><div class="preserve-white-space">0</div></dd>
    <dd class="value"><div class="preserve-white-space">123</div></dd>
  </dl></fieldset>
</div></body></html>"""

# Printer that exposes ONLY a function breakdown (no size table, no totals).
FUNC_ONLY_HTML = """<html><body><div class="section">
  <fieldset class="group"><legend>Function</legend><dl class="values">
    <dd class="value"><div class="preserve-white-space">100</div></dd>
    <dd class="value"><div class="preserve-white-space">50</div></dd>
    <dd class="value"><div class="preserve-white-space"></div></dd>
    <dd class="value"><div class="preserve-white-space"></div></dd>
    <dd class="value"><div class="preserve-white-space"></div></dd>
    <dd class="value"><div class="preserve-white-space"></div></dd>
    <dd class="value"><div class="preserve-white-space"></div></dd>
    <dd class="value"><div class="preserve-white-space"></div></dd>
    <dd class="value"><div class="preserve-white-space"></div></dd>
    <dd class="value"><div class="preserve-white-space"></div></dd>
  </dl></fieldset>
</div></body></html>"""


class TestParseMaintenance:
    def test_full(self):
        r = parse_maintenance(FULL_HTML)
        assert r[KEY_PAGES_TOTAL] == 1234
        assert r[KEY_PAGES_BW] == 800
        assert r[KEY_PAGES_COLOR] == 434
        assert r[KEY_PAGES_DUPLEX] == 600
        assert r[KEY_PAGES_SIMPLEX] == 634
        assert r[KEY_FIRST_PRINT_DATE] == "2024-03-15"

    def test_functions(self):
        r = parse_maintenance(FULL_HTML)
        f = r[KEY_PAGES_BY_FUNCTION]
        assert f["bw_copy"] == 100;   assert f["color_copy"] == 200
        assert f["bw_fax"] == 300;    assert f["color_fax"] == 400
        assert f["bw_scan"] == 500;   assert f["color_scan"] == 600
        assert f["bw_print"] == 700;  assert f["color_print"] == 800
        assert f["bw_other"] == 900;  assert f["color_other"] == 1000

    def test_size_table(self):
        r = parse_maintenance(FULL_HTML)
        s = r[KEY_PAGES_BY_SIZE]
        # Single row → SIZE_KEYS[0] = "a3_ledger"
        assert "a3_ledger" in s
        assert s["a3_ledger"]["simplex_bw"] == 10; assert s["a3_ledger"]["simplex_color"] == 20
        assert s["a3_ledger"]["duplex_bw"] == 30;  assert s["a3_ledger"]["duplex_color"] == 40

    def test_partial(self):
        r = parse_maintenance(PARTIAL_HTML)
        assert r[KEY_PAGES_TOTAL] == 999
        assert r[KEY_PAGES_BW] is None
        assert r[KEY_PAGES_BY_FUNCTION] == {}

    def test_empty(self):
        assert parse_maintenance(EMPTY_HTML)[KEY_PAGES_TOTAL] is None


class TestParseMaintenanceL3250:
    """EcoTank / L-series: no totals fieldset, totals derived from by_size."""

    def test_derived_totals(self):
        r = parse_maintenance(L3250_HTML)
        # Aggregated from the per-size table (simplex_bw/color, duplex_bw/color).
        assert r[KEY_PAGES_TOTAL] == 2506
        assert r[KEY_PAGES_SIMPLEX] == 2506
        assert r[KEY_PAGES_DUPLEX] == 0
        assert r[KEY_PAGES_BW] == 229
        assert r[KEY_PAGES_COLOR] == 2277

    def test_first_print_date(self):
        r = parse_maintenance(L3250_HTML)
        assert r[KEY_FIRST_PRINT_DATE] == "2025-03-01"

    def test_functions_present_absent(self):
        r = parse_maintenance(L3250_HTML)
        f = r[KEY_PAGES_BY_FUNCTION]
        # Reported functions keep their values.
        assert f["bw_copy"] == 2506
        assert f["color_copy"] == 229
        assert f["bw_fax"] == 2277
        assert f["bw_scan"] == 2506
        assert f["color_fax"] == 0
        # Not exposed by this model → None (sensor should be filtered out).
        assert f["bw_print"] is None
        assert f["color_print"] is None
        assert f["color_scan"] is None
        assert f["bw_other"] is None
        assert f["color_other"] is None

    def test_language_parsed(self):
        r = parse_maintenance(L3250_HTML)
        lang = r[KEY_PAGES_BY_LANGUAGE]
        assert lang["escpr"] == 124
        assert lang["pcl"] == 52
        assert lang["other"] == 123


class TestParseMaintenanceFuncOnly:
    """Printer with only a function breakdown (no size table, no totals)."""

    def test_totals_from_function(self):
        r = parse_maintenance(FUNC_ONLY_HTML)
        assert r[KEY_PAGES_BY_SIZE] == {}
        assert r[KEY_PAGES_TOTAL] == 150
        assert r[KEY_PAGES_BW] == 100
        assert r[KEY_PAGES_COLOR] == 50
        # No simplex/duplex breakdown available → stay None.
        assert r[KEY_PAGES_SIMPLEX] is None
        assert r[KEY_PAGES_DUPLEX] is None

    def test_no_size_language_dimensions(self):
        # A function-only printer must not expose size/language counters,
        # so no dead entities should ever be created for them.
        r = parse_maintenance(FUNC_ONLY_HTML)
        assert r[KEY_PAGES_BY_SIZE] == {}
        assert r[KEY_PAGES_BY_LANGUAGE] == {}


class TestSizeLanguageDimensions:
    """The previously-discarded pages_by_size / pages_by_language dimensions.

    These back the data-driven ``pages_size_*`` / ``pages_language_*`` sensors.
    Lock the parsed structure so the new entities always have real data.
    """

    def test_l3250_size_keys(self):
        r = parse_maintenance(L3250_HTML)
        s = r[KEY_PAGES_BY_SIZE]
        # SIZE_KEYS order: row0=a3_ledger, then a4_letter, a5, a6, ...
        # L3250's 8 rows map to the known SIZE_KEYS list.
        assert "a4_letter" in s
        assert "a5" in s
        assert "a6" in s
        assert "other" in s

    def test_l3250_size_subvalues(self):
        r = parse_maintenance(L3250_HTML)
        s = r[KEY_PAGES_BY_SIZE]
        # Representative row values from the real L3250 maintenance page.
        assert s["a4_letter"]["simplex_bw"] == 229
        assert s["a4_letter"]["simplex_color"] == 2180
        assert s["a4_letter"]["duplex_bw"] == 0
        assert s["a4_letter"]["duplex_color"] == 0
        assert s["a5"]["simplex_color"] == 26
        assert s["a6"]["simplex_color"] == 3
        assert s["other"]["simplex_color"] == 68

    def test_size_total_aggregation(self):
        # Mirror the lambda used by the pages_size_* sensor value_fn.
        r = parse_maintenance(L3250_HTML)
        s = r[KEY_PAGES_BY_SIZE]
        total_a4 = sum(v for v in s["a4_letter"].values() if v)
        assert total_a4 == 229 + 2180  # 2409
        total_all = sum(
            sum(v for v in vals.values() if v) for vals in s.values()
        )
        # matches the derived pages_total (2506) from the per-size table
        assert total_all == 2506

    def test_language_values(self):
        r = parse_maintenance(L3250_HTML)
        lang = r[KEY_PAGES_BY_LANGUAGE]
        assert lang["escpr"] == 124
        assert lang["pcl"] == 52
        assert lang["postscript_pdf"] == 0
        assert lang["escpage"] == 0
        assert lang["other"] == 123


# ── parse_product_status ───────────────────────────────────────────────────

IMG_HTML = """<html><head><title>ET-2750</title></head><body>
<fieldset class="group"><legend>S</legend><li class="value">Ready</li></fieldset>
<fieldset id="PRT_STATUS">Ready</fieldset>
<fieldset id="SCN_STATUS">Scanner OK</fieldset>
<ul class="inksection">
  <li class="tank"><img src="Ink_BK.PNG" height="48"><div>K</div></li>
  <li class="tank"><img src="Ink_C.PNG" height="30"><div>C</div></li>
  <li class="tank"><img src="Ink_M.PNG" height="20"><div>M</div></li>
  <li class="tank"><img src="Ink_Y.PNG" height="10"><div>Y</div></li>
  <li class="tank"><div class="mbicn_warn"></div><img src="Ink_BK.PNG" height="25"></li>
</ul>
<dl class="values">
  <dt class="key">Firmware</dt><dd class="value">12.34.ABCDE</dd>
  <dt class="key">Serial</dt><dd class="value">ABC12345DE</dd>
  <dt class="key">MAC</dt><dd class="value">00:1B:44:11:3A:B7</dd>
</dl>
</body></html>"""

CSS_HTML = """<html><head><title>L3250</title></head><body>
<fieldset class="group"><legend>S</legend><li class="value"><div class="preserve-white-space">Ready</div></li></fieldset>
<ul class="inksection">
  <li class="tank"><div class="tank_4th"></div><div class="clrname">BK</div></li>
  <li class="tank"><div class="tank_3rd"></div><div class="clrname">C</div></li>
  <li class="tank"><div class="tank_2nd"></div><div class="clrname">M</div></li>
  <li class="tank"><div class="tank_1st"></div><div class="clrname">Y</div></li>
</ul>
</body></html>"""

MIN_HTML = "<html><body></body></html>"

PAPER_HTML = """<html><head><title>L3250</title></head><body>
<fieldset class="group"><legend>Paper Source</legend><dl class="values">
  <dd class="value"><div class="preserve-white-space">A4</div></dd>
  <dd class="value"><div class="preserve-white-space">Plain Paper</div></dd>
</dl></fieldset>
</body></html>"""


class TestParseProductStatus:
    def test_img_inks(self):
        r = parse_product_status(IMG_HTML)
        inks = r[KEY_INK_LEVELS]
        assert inks["K"] == 96; assert inks["C"] == 60
        assert inks["M"] == 40; assert inks["Y"] == 20

    def test_maintenance_box(self):
        r = parse_product_status(IMG_HTML)
        assert r[KEY_MAINTENANCE_BOX] == 50  # 25/50*100

    def test_css_inks(self):
        r = parse_product_status(CSS_HTML)
        inks = r[KEY_INK_LEVELS]
        assert inks["K"] == 100; assert inks["C"] == 75
        assert inks["M"] == 50;  assert inks["Y"] == 25

    def test_identity(self):
        r = parse_product_status(IMG_HTML)
        assert r[KEY_PRINTER_STATUS] == "Ready"
        assert r[KEY_SCANNER_STATUS] is not None
        assert r[KEY_FIRMWARE] == "12.34.ABCDE"
        assert r[KEY_SERIAL] == "ABC12345DE"
        assert r[KEY_MAC_ADDRESS] == "00:1B:44:11:3A:B7"
        assert r[KEY_MODEL] == "ET-2750"

    def test_minimal(self):
        r = parse_product_status(MIN_HTML)
        assert r[KEY_INK_LEVELS] == {}
        assert r[KEY_PRINTER_STATUS] is None

    def test_paper_source(self):
        r = parse_product_status(PAPER_HTML)
        ps = r[KEY_PAPER_SOURCE]
        assert ps == {"size": "A4", "type": "Plain Paper"}

    def test_paper_source_absent(self):
        r = parse_product_status(MIN_HTML)
        assert r[KEY_PAPER_SOURCE] == {}


# ── IPP binary protocol (no network) ──────────────────────────────────────

class TestIppProtocol:
    def test_build_structure(self):
        import struct
        c = EpsonIppClient("h")
        b = c._build_request(0x000B, "ipp://h:631/p")
        assert struct.unpack(">H", b[0:2])[0] == 0x0200
        assert struct.unpack(">H", b[2:4])[0] == 0x000B
        assert struct.unpack(">I", b[4:8])[0] == 1

    def test_has_required_fields(self):
        c = EpsonIppClient("h")
        b = c._build_request(0x000B, "ipp://h/p")
        for token in [b"printer-uri", b"ipp://h/p", b"attributes-charset",
                      b"utf-8", b"attributes-natural-language", b"en-us",
                      b"requested-attributes", b"all"]:
            assert token in b, f"Missing {token!r}"

    def test_decode_int(self):
        import struct
        c = EpsonIppClient("h")
        assert c._decode_value(0x21, struct.pack(">i", 42), "x") == 42
        assert c._decode_value(0x21, struct.pack(">i", -1), "x") == -1

    def test_decode_bool(self):
        c = EpsonIppClient("h")
        assert c._decode_value(0x22, b"\x01", "x") is True
        assert c._decode_value(0x22, b"\x00", "x") is False

    def test_decode_enum(self):
        import struct
        assert EpsonIppClient("h")._decode_value(0x23, struct.pack(">i", 3), "x") == 3

    def test_decode_string(self):
        assert EpsonIppClient("h")._decode_value(0x44, b"idle", "x") == "idle"
        assert EpsonIppClient("h")._decode_value(0x41, b"text", "x") == "text"
        assert EpsonIppClient("h")._decode_value(0x45, b"uri", "x") == "uri"
        assert EpsonIppClient("h")._decode_value(0x47, b"utf-8", "x") == "utf-8"

    def test_decode_out_of_band(self):
        c = EpsonIppClient("h")
        assert c._decode_value(0x10, b"x", "x") is None  # unsupported
        assert c._decode_value(0x12, b"x", "x") is None  # no-value
        assert c._decode_value(0x13, b"x", "x") is None  # unknown

    def test_decode_range(self):
        import struct
        r = EpsonIppClient("h")._decode_value(0x33, struct.pack(">ii", 1, 999), "x")
        assert r == (1, 999)

    def test_decode_resolution(self):
        import struct
        r = EpsonIppClient("h")._decode_value(0x32, struct.pack(">iiB", 600, 1200, 3), "x")
        assert r == "600x1200 dpi"

    def test_parse(self):
        import struct
        c = EpsonIppClient("h")
        # IPP header: version(2) + status(2) + request-id(4) = 8 bytes
        d = struct.pack(">HHI", 0x0200, 0x0000, 1)
        d += bytes([0x04])  # printer group
        n, v = b"test", b"value"
        d += bytes([0x44]) + struct.pack(">H", len(n)) + n + struct.pack(">H", len(v)) + v
        d += bytes([0x03])
        attrs, _ = c._parse_attributes(d, 8)
        assert attrs.get("test") == "value"

    def test_parse_empty(self):
        a, p = EpsonIppClient("h")._parse_attributes(b"", 0)
        assert a == {}

    def test_parse_truncated(self):
        import struct
        d = bytes([0x04, 0x21]) + struct.pack(">H", 5000)  # int tag with huge name len
        a, _ = EpsonIppClient("h")._parse_attributes(d, 0)
        assert a == {}


# ── ESC/P command bytes ────────────────────────────────────────────────────

class TestEscCommands:
    def test_init(self):  assert ESC_COMMANDS["initialize"] == b"\x1b\x40"
    def test_clean(self): assert ESC_COMMANDS["printhead_clean"] == b"\x1b(C\x02\x00\x00\x01"
    def test_deep(self):  assert ESC_COMMANDS["printhead_clean_deep"] == b"\x1b(C\x02\x00\x00\x02"



