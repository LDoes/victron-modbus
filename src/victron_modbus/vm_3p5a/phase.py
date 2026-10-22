"""One grid phase (L1, L2 or L3): voltage, current and energy.

Unlike the VM-3P75CT, the VM-3P5A uses industry-standard 5A CTs, with a larger
possible current range. Therefore it reports current on a wider 32-bit
"high range current" register, so ``current`` sits at a different address and
width than the VM-3P75CT variant.
"""

from modbus_connection.model import gauge, int32, uint32

from .._energy_meter import PhaseBlock
from ..sentinels import UNAVAILABLE_INT16, UNAVAILABLE_INT32, UNAVAILABLE_UINT32


class Phase(PhaseBlock):
    """A single grid phase, instantiated with ``index=1`` (L1), ``2`` (L2) or
    ``3`` (L3)."""

    voltage = gauge(0x3040, 0.01, nan=UNAVAILABLE_INT16, stride=8, unit="V")
    """Phase voltage."""

    current = int32(0x3058, scale=0.01, nan=UNAVAILABLE_INT32, stride=2, unit="A")
    """Phase current, read from the high range current register."""

    forward_energy = uint32(
        0x3042, scale=0.01, nan=UNAVAILABLE_UINT32, stride=8, unit="kWh"
    )
    """Energy imported from the grid on this phase."""

    reverse_energy = uint32(
        0x3044, scale=0.01, nan=UNAVAILABLE_UINT32, stride=8, unit="kWh"
    )
    """Energy exported to the grid on this phase."""
