"""Epson Printer integration — HTML scraping + IPP state + Raw control."""

from __future__ import annotations

import logging
import os

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_IPP_UUID,
    DOMAIN,
    IPP_DOMAIN,
    SERVICE_CLEAN_PRINTHEAD,
    SERVICE_IPP_PRINT_FILE,
    SERVICE_NOZZLE_CHECK,
    SERVICE_PRINT_FILE,
    SERVICE_PRINT_TEXT,
    SERVICE_INITIALIZE,
)
from .control import EpsonPrinterControl
from .coordinator import EpsonPrinterCoordinator
from .ipp_client import EpsonIppClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


def _find_ipp_identifier(hass: HomeAssistant, host: str) -> str | None:
    """Find the IPP device identifier for a host (for device merging)."""
    registry = dr.async_get(hass)
    needle = host.lower()
    for device in registry.devices.values():
        ipp_id: str | None = None
        for identifier_tuple in device.identifiers:
            domain = identifier_tuple[0]
            if domain == IPP_DOMAIN:
                if len(identifier_tuple) >= 2:
                    ipp_id = str(identifier_tuple[1])
                break
        if ipp_id is None:
            continue
        if needle and needle in (device.configuration_url or "").lower():
            return ipp_id
    return None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Epson Printer from a config entry."""
    host = entry.data.get(CONF_HOST)
    if host:
        registry_ipp_id = _find_ipp_identifier(hass, host)
        if registry_ipp_id and registry_ipp_id != entry.data.get(CONF_IPP_UUID):
            _LOGGER.debug(
                "Updating ipp_uuid for entry %s: %r -> %r",
                entry.entry_id,
                entry.data.get(CONF_IPP_UUID),
                registry_ipp_id,
            )
            hass.config_entries.async_update_entry(
                entry,
                data={**entry.data, CONF_IPP_UUID: registry_ipp_id},
            )

    coordinator = EpsonPrinterCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Register RAW print control services
    _register_services(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


# ── Service registration ───────────────────────────────────────────────────

def _resolve_printer_entry_id(
    hass: HomeAssistant, call: ServiceCall
) -> str | None:
    """Resolve the target entry_id from service call data.

    Priority:
      1. ``entry_id`` parameter in the service call
      2. ``host`` parameter in the service call (match by host)
      3. First available entry (single-printer fallback)

    Returns ``None`` when no entry is configured or found.
    """
    entries = hass.data.get(DOMAIN, {})

    # 1. Explicit entry_id
    entry_id = str(call.data.get("entry_id", "") or "")
    if entry_id and entry_id in entries:
        return entry_id

    # 2. Match by host
    host = str(call.data.get("host", "") or "")
    if host:
        for eid, coordinator in entries.items():
            if coordinator.entry.data.get(CONF_HOST) == host:
                return eid

    # 3. First available entry
    for eid in entries:
        return eid

    _LOGGER.error("No Epson printer entries configured")
    return None


def _register_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register RAW 9100 print control services (register once)."""

    if hass.services.has_service(DOMAIN, SERVICE_PRINT_TEXT):
        return

    async def _handle_print_text(call: ServiceCall):
        entry_id = _resolve_printer_entry_id(hass, call)
        if entry_id is None:
            return
        host = hass.config_entries.async_get_entry(entry_id).data[CONF_HOST]
        control = EpsonPrinterControl(host, 9100)
        text = call.data.get("text", "")
        result = await hass.async_add_executor_job(control.print_text, text)
        if not result:
            _LOGGER.error("Failed to print text")

    async def _handle_print_file(call: ServiceCall):
        entry_id = _resolve_printer_entry_id(hass, call)
        if entry_id is None:
            return
        host = hass.config_entries.async_get_entry(entry_id).data[CONF_HOST]
        control = EpsonPrinterControl(host, 9100)
        filepath = call.data.get("filepath", "")
        result = await hass.async_add_executor_job(control.print_file, filepath)
        if not result:
            _LOGGER.error("Failed to print file: %s", filepath)

    async def _handle_clean_printhead(call: ServiceCall):
        entry_id = _resolve_printer_entry_id(hass, call)
        if entry_id is None:
            return
        host = hass.config_entries.async_get_entry(entry_id).data[CONF_HOST]
        control = EpsonPrinterControl(host, 9100)
        deep = call.data.get("deep", False)
        result = await hass.async_add_executor_job(control.clean_printhead, deep)
        if not result:
            _LOGGER.error("Failed to clean printhead")

    async def _handle_nozzle_check(call: ServiceCall):
        entry_id = _resolve_printer_entry_id(hass, call)
        if entry_id is None:
            return
        host = hass.config_entries.async_get_entry(entry_id).data[CONF_HOST]
        control = EpsonPrinterControl(host, 9100)
        result = await hass.async_add_executor_job(control.nozzle_check)
        if not result:
            _LOGGER.error("Failed to run nozzle check")

    async def _handle_ipp_print_file(call: ServiceCall):
        """Print a file via IPP (supports JPEG, PNG, PDF)."""
        entry_id = _resolve_printer_entry_id(hass, call)
        if entry_id is None:
            return
        entry = hass.config_entries.async_get_entry(entry_id)
        host = entry.data[CONF_HOST]
        file_path = call.data.get("file_path", "")
        job_name = call.data.get("job_name")

        if not file_path:
            _LOGGER.error("IPP print: no file_path provided")
            return

        # MIME type hint — print_job auto-converts JPEG/PNG/BMP to PWG-Raster
        ext = os.path.splitext(file_path)[1].lower()
        mime_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".pdf": "application/pdf",
            ".tif": "image/tiff",
            ".tiff": "image/tiff",
            ".bmp": "image/bmp",
        }
        doc_format = mime_map.get(ext, "application/octet-stream")

        try:
            with open(file_path, "rb") as f:
                file_bytes = f.read()
        except OSError as err:
            _LOGGER.error("IPP print: cannot read file %s: %s", file_path, err)
            return

        ipp = EpsonIppClient(host, 631, use_ssl=True)
        result = await hass.async_add_executor_job(
            ipp.print_job, file_bytes, doc_format, job_name
        )
        if not result or result.get("job_id") is None:
            _LOGGER.error("IPP print failed for %s", file_path)

    hass.services.async_register(DOMAIN, SERVICE_PRINT_TEXT, _handle_print_text)
    hass.services.async_register(DOMAIN, SERVICE_PRINT_FILE, _handle_print_file)
    hass.services.async_register(DOMAIN, SERVICE_CLEAN_PRINTHEAD, _handle_clean_printhead)
    hass.services.async_register(DOMAIN, SERVICE_NOZZLE_CHECK, _handle_nozzle_check)
    async def _handle_initialize(call: ServiceCall):
        """Send ESC @ to reset the printer to its initial state."""
        entry_id = _resolve_printer_entry_id(hass, call)
        if entry_id is None:
            return
        host = hass.config_entries.async_get_entry(entry_id).data[CONF_HOST]
        control = EpsonPrinterControl(host, 9100)
        result = await hass.async_add_executor_job(control.initialize)
        if not result:
            _LOGGER.error("Failed to initialize printer")

    hass.services.async_register(DOMAIN, SERVICE_PRINT_TEXT, _handle_print_text)
    hass.services.async_register(DOMAIN, SERVICE_PRINT_FILE, _handle_print_file)
    hass.services.async_register(DOMAIN, SERVICE_CLEAN_PRINTHEAD, _handle_clean_printhead)
    hass.services.async_register(DOMAIN, SERVICE_NOZZLE_CHECK, _handle_nozzle_check)
    hass.services.async_register(DOMAIN, SERVICE_IPP_PRINT_FILE, _handle_ipp_print_file)
    hass.services.async_register(DOMAIN, SERVICE_INITIALIZE, _handle_initialize)
