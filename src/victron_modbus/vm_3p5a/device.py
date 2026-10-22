"""The top-level VM-3P5A device object."""

from __future__ import annotations

from typing import TYPE_CHECKING

from modbus_connection.model import UpdateReport

from .._energy_meter import EnergyMeter, Info
from .meter import Meter
from .phase import Phase

if TYPE_CHECKING:
    from modbus_connection import ModbusUnit

__all__ = ["VM3P5A", "UpdateReport"]


class VM3P5A(EnergyMeter[Meter, Phase]):
    """A Victron VM-3P5A energy meter reached through a ``ModbusUnit``."""

    def __init__(self, unit: ModbusUnit, *, info: Info | None = None) -> None:
        """Wrap ``unit``; pass ``info`` if the identification was read already."""
        super().__init__(unit, Meter, Phase, info=info)
