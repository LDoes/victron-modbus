"""One grid phase (L1, L2 or L3): voltage, current and energy.

Power is read apart from the other phase readings, as part of the device's
``power`` sub-system, so it can be polled more often.
"""

from modbus_connection.model import gauge, uint32

from .._energy_meter import PhaseBlock
from ..sentinels import UNAVAILABLE_INT16, UNAVAILABLE_UINT32


class Phase(PhaseBlock):
    """A single grid phase, instantiated with ``index=1`` (L1), ``2`` (L2) or
    ``3`` (L3)."""

    voltage = gauge(0x3040, 0.01, nan=UNAVAILABLE_INT16, stride=8, unit="V")
    """Phase voltage."""

    current = gauge(0x3041, 0.01, nan=UNAVAILABLE_INT16, stride=8, unit="A")
    """Phase current, sensed through the external CT clamp."""

    forward_energy = uint32(
        0x3042, scale=0.01, nan=UNAVAILABLE_UINT32, stride=8, unit="kWh"
    )
    """Energy imported from the grid on this phase."""

    reverse_energy = uint32(
        0x3044, scale=0.01, nan=UNAVAILABLE_UINT32, stride=8, unit="kWh"
    )
    """Energy exported to the grid on this phase."""
