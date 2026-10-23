"""Grid connection totals: energy counters."""

from modbus_connection.model import uint32

from .._energy_meter import RegisterBlock
from ..sentinels import UNAVAILABLE_UINT32


class Meter(RegisterBlock):
    """Totals across all three phases, read from the holding registers."""

    total_forward_energy = uint32(
        0x3034, scale=0.01, nan=UNAVAILABLE_UINT32, unit="kWh"
    )
    """Total energy imported from the grid."""

    total_reverse_energy = uint32(
        0x3036, scale=0.01, nan=UNAVAILABLE_UINT32, unit="kWh"
    )
    """Total energy exported to the grid."""
