"""Config flow for Epson Printer."""

from __future__ import annotations

import asyncio
import logging
import ssl
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


# Shared SSL context that never validates — Epson printers use self-signed certs
_INSECURE_SSL_CTX: ssl.SSLContext | None = None


def _get_insecure_ssl_ctx() -> ssl.SSLContext:
    global _INSECURE_SSL_CTX
    if _INSECURE_SSL_CTX is None:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        _INSECURE_SSL_CTX = ctx
    return _INSECURE_SSL_CTX


async def _try_fetch_status(
    hass: HomeAssistant, host: str, scheme: str, port: int
) -> dict[str, Any]:
    """Attempt to fetch and parse the product-status page with given settings."""
    session = async_get_clientsession(hass)
    default_port = 80 if scheme == "http" else 443
    netloc = host if port == default_port else f"{host}:{port}"
    url = f"{scheme}://{netloc}{PATH_PRODUCT_STATUS}"
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
    kwargs: dict[str, Any] = {}
    if scheme == "https":
        kwargs["ssl_context"] = _get_insecure_ssl_ctx()
    else:
        kwargs["ssl"] = False
    _LOGGER.debug(
        "Fetching %s timeout=%s kwargs=%s",
        url, timeout, {k: type(v).__name__ for k, v in kwargs.items()}
    )
    async with session.get(url, timeout=timeout, **kwargs) as resp:
        _LOGGER.debug("Response %s from %s", resp.status, resp.url)
        resp.raise_for_status()
        text = await resp.text(encoding="utf-8", errors="replace")
    return parse_product_status(text)


def _lookup_ipp_identifier_by_host(hass: HomeAssistant, host: str) -> str | None:
    """Return IPP device UUID for merging with built-in IPP device."""
    registry = dr.async_get(hass)
    needle = host.lower()
    for device in registry.devices.values():
        ipp_id: str | None = None
        for identifier_tuple in device.identifiers:
            domain = identifier_tuple[0]
            if domain == IPP_DOMAIN:
                # HA identifiers can be 2-tuple: (domain, id)
                # or 3-tuple: (domain, id, sub_key)
                if len(identifier_tuple) >= 2:
                    ipp_id = str(identifier_tuple[1])
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
    """Fetch product-status page and return identity info.

    Tries the requested scheme first, then auto-fallsback to the
    opposite scheme if the first attempt fails.  This saves users
    from having to know whether their printer speaks HTTP or HTTPS.
    """
    first_scheme = scheme
    fallback_scheme = "http" if scheme == "https" else "https"
    last_exception: Exception | None = None

    for try_scheme in (first_scheme, fallback_scheme):
        try:
            return await _try_fetch_status(hass, host, try_scheme, port)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            last_exception = exc
            _LOGGER.debug(
                "%s://%s ... failed: %s", try_scheme, host, exc
            )
            continue

    # Both schemes failed — reraise the last exception so the
    # caller sees a concrete error type.
    if isinstance(last_exception, aiohttp.ClientResponseError):
        raise last_exception
    if isinstance(last_exception, (aiohttp.ClientError, asyncio.TimeoutError, OSError)):
        raise last_exception  # type: ignore[misc]
    raise OSError(f"Cannot connect to printer at {host}") from last_exception


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
            except (aiohttp.ClientError, asyncio.TimeoutError, TimeoutError, OSError) as err:
                _LOGGER.debug("Connection error: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception(
                    "Unexpected error validating Epson printer at %s:%s",
                    host, port
                )
                errors["base"] = "unknown"
            else:
                try:
                    ipp_uuid = _lookup_ipp_identifier_by_host(self.hass, host)
                except Exception:
                    _LOGGER.exception("Failed to lookup IPP identifier for %s", host)
                    ipp_uuid = None
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
