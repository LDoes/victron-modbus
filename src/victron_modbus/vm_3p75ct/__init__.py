"""Read a Victron VM-3P75CT energy meter over Modbus.

The VM-3P75CT senses phase current through external CT clamps (up to 75A per
phase). Consumers construct :class:`VM3P75CT` from a
``modbus_connection.ModbusUnit`` and read its sub-systems (``meter``,
``phase_1``, ``phase_2``, ``phase_3``) as plain Python attributes.
"""

from .device import VM3P75CT, UpdateReport
from .meter import Meter
from .phase import Phase

__all__ = ["Meter", "Phase", "UpdateReport", "VM3P75CT"]
