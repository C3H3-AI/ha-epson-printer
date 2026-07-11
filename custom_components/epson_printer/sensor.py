"""Sensor platform for Epson Printer — HTML-scraped ink/pages + IPP state."""

from __future__ import annotations

import logging

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    PERCENTAGE,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_IPP_UUID,
    DATA_IPP,
    DATA_MAINTENANCE,
    DATA_PRODUCT,
    DOMAIN,
    FUNCTION_KEYS,
    INK_COLORS,
    IPP_DOMAIN,
    KEY_EPSON_CONNECT_STATUS,
    KEY_FIRMWARE,
    KEY_FIRST_PRINT_DATE,
    KEY_INK_LEVELS,
    KEY_MAC_ADDRESS,
    KEY_MAINTENANCE_BOX,
    KEY_MODEL,
    KEY_PAGES_BW,
    KEY_PAGES_BY_FUNCTION,
    KEY_PAGES_COLOR,
    KEY_PAGES_DUPLEX,
    KEY_PAGES_SIMPLEX,
    KEY_PAGES_TOTAL,
    KEY_PRINTER_STATUS,
    KEY_SCANNER_STATUS,
    KEY_SERIAL,
    MANUFACTURER,
)
from .coordinator import EpsonPrinterCoordinator

_LOGGER = logging.getLogger(__name__)

UNIT_PAGES = "pages"


@dataclass(frozen=True, kw_only=True)
class EpsonSensorDescription(SensorEntityDescription):
    """Sensor description with a callable value extractor."""

    value_fn: Callable[[Mapping[str, Any]], Any]


# ── Helpers ────────────────────────────────────────────────────────────────

def _maintenance(data: Mapping[str, Any], key: str) -> Any:
    return data.get(DATA_MAINTENANCE, {}).get(key)


def _product(data: Mapping[str, Any], key: str) -> Any:
    return data.get(DATA_PRODUCT, {}).get(key)


def _function_count(data: Mapping[str, Any], key: str) -> Any:
    return data.get(DATA_MAINTENANCE, {}).get(KEY_PAGES_BY_FUNCTION, {}).get(key)


def _ink_level(data: Mapping[str, Any], colour: str) -> Any:
    return data.get(DATA_PRODUCT, {}).get(KEY_INK_LEVELS, {}).get(colour)


def _ipp_attr(data: Mapping[str, Any], attr: str) -> Any:
    return data.get(DATA_IPP, {}).get(attr)


def _parse_date(val: Any) -> date | None:
    """Convert a date string to a date object."""
    if val is None:
        return None
    try:
        parts = str(val).split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError, TypeError):
        return None


def _icon_for_function(name: str) -> str:
    """Return an appropriate icon for a printer function key."""
    icons = {
        "print": "mdi:printer",
        "copy": "mdi:content-copy",
        "scan": "mdi:scanner",
        "fax": "mdi:fax",
    }
    return icons.get(name, "mdi:file-document")


# ── Sensor descriptions ────────────────────────────────────────────────────

PAGE_DESCRIPTIONS: tuple[EpsonSensorDescription, ...] = (
    EpsonSensorDescription(
        key=KEY_PAGES_TOTAL,
        translation_key="pages_total",
        icon="mdi:file-document-multiple",
        native_unit_of_measurement=UNIT_PAGES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: _maintenance(d, KEY_PAGES_TOTAL),
    ),
    EpsonSensorDescription(
        key=KEY_PAGES_BW,
        translation_key="pages_bw",
        icon="mdi:file-document-outline",
        native_unit_of_measurement=UNIT_PAGES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _maintenance(d, KEY_PAGES_BW),
    ),
    EpsonSensorDescription(
        key=KEY_PAGES_COLOR,
        translation_key="pages_color",
        icon="mdi:palette",
        native_unit_of_measurement=UNIT_PAGES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _maintenance(d, KEY_PAGES_COLOR),
    ),
    EpsonSensorDescription(
        key=KEY_PAGES_SIMPLEX,
        translation_key="pages_simplex",
        icon="mdi:file-document-outline",
        native_unit_of_measurement=UNIT_PAGES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _maintenance(d, KEY_PAGES_SIMPLEX),
    ),
    EpsonSensorDescription(
        key=KEY_PAGES_DUPLEX,
        translation_key="pages_duplex",
        icon="mdi:file-compare",
        native_unit_of_measurement=UNIT_PAGES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _maintenance(d, KEY_PAGES_DUPLEX),
    ),
)

