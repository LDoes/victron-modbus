"""Read a Victron P1Link energy meter over Modbus.

Consumers construct :class:`P1Link` from a ``modbus_connection.ModbusUnit`` and
read its sub-systems (``meter``, ``phase_1``, ``phase_2``, ``phase_3``) as plain
Python attributes.
"""

from .device import P1Link, UpdateReport
from .meter import Meter
from .phase import Phase

__all__ = ["Meter", "P1Link", "Phase", "UpdateReport"]
