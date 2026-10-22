#!/usr/bin/env python3
"""Query a Victron energy meter over Modbus and print every value.

Connects over Modbus/TCP or Modbus/UDP, reads the whole device once, and dumps
every sub-system's values to the terminal. Handy for checking a real VM-3P75CT,
VM-3P5A without any other software.

The library only needs the connection protocol; this script selects a concrete
backend, so install the ``cli`` extra first (``pip install victron-modbus[cli]``).
"""

from __future__ import annotations

import argparse
import asyncio

from modbus_connection import ModbusError
from modbus_connection.cli_helper import (
    CountingUnit,
    add_connection_args,
    connect_from_args,
    print_component,
)

from victron_modbus import UnsupportedDeviceError, async_identify
from victron_modbus.vm_3p5a import VM3P5A
from victron_modbus.vm_3p75ct import VM3P75CT

DEVICES = {"vm_3p75ct": VM3P75CT, "vm_3p5a": VM3P5A}

# (label, attribute name on the device) - the order in which sections are printed.
SECTIONS: list[tuple[str, str]] = [
    ("Info", "info"),
    ("Power", "power"),
    ("Meter", "meter"),
    ("Phase L1", "phase_1"),
    ("Phase L2", "phase_2"),
    ("Phase L3", "phase_3"),
]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_connection_args(parser, connections=(("udp", None), ("tcp", None)))
    parser.add_argument(
        "--model",
        choices=DEVICES,
        help="device model (default: detect from the product ID)",
    )
    parser.add_argument(
        "--unit", type=int, default=1, help="Modbus unit/slave id (default: 1)"
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    try:
        conn = await connect_from_args(args)
    except ModbusError as err:
        print(f"Could not connect: {err}")
        return 1

    counting = CountingUnit(conn.for_unit(args.unit))
    try:
        if args.model is None:
            device = await async_identify(counting)
        else:
            device = DEVICES[args.model](counting)
        await device.async_update()
    except (ModbusError, UnsupportedDeviceError) as err:
        print(f"Error reading device: {err}")
        return 1
    finally:
        await conn.close()

    for label, attr in SECTIONS:
        print()
        print_component(getattr(device, attr), title=label)
    print(f"\n{counting.reads} Modbus reads")
    return 0


def main() -> int:
    return asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