FUNCTION_DESCRIPTIONS: tuple[EpsonSensorDescription, ...] = tuple(
    EpsonSensorDescription(
        key=f"function_{name}",
        translation_key=f"function_{name}",
        icon=_icon_for_function(name),
        native_unit_of_measurement=UNIT_PAGES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        value_fn=lambda d, name=name: _function_count(d, name),
    )
    for name in FUNCTION_KEYS
)

DIAGNOSTIC_DESCRIPTIONS: tuple[EpsonSensorDescription, ...] = (
    EpsonSensorDescription(
        key=KEY_PRINTER_STATUS,
        translation_key="printer_status",
        icon="mdi:printer-check",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _product(d, KEY_PRINTER_STATUS),
    ),
    EpsonSensorDescription(
        key=KEY_SCANNER_STATUS,
        translation_key="scanner_status",
        icon="mdi:scanner",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _product(d, KEY_SCANNER_STATUS),
    ),
    EpsonSensorDescription(
        key=KEY_MAINTENANCE_BOX,
        translation_key="maintenance_box",
        icon="mdi:broom",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _product(d, KEY_MAINTENANCE_BOX),
    ),
    EpsonSensorDescription(
        key=KEY_EPSON_CONNECT_STATUS,
        translation_key="epson_connect_status",
        icon="mdi:wifi-check",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _product(d, KEY_EPSON_CONNECT_STATUS),
    ),
    EpsonSensorDescription(
        key=KEY_FIRST_PRINT_DATE,
        translation_key="first_print_date",
        icon="mdi:calendar",
        device_class=SensorDeviceClass.DATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _parse_date(_maintenance(d, KEY_FIRST_PRINT_DATE)),
    ),
    EpsonSensorDescription(
        key=KEY_FIRMWARE,
        translation_key="firmware",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _product(d, KEY_FIRMWARE),
    ),
)

# IPP-based sensors (real-time printer state)
IPP_DESCRIPTIONS: tuple[EpsonSensorDescription, ...] = (
    EpsonSensorDescription(
        key="ipp_state",
        translation_key="ipp_state",
        icon="mdi:printer-eye",
        value_fn=lambda d: _format_printer_state(_ipp_attr(d, "printer-state")),
    ),
    EpsonSensorDescription(
        key="ipp_state_reason",
        translation_key="ipp_state_reason",
        icon="mdi:information-outline",
        entity_registry_enabled_default=False,
        value_fn=lambda d: _ipp_attr(d, "printer-state-reasons"),
    ),
    EpsonSensorDescription(
        key="ipp_uptime",
        translation_key="ipp_uptime",
        icon="mdi:clock-outline",
        native_unit_of_measurement="s",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _ipp_attr(d, "printer-up-time"),
    ),
    EpsonSensorDescription(
        key="ipp_model",
        translation_key="ipp_model",
        icon="mdi:label-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _ipp_attr(d, "printer-make-and-model"),
    ),
    EpsonSensorDescription(
        key="ipp_queued_jobs",
        translation_key="ipp_queued_jobs",
        icon="mdi:format-list-numbered",
        native_unit_of_measurement="jobs",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _ipp_attr(d, "queued-job-count"),
    ),
    EpsonSensorDescription(
        key="ipp_accepting_jobs",
        translation_key="ipp_accepting_jobs",
        icon="mdi:check-circle-outline",
        value_fn=lambda d: "Yes" if _ipp_attr(d, "printer-is-accepting-jobs") else "No",
    ),
    EpsonSensorDescription(
        key="ipp_pages_per_minute",
        translation_key="ipp_pages_per_minute",
        icon="mdi:speedometer",
        entity_registry_enabled_default=False,
        value_fn=lambda d: _ipp_attr(d, "pages-per-minute"),
    ),
)


def _format_printer_state(val: Any) -> str | None:
    states = {3: "idle", 4: "printing", 5: "stopped"}
    if val is None:
        return None
    return states.get(val, f"unknown ({val})")


