"""Read Victron Energy Modbus devices.

This package covers Victron's family of Modbus/TCP and Modbus/UDP devices,
following Victron's own unified Modbus register-list convention. Each device
type lives in its own sub-package with a top-level device object, e.g.:

    from victron_modbus.vm_3p75ct import VM3P75CT

(the device classes are also importable from this package directly), or,
when the model is not known up front, let the device say what it is:

    device = await async_identify(unit)

Currently supported:

* :mod:`victron_modbus.vm_3p75ct` - the VM-3P75CT energy meter (CT-clamp
  current sensing).
* :mod:`victron_modbus.vm_3p5a` - the VM-3P5A energy meter (current sensing
  through standard 5 A CTs).

Other Victron products with a Modbus interface of their own can be added as
further sub-packages without affecting existing ones.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from modbus_connection.model import UpdateReport

from ._energy_meter import (
    ALL_PHASES,
    FAST_SUB_SYSTEMS,
    SLOW_SUB_SYSTEMS,
    SUB_SYSTEMS,
    EnergyMeter,
    Info,
    Power,
    configure_unit,
    retry_lost,
)
from .vm_3p5a import VM3P5A
from .vm_3p75ct import VM3P75CT

if TYPE_CHECKING:
    from modbus_connection import ModbusUnit

__all__ = [
    "ALL_PHASES",
    "FAST_SUB_SYSTEMS",
    "PRODUCTS",
    "SLOW_SUB_SYSTEMS",
    "SUB_SYSTEMS",
    "VM3P5A",
    "VM3P75CT",
    "EnergyMeter",
    "Info",
    "Power",
    "UnsupportedDeviceError",
    "UpdateReport",
    "async_identify",
]

# Victron product ID (register 0x1000) -> device class. A new hardware revision
# with the same register map gets its own product ID, but the same class.
PRODUCTS: dict[int, type[VM3P75CT | VM3P5A]] = {
    0xA1B1: VM3P75CT,
    0xA1B5: VM3P75CT,  # newer hardware revision
    0xA1B2: VM3P5A,
}


class UnsupportedDeviceError(Exception):
    """The device answered, but with a product ID this library does not know."""

    def __init__(self, product_id: int | None) -> None:
        super().__init__(
            "unknown product ID"
            if product_id is None
            else f"unsupported product ID 0x{product_id:04X}"
        )
        self.product_id = product_id


async def async_identify(unit: ModbusUnit) -> VM3P75CT | VM3P5A:
    """Read the product ID and return the matching device object.

    The identification it read is kept, so ``device.info`` (including the
    serial number) is available right away without reading it again.

    Raises ``UnsupportedDeviceError`` for a product this library does not
    cover, and ``ModbusError`` if the device cannot be read.
    """
    configure_unit(unit)
    info = Info(unit)
    await retry_lost(info.async_update)
    device_class = PRODUCTS.get(info.product_id or -1)
    if device_class is None:
        raise UnsupportedDeviceError(info.product_id)
    return device_class(unit, info=info)
