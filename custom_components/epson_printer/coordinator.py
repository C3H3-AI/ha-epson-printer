"""DataUpdateCoordinator: fetches HTML status pages (ink/pages) + IPP state.

URL fallback: tries Advanced UI paths first, falls back to Basic UI paths.
Supports printers with /ADVANCED/INFO_PRTINFO/TOP (fieldset) and
/HTML/TOP/PRTINFO.HTML (li.tank) web interfaces.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    COMMON_PATHS,
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SCHEME,
    DATA_IPP,
    DATA_MAINTENANCE,
    DATA_PRODUCT,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    HTTP_TIMEOUT_SECONDS,
    LANG_ENGLISH,
    MAINTENANCE_PATHS,
    MIN_SCAN_INTERVAL_SECONDS,
    PRODUCT_STATUS_PATHS,
    get_insecure_ssl_ctx,
)
from .ipp_client import EpsonIppClient
from .parser import detect_page_format, parse_maintenance, parse_product_status

_LOGGER = logging.getLogger(__name__)


class EpsonPrinterCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls HTML status pages + IPP attributes, merges into one dict."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        scan_interval = self._scan_interval_from_options(entry)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({entry.data[CONF_HOST]})",
            update_interval=scan_interval,
        )
        self.entry = entry
        self._session = async_get_clientsession(hass)
        self._language_set = False
        self._page_format: str | None = None
        host = entry.data[CONF_HOST]
        self._ipp_client = EpsonIppClient(host, 631)

    @staticmethod
    def _scan_interval_from_options(entry: ConfigEntry) -> timedelta:
        seconds = entry.options.get(CONF_SCAN_INTERVAL)
        if not seconds:
            return DEFAULT_SCAN_INTERVAL
        try:
            value = int(seconds)
        except (TypeError, ValueError):
            return DEFAULT_SCAN_INTERVAL
        return timedelta(seconds=max(MIN_SCAN_INTERVAL_SECONDS, value))

    @property
    def base_url(self) -> str:
        scheme = self.entry.data.get(CONF_SCHEME, "https")
        host = self.entry.data[CONF_HOST]
        port = int(self.entry.data.get(CONF_PORT, DEFAULT_PORT))
        default_port = 80 if scheme == "http" else 443
        if port == default_port:
            return f"{scheme}://{host}"
        return f"{scheme}://{host}:{port}"

    def _build_url(self, path: str) -> str:
        """Build an absolute URL for a given path."""
        return f"{self.base_url}{path}"

    async def async_config_entry_first_refresh(self) -> None:
        """First refresh: detect page format, then do normal refresh."""
        try:
            first_path = PRODUCT_STATUS_PATHS[0]
            html = await self._fetch_single(first_path)
            self._page_format = detect_page_format(html)
            _LOGGER.info("Detected page format: %s (via %s)", self._page_format, first_path)
        except Exception as exc:
            _LOGGER.debug("Advanced UI probe failed: %s. Trying basic...", exc)
            try:
                basic_path = PRODUCT_STATUS_PATHS[1]
                html = await self._fetch_single(basic_path)
                self._page_format = detect_page_format(html)
                _LOGGER.info("Detected page format: %s (via %s)", self._page_format, basic_path)
            except Exception as exc2:
                _LOGGER.warning("Could not detect page format: %s. Falling back to advanced.", exc2)
                self._page_format = "advanced"
        await super().async_config_entry_first_refresh()

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch HTML pages + IPP attributes in parallel."""
        if not self._language_set:
            try:
                await self._set_language_english()
            except Exception as err:
                _LOGGER.debug("Could not switch printer UI to English: %s", err)
            else:
                self._language_set = True

        try:
            maintenance_task = self._fetch_html(MAINTENANCE_PATHS)
            product_task = self._fetch_html(PRODUCT_STATUS_PATHS)
            ipp_task = self._fetch_ipp()
            maintenance_html, product_html, ipp_data = await asyncio.gather(
                maintenance_task, product_task, ipp_task,
            )

            maintenance = await self.hass.async_add_executor_job(
                parse_maintenance, maintenance_html
            )
            product = await self.hass.async_add_executor_job(
                parse_product_status, product_html
            )
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Error talking to printer: {err}") from err
        except asyncio.TimeoutError as err:
            raise UpdateFailed("Timeout while fetching printer data") from err

        return {
            DATA_MAINTENANCE: maintenance,
            DATA_PRODUCT: product,
            DATA_IPP: ipp_data or {},
        }

    async def _fetch_single(self, path: str) -> str:
        """Fetch a single HTML page from the printer. Raises on error."""
        url = self._build_url(path)
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
        kwargs: dict[str, Any] = {}
        if self.base_url.startswith("https"):
            kwargs["ssl_context"] = get_insecure_ssl_ctx()
        else:
            kwargs["ssl"] = False
        async with self._session.get(url, timeout=timeout, **kwargs) as resp:
            resp.raise_for_status()
            return await resp.text(encoding="utf-8", errors="replace")

    async def _fetch_html(self, paths: tuple[str, ...]) -> str:
        """Fetch HTML, trying each path in order until one succeeds.

        Returns the first successful response. If all paths fail,
        returns empty string (non-fatal for maintenance pages).
        """
        errors: list[str] = []
        for path in paths:
            try:
                return await self._fetch_single(path)
            except (aiohttp.ClientResponseError, aiohttp.ClientError, asyncio.TimeoutError) as err:
                _LOGGER.debug("Fetch %s failed: %s", path, err)
                errors.append(f"{path}: {err}")
                continue

        if paths == PRODUCT_STATUS_PATHS:
            raise UpdateFailed(
                f"Could not reach printer at any known path: {'; '.join(errors)}"
            )
        _LOGGER.debug("Maintenance page unavailable (all paths failed): %s", errors)
        return "<html></html>"

    async def _fetch_ipp(self) -> dict:
        try:
            return await self.hass.async_add_executor_job(
                self._ipp_client.get_printer_attributes
            )
        except OSError as err:
            _LOGGER.debug("IPP fetch failed (non-fatal): %s", err)
            return {}

    async def _set_language_english(self) -> None:
        """Set printer language to English via POST.

        Tries advanced COMMON path first, then basic if that fails.
        Basic UI may not have a language endpoint; this is best-effort.
        """
        for path in COMMON_PATHS:
            try:
                url = self._build_url(path)
                timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
                kwargs: dict[str, Any] = {"data": {"SEL_LANGA": LANG_ENGLISH}, "timeout": timeout}
                if self.base_url.startswith("https"):
                    kwargs["ssl_context"] = get_insecure_ssl_ctx()
                else:
                    kwargs["ssl"] = False
                async with self._session.post(url, **kwargs) as resp:
                    resp.raise_for_status()
                    _LOGGER.debug("Language set to English via %s", path)
                    return
            except Exception as err:
                _LOGGER.debug("Language set via %s failed: %s", path, err)
                continue
        _LOGGER.debug("Could not set language to English (no path worked)")