# ── Platform setup ─────────────────────────────────────────────────────────

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Epson Printer sensors from a config entry."""
    _LOGGER.debug("sensor.async_setup_entry called for %s", entry.entry_id)
    coordinator: EpsonPrinterCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Detect which ink colours are actually available on this printer
    available_inks: set[str] = set()
    if coordinator.data and DATA_PRODUCT in coordinator.data:
        inks = coordinator.data[DATA_PRODUCT].get(KEY_INK_LEVELS, {})
        available_inks = set(inks.keys())
        _LOGGER.debug("Available inks: %s, coordinator.data has keys: %s", available_inks, list(coordinator.data.keys()))
    else:
        _LOGGER.debug("coordinator.data is %s, DATA_PRODUCT in data: %s", coordinator.data is None, DATA_PRODUCT in (coordinator.data or {}))

    ink_descriptions = tuple(
        EpsonSensorDescription(
            key=f"ink_{colour.lower()}",
            translation_key=f"ink_{colour.lower()}",
            icon="mdi:water",
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            entity_registry_enabled_default=True,
            value_fn=lambda d, colour=colour: _ink_level(d, colour),
        )
        for colour in INK_COLORS
        if colour in available_inks
    )

    data = coordinator.data or {}

    descriptions: list[EpsonSensorDescription] = list(PAGE_DESCRIPTIONS)

    # Only expose function counters the printer actually reports. Many
    # models publish only a subset (e.g. copy/scan/fax but no print counts),
    # so creating the rest just yields permanently-unavailable dead entities.
    for desc in FUNCTION_DESCRIPTIONS:
        fname = desc.key.split("_", 1)[1]
        if _function_count(data, fname) is not None:
            descriptions.append(desc)

    descriptions += list(ink_descriptions)

    # Only expose diagnostic sensors that have a value on this printer
    # (e.g. scanner_status / maintenance_box are absent on many models).
    for desc in DIAGNOSTIC_DESCRIPTIONS:
        if desc.value_fn(data) is not None:
            descriptions.append(desc)

    descriptions += list(IPP_DESCRIPTIONS)

    async_add_entities(
        EpsonPrinterSensor(coordinator, description) for description in descriptions
    )


# ── Sensor entity ──────────────────────────────────────────────────────────

class EpsonPrinterSensor(CoordinatorEntity[EpsonPrinterCoordinator], SensorEntity):
    """Generic sensor backed by ``EpsonSensorDescription.value_fn``."""

    entity_description: EpsonSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EpsonPrinterCoordinator,
        description: EpsonSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{self._device_unique_id}_{description.key}"

    @property
    def _device_unique_id(self) -> str:
        product = (
            self.coordinator.data.get(DATA_PRODUCT, {})
            if self.coordinator.data
            else {}
        )
        ipp_uuid = self.coordinator.entry.data.get(CONF_IPP_UUID)
        if ipp_uuid:
            return ipp_uuid
        serial = product.get(KEY_SERIAL)
        if serial:
            return serial
        return self.coordinator.entry.data[CONF_HOST].lower()

    @property
    def device_info(self) -> DeviceInfo:
        product = (
            self.coordinator.data.get(DATA_PRODUCT, {})
            if self.coordinator.data
            else {}
        )
        serial = product.get(KEY_SERIAL)
        ipp_uuid = self.coordinator.entry.data.get(CONF_IPP_UUID)
        mac = product.get(KEY_MAC_ADDRESS)

        identifiers: set[tuple[str, str]]
        if ipp_uuid:
            identifiers = {(IPP_DOMAIN, ipp_uuid)}
        else:
            identifiers = {(DOMAIN, self._device_unique_id)}

        connections: set[tuple[str, str]] = set()
        if mac:
            connections.add(("mac", mac))

        return DeviceInfo(
            identifiers=identifiers,
            manufacturer=MANUFACTURER,
            model=product.get(KEY_MODEL),
            name=self.coordinator.entry.data.get(CONF_NAME)
            or product.get(KEY_MODEL)
            or self.coordinator.entry.data[CONF_HOST],
            sw_version=product.get(KEY_FIRMWARE),
            serial_number=serial,
            connections=connections,
            configuration_url=f"{self.coordinator.base_url}/",
        )

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def icon(self) -> str | None:
        """Return the icon."""
        if self.entity_description and self.entity_description.icon:
            return self.entity_description.icon
        return super().icon

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None
