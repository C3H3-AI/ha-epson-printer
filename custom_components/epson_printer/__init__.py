"""Epson Printer integration — HTML scraping + IPP state + Raw control."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_IPP_UUID,
    DOMAIN,
    IPP_DOMAIN,
    SERVICE_CLEAN_PRINTHEAD,
    SERVICE_NOZZLE_CHECK,
    SERVICE_PRINT_FILE,
    SERVICE_PRINT_TEXT,
)
from .control import EpsonPrinterControl
from .coordinator import EpsonPrinterCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


def _find_ipp_identifier(hass: HomeAssistant, host: str) -> str | None:
    """Find the IPP device identifier for a host (for device merging)."""
    registry = dr.async_get(hass)
    needle = host.lower()
    for device in registry.devices.values():
        ipp_id: str | None = None
        for domain, identifier in device.identifiers:
            if domain == IPP_DOMAIN:
                ipp_id = identifier
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

def _register_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register RAW 9100 print control services (register once)."""

    if hass.services.has_service(DOMAIN, SERVICE_PRINT_TEXT):
        return

    async def _handle_print_text(call: ServiceCall):
        entry_id = next(iter(hass.data.get(DOMAIN, {})))
        host = call.data.get("host", "")
        if not host:
            for eid, data in hass.data.get(DOMAIN, {}).items():
                host = data.get("host", "")
                break
        control = EpsonPrinterControl(
            host or hass.config_entries.async_get_entry(entry_id).data[CONF_HOST],
            9100,
        )
        text = call.data.get("text", "")
        result = await hass.async_add_executor_job(control.print_text, text)
        if not result:
            _LOGGER.error("Failed to print text")

    async def _handle_print_file(call: ServiceCall):
        entry_id = next(iter(hass.data.get(DOMAIN, {})))
        host = hass.config_entries.async_get_entry(entry_id).data[CONF_HOST]
        control = EpsonPrinterControl(host, 9100)
        filepath = call.data.get("filepath", "")
        result = await hass.async_add_executor_job(control.print_file, filepath)
        if not result:
            _LOGGER.error("Failed to print file: %s", filepath)

    async def _handle_clean_printhead(call: ServiceCall):
        entry_id = next(iter(hass.data.get(DOMAIN, {})))
        host = hass.config_entries.async_get_entry(entry_id).data[CONF_HOST]
        control = EpsonPrinterControl(host, 9100)
        deep = call.data.get("deep", False)
        result = await hass.async_add_executor_job(control.clean_printhead, deep)
        if not result:
            _LOGGER.error("Failed to clean printhead")

    async def _handle_nozzle_check(call: ServiceCall):
        entry_id = next(iter(hass.data.get(DOMAIN, {})))
        host = hass.config_entries.async_get_entry(entry_id).data[CONF_HOST]
        control = EpsonPrinterControl(host, 9100)
        result = await hass.async_add_executor_job(control.nozzle_check)
        if not result:
            _LOGGER.error("Failed to run nozzle check")

    hass.services.async_register(DOMAIN, SERVICE_PRINT_TEXT, _handle_print_text)
    hass.services.async_register(DOMAIN, SERVICE_PRINT_FILE, _handle_print_file)
    hass.services.async_register(DOMAIN, SERVICE_CLEAN_PRINTHEAD, _handle_clean_printhead)
    hass.services.async_register(DOMAIN, SERVICE_NOZZLE_CHECK, _handle_nozzle_check)
