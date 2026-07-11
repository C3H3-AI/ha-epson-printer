"""Config flow for Epson Printer 鈥?discovery-first, manual IP fallback."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.zeroconf import async_get_async_instance
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from zeroconf import ServiceBrowser, ServiceStateChange

from .const import (
    CONF_IPP_UUID,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SCHEME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    HTTP_TIMEOUT_SECONDS,
    IPP_DOMAIN,
    MIN_SCAN_INTERVAL_SECONDS,
    PRODUCT_STATUS_PATHS,
    get_insecure_ssl_ctx,
)
from .parser import parse_product_status

_LOGGER = logging.getLogger(__name__)

_MDNS_SCAN_TIMEOUT = 3.0
_MDNS_SERVICE_TYPES = ("_ipps._tcp.local.", "_ipp._tcp.local.", "_printer._tcp.local.")

STEP_MANUAL_IP_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})


async def _try_fetch_status(
    hass: HomeAssistant, host: str, scheme: str, port: int
) -> dict[str, Any]:
    """Fetch product-status page, trying Advanced then Basic UI paths.

    Returns the parsed result from the first path that succeeds.
    Raises on total failure (all paths exhausted).
    """
    session = async_get_clientsession(hass)
    default_port = 80 if scheme == "http" else 443
    netloc = host if port == default_port else f"{host}:{port}"
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)

    last_error: Exception | None = None
    for path in PRODUCT_STATUS_PATHS:
        url = f"{scheme}://{netloc}{path}"
        kwargs: dict[str, Any] = {}
        if scheme == "https":
            kwargs["ssl_context"] = get_insecure_ssl_ctx()
        else:
            kwargs["ssl"] = False
        try:
            _LOGGER.debug("Fetching %s", url)
            async with session.get(url, timeout=timeout, **kwargs) as resp:
                _LOGGER.debug("Response %s from %s", resp.status, resp.url)
                resp.raise_for_status()
                text = await resp.text(encoding="utf-8", errors="replace")
            return parse_product_status(text)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            last_error = exc
            _LOGGER.debug("%s failed: %s", url, exc)
            continue

    if isinstance(last_error, aiohttp.ClientResponseError):
        raise last_error  # noqa: TRY201
    if isinstance(last_error, (aiohttp.ClientError, asyncio.TimeoutError, OSError)):
        raise last_error  # noqa: TRY201
    raise OSError(f"Cannot connect to printer at {host}") from last_error


def _lookup_ipp_identifier_by_host(hass: HomeAssistant, host: str) -> str | None:
    """Return IPP device UUID for merging with built-in IPP device."""
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
    """Validate host by trying requested scheme, then fallback scheme."""
    first_scheme = scheme
    fallback_scheme = "http" if scheme == "https" else "https"
    last_exception: Exception | None = None

    for try_scheme in (first_scheme, fallback_scheme):
        try:
            return await _try_fetch_status(hass, host, try_scheme, port)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            last_exception = exc
            _LOGGER.debug("%s://%s ... failed: %s", try_scheme, host, exc)
            continue

    if isinstance(last_exception, aiohttp.ClientResponseError):
        raise last_exception  # noqa: TRY201
    if isinstance(last_exception, (aiohttp.ClientError, asyncio.TimeoutError, OSError)):
        raise last_exception  # noqa: TRY201
    raise OSError(f"Cannot connect to printer at {host}") from last_exception


class EpsonPrinterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self._discovered: list[dict[str, Any]] = []

    # 鈹€鈹€ Steps 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: active mDNS scan, then selection or manual IP."""
        if user_input is not None:
            # Should not happen 鈥?this step has no schema of its own
            return await self.async_step_manual_ip()

        discovered = await self._scan_lan()
        if not discovered:
            return await self.async_step_manual_ip()

        self._discovered = discovered
        return await self.async_step_select_printer()

    async def async_step_select_printer(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2: pick a discovered printer, or fall back to manual IP."""
        errors: dict[str, str] = {}
        if user_input is not None:
            selection = user_input.get("printer", "")
            if selection == "__manual__":
                return await self.async_step_manual_ip()

            try:
                idx = int(selection)
                printer = self._discovered[idx]
            except (ValueError, IndexError):
                errors["base"] = "unknown"
            else:
                return await self._finalize_entry(
                    host=printer["host"],
                    title=printer["title"],
                    ipp_uuid=printer.get("uuid"),
                )

        options: dict[str, str] = {}
        for i, p in enumerate(self._discovered):
            label = f"{p['model']} ({p['host']})"
            options[str(i)] = label
        options["__manual__"] = "Enter IP address manually"

        schema = vol.Schema({vol.Required("printer"): vol.In(options)})
        return self.async_show_form(
            step_id="select_printer",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "count": str(len(self._discovered)),
            },
        )

    async def async_step_manual_ip(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Fallback step: manual IP address entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host: str = user_input[CONF_HOST].strip()
            try:
                identity = await _validate_host(self.hass, host, "http", 80)
            except aiohttp.ClientResponseError as err:
                _LOGGER.debug("HTTP error from printer: %s", err)
                errors["base"] = "cannot_connect"
            except (aiohttp.ClientError, asyncio.TimeoutError, TimeoutError, OSError) as err:
                _LOGGER.debug("Connection error: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error validating printer at %s", host)
                errors["base"] = "unknown"
            else:
                try:
                    ipp_uuid = _lookup_ipp_identifier_by_host(self.hass, host)
                except Exception:
                    _LOGGER.exception("Failed to lookup IPP identifier for %s", host)
                    ipp_uuid = None
                return await self._finalize_entry(
                    host=host,
                    title=identity.get("model") or f"Epson Printer ({host})",
                    ipp_uuid=ipp_uuid,
                )

        return self.async_show_form(
            step_id="manual_ip",
            data_schema=STEP_MANUAL_IP_SCHEMA,
            errors=errors,
        )

    async def async_step_zeroconf(
        self, discovery_info: dict[str, Any]
    ) -> FlowResult:
        """Handle zeroconf/mDNS passive discovery of Epson printers."""
        properties = discovery_info.get("properties", {})
        host = discovery_info.get("host", "").lower()

        mfg = (properties.get("usb_MFG") or "").upper()
        if "EPSON" not in mfg:
            return self.async_abort(reason="not_epson_printer")

        uuid_hex = (properties.get("UUID") or "").replace("-", "").lower()
        unique_id = uuid_hex or host
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        model_name = properties.get("ty") or ""
        title = model_name or f"Epson Printer ({host})"

        return self.async_create_entry(
            title=title,
            data={
                CONF_HOST: host,
                CONF_NAME: title,
                CONF_SCHEME: "http",
                CONF_PORT: 80,
                CONF_IPP_UUID: uuid_hex or None,
            },
        )

    # 鈹€鈹€ Internal helpers 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    async def _scan_lan(self) -> list[dict[str, Any]]:
        """Active mDNS scan for Epson printers (~3 s timeout)."""
        _LOGGER.debug("_scan_lan: starting mDNS scan")
        try:
            zc_instance = await async_get_async_instance(self.hass)
            _LOGGER.debug("_scan_lan: got zeroconf instance OK")
        except Exception as exc:
            _LOGGER.exception("_scan_lan: Failed to get zeroconf instance: %s", exc)
            return []

        zc = zc_instance.zeroconf
        found: list[dict[str, Any]] = []
        lock = threading.Lock()

        def _handler(
            _zc: Any,
            service_type: str,
            name: str,
            state_change: ServiceStateChange,
        ) -> None:
            if state_change != ServiceStateChange.Added:
                return
            info = _zc.get_service_info(service_type, name)
            if info is None:
                return
            props = {
                k.decode("utf-8", "replace"):
                    v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)
                for k, v in info.properties.items()
            }
            mfg = (props.get("usb_MFG") or "").upper()
            _LOGGER.debug("_scan_lan handler: type=%s name=%s mfg=%s props=%s",
                          service_type, name, mfg, props)
            if "EPSON" not in mfg:
                _LOGGER.debug("_scan_lan handler: NOT EPSON, skipping")
                return
            addrs = info.parsed_addresses()
            if not addrs:
                _LOGGER.debug("_scan_lan handler: no addresses for %s", name)
                return
            addr = addrs[0]
            _LOGGER.debug("_scan_lan handler: FOUND potential printer at %s", addr)
            with lock:
                if any(p["host"] == addr for p in found):
                    _LOGGER.debug("_scan_lan handler: duplicate %s, skip", addr)
                    return
                mdl = props.get("usb_MDL", "").replace("_", " ")
                uuid_raw = props.get("UUID", "")
                found.append({
                    "host": addr,
                    "model": mdl or props.get("ty", f"Epson ({addr})"),
                    "title": mdl or f"Epson Printer ({addr})",
                    "uuid": uuid_raw.replace("-", "").lower() if uuid_raw else None,
                })
                _LOGGER.debug("_scan_lan handler: ADDED %s (%s)", addr, mdl)

        _LOGGER.debug("_scan_lan: starting 3 ServiceBrowsers")
        browsers = [
            ServiceBrowser(zc, stype, handlers=[_handler])
            for stype in _MDNS_SERVICE_TYPES
        ]

        try:
            deadline = time.monotonic() + _MDNS_SCAN_TIMEOUT
            while time.monotonic() < deadline:
                with lock:
                    if found:
                        _LOGGER.debug("_scan_lan: found %d printer(s) early, extra wait", len(found))
                        break
                await asyncio.sleep(0.3)
            remaining = deadline - time.monotonic()
            _LOGGER.debug("_scan_lan: poll loop done, %s remaining, found=%d",
                          f"{remaining:.1f}s" if remaining > 0 else "timeout", len(found))
            # Brief extra wait for more printers in the same batch
            await asyncio.sleep(0.5)
            _LOGGER.debug("_scan_lan: final count=%d", len(found))
        finally:
            for b in browsers:
                b.cancel()
            _LOGGER.debug("_scan_lan: browsers cancelled")

        return found

    async def _finalize_entry(
        self, host: str, title: str, ipp_uuid: str | None
    ) -> FlowResult:
        """Create the config entry with derived unique ID and data."""
        unique_id = ipp_uuid or host.lower()
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        return self.async_create_entry(
            title=title,
            data={
                CONF_HOST: host,
                CONF_NAME: title,
                CONF_SCHEME: "http",
                CONF_PORT: 80,
                CONF_IPP_UUID: ipp_uuid,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return EpsonPrinterOptionsFlow()


class EpsonPrinterOptionsFlow(config_entries.OptionsFlow):
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
