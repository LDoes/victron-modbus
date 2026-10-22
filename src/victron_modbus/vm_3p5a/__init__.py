"""Read a Victron VM-3P5A energy meter over Modbus.

The VM-3P5A senses phase current using industry-standard 5A CTs and a
wider-range register. Consumers construct :class:`VM3P5A` from a
``modbus_connection.ModbusUnit`` and read its sub-systems (``meter``,
``phase_1``, ``phase_2``, ``phase_3``) as plain Python attributes.
"""

from .device import VM3P5A, UpdateReport
from .meter import Meter
from .phase import Phase

__all__ = ["Meter", "Phase", "UpdateReport", "VM3P5A"]
