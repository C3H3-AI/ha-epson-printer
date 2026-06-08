"""Config flow for Epson Printer."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_IPP_UUID,
    CONF_SCAN_INTERVAL,
    CONF_SCHEME,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCHEME,
    DOMAIN,
    HTTP_TIMEOUT_SECONDS,
    IPP_DOMAIN,
    MIN_SCAN_INTERVAL_SECONDS,
    PATH_PRODUCT_STATUS,
)
from .parser import parse_product_status

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_NAME, default="Epson Printer"): str,
        vol.Optional(CONF_SCHEME, default=DEFAULT_SCHEME): vol.In(["http", "https"]),
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
    }
)


def _lookup_ipp_identifier_by_host(hass: HomeAssistant, host: str) -> str | None:
    """Return IPP device UUID for merging with built-in IPP device."""
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
        config_url = (device.configuration_url or "").lower()
        if needle and needle in config_url:
            _LOGGER.debug(
                "Matched IPP device %s for host %s, identifier=%r",
                device.id, host, ipp_id,
            )
            return ipp_id
    return None


async def _validate_host(
    hass: HomeAssistant, host: str, scheme: str, port: int
) -> dict[str, Any]:
    """Fetch product-status page and return identity info."""
    session = async_get_clientsession(hass)
    default_port = 80 if scheme == "http" else 443
    netloc = host if port == default_port else f"{host}:{port}"
    url = f"{scheme}://{netloc}{PATH_PRODUCT_STATUS}"
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
    async with session.get(url, timeout=timeout, ssl=False) as resp:
        resp.raise_for_status()
        text = await resp.text(encoding="utf-8", errors="replace")
    return parse_product_status(text)


class EpsonPrinterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for Epson Printer."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host: str = user_input[CONF_HOST].strip()
            scheme: str = user_input[CONF_SCHEME]
            port: int = user_input[CONF_PORT]
            try:
                identity = await _validate_host(self.hass, host, scheme, port)
            except aiohttp.ClientResponseError as err:
                _LOGGER.debug("HTTP error from printer: %s", err)
                errors["base"] = "cannot_connect"
            except (aiohttp.ClientError, TimeoutError, OSError) as err:
                _LOGGER.debug("Connection error: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error validating Epson printer")
                errors["base"] = "unknown"
            else:
                ipp_uuid = _lookup_ipp_identifier_by_host(self.hass, host)
                unique_id = ipp_uuid or identity.get("serial") or host.lower()
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: host}
                )
                title = user_input.get(CONF_NAME) or identity.get("model") or host
                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_HOST: host,
                        CONF_NAME: title,
                        CONF_SCHEME: scheme,
                        CONF_PORT: port,
                        CONF_IPP_UUID: ipp_uuid,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return EpsonPrinterOptionsFlow(config_entry)


class EpsonPrinterOptionsFlow(config_entries.OptionsFlow):
    """Options flow for polling interval."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds())
        )
        schema = vol.Schema(
            {
                vol.Optional(CONF_SCAN_INTERVAL, default=current): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL_SECONDS)
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
