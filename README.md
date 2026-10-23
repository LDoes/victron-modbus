# `victron-modbus` Python library

[![CI](https://github.com/ldoes/victron-modbus/actions/workflows/ci.yml/badge.svg)](https://github.com/ldoes/victron-modbus/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/victron-modbus.svg)](https://pypi.org/project/victron-modbus/)
[![Python](https://img.shields.io/pypi/pyversions/victron-modbus.svg)](https://pypi.org/project/victron-modbus/)
[![License](https://img.shields.io/github/license/ldoes/victron-modbus.svg)](LICENSE)

`victron-modbus` is an asynchronous, transport-independent Python library for
reading Victron Energy devices over Modbus. It has no dependencies beyond
`modbus-connection`, so any Python application can use it.

## Purpose and scope

Victron products that speak Modbus share conventions: the same
identification registers (product ID at 0x1000, serial number at 0x1001),
data types and unavailable-value markers. Each product type still has its own
register map. `victron-modbus` follows that shape: **one library, one
sub-package per device type**, each with its own register map, data types,
scaling and units.

The library:

* contains the register map for each supported device type, grouped by
  sub-system. A component reads only the registers it declares, merging
  adjacent ones into one request. Registers outside the map can depend on the
  model and firmware, and a device may reject a whole request that touches
  one it lacks,
* does **not** create or own the Modbus transport. Applications using the
  library provide a [`modbus_connection.ModbusUnit`](https://github.com/home-assistant-libs/modbus-connection)
  and may use any backend supported by `modbus-connection` (pymodbus, tmodbus, ...).

An example script `script/query.py` shows how to build an application that
queries a supported device over Modbus/UDP or Modbus/TCP
(`python script/query.py 192.168.1.101`; the model is detected from the
product ID). It uses the tmodbus backend, so install it with
`pip install victron-modbus[cli]`.

## Supported devices

| Device | Product ID | Package | Registers read |
| :----- | :--------- | :------ | :------------- |
| Victron VM-3P75CT | `0xA1B1`, `0xA1B5` | `victron_modbus.vm_3p75ct` | total power/energy, PE-N voltage, frequency (also in 0.001 Hz, where the firmware has it), L1-L3 voltage/current/power/energy |
| Victron VM-3P5A | `0xA1B2` | `victron_modbus.vm_3p5a` | total power/energy, PE-N voltage, frequency (also in 0.001 Hz, where the firmware has it), L1-L3 voltage/current/power/energy |
| Victron P1Link | `0xC02F` | `victron_modbus.p1link` | total power/energy, L1-L3 voltage/current/power/energy |

The VM-3P75CT reads phase current from the 16-bit current registers (0x3041,
0x3049, 0x3051); the VM-3P5A and P1Link from the 32-bit ones (0x3058-0x305D).

Every device also exposes `info` (product ID, serial number, hardware
version) and `power` (total and per-phase active power, positive while
importing). Power changes from moment to moment and the rest slowly, so they
can be polled apart: `async_update(FAST_SUB_SYSTEMS)` reads only power, and
`async_update(SLOW_SUB_SYSTEMS)` the rest.

On the first poll the device also reads what doesn't change while it runs:

* `info`, unless `async_identify` already read it;
* the phase configuration, exposed as `connected_phases` (for example `(1,)`
  for a single-phase installation on L1). A meter that doesn't report it is
  taken as three-phase;
* whether the firmware has the 0.001 Hz frequency register. If it doesn't,
  `meter.frequency_fine` stays `None`.

After a firmware update or a wiring change, create a new device object to
pick up the change.

Other Victron products with a Modbus interface of their own, such as the EV
Charging Station, can be added as further sub-packages - see
[Adding a device](#adding-a-device) below. Contributions are welcome.

Products that only speak Modbus through a GX device (inverter/chargers,
battery monitors, solar chargers, ...) are out of scope: the GX device
publishes all of them over MQTT, which is the better interface to read them
through.

## Data provided by the library

For each supported device, `victron-modbus` provides typed attributes for
every register it reads, plus neutral datapoint metadata such as unit and
scale. The example uses the tmodbus backend; install it with
`pip install victron-modbus[cli]` (the library itself only needs
`modbus-connection`). See the VM-3P75CT example:

```python
from modbus_connection.tmodbus import connect_udp
from victron_modbus.vm_3p75ct import VM3P75CT

connection = await connect_udp("192.168.1.101")
try:
    device = VM3P75CT(connection.for_unit(1))
    report = await device.async_update()  # which sub-systems updated / failed
    print(device.info.serial_number, device.power.total, device.phase_1.voltage)
finally:
    await connection.close()
```

A reading the device reports as unavailable is `None`, for example the
voltage of a phase that isn't connected. Each sub-system that fails to read is
listed in `report.failed`; check the report before using its values.

The device sets a 1 s request timeout on the unit, unless the connection sets
its own. Modbus/UDP never retransmits a lost datagram, and a meter on Wi-Fi
can lose a good share of them, so a request that times out is repeated, three
attempts in all. That covers `async_identify`, the reads at setup and every
poll. A device that answers nothing therefore takes three timeouts (3 s) to
give up on. The bound is three timeouts per sub-system that is read: when
several sub-systems each time out in turn, the total is longer, and a caller
that polls them separately (for example fast and slow) gets the bound on each
poll. Refusals and dropped connections are not retried.

When the model is not known up front, `async_identify` reads the product ID
and returns the matching device object (or raises `UnsupportedDeviceError`):

```python
from victron_modbus import async_identify

device = await async_identify(unit)
```

## Adding a device

1. Create `src/victron_modbus/<device>/` with `Component` subclasses grouping
   its registers by sub-system (see `vm_3p75ct/meter.py` and `vm_3p75ct/phase.py`
   for examples), and a top-level device object in `device.py` following the
   [device-object pattern](https://home-assistant-libs.github.io/modbus-connection/patterns/library/).
   A three-phase energy meter only needs its register map: subclass the shared
   `EnergyMeter` from `_energy_meter.py` (see `vm_3p75ct/device.py`), which
   already handles polling, partial-failure reporting and raw diagnostics.
2. Export the device object and its components from `<device>/__init__.py`.
3. Add tests under `tests/` using the `modbus_connection` mock backend - no
   physical device or Modbus server required. For an energy meter, test its
   register map in `tests/test_<device>.py`, and add it to `DEVICES` in
   `tests/test_energy_meter.py`.
4. Add its product ID to `PRODUCTS` in `victron_modbus/__init__.py`, and the
   model to `DEVICES` in `script/query.py`.
5. Add the device to the table above.

## Testing and validation

The library ships with a test suite that runs entirely against the in-memory
mock backend provided by `modbus-connection`. No physical device or Modbus
server is required to run the tests.

## Documentation, development and contribution guidelines

* Each `Component` class documents the registers it reads via attribute
  docstrings.
* [`script/query.py`](script/query.py) - a standalone CLI that reads a real
  device once and prints every value; the fastest way to check physical
  hardware.
* Run `script/run_checks.sh` before committing: it checks formatting, lints,
  type-checks and runs the tests with coverage.
* Run `script/format_code.sh` to format the code.

Pull requests are welcome, including for new device types. Please open an
issue first for anything beyond a small fix, so the approach can be discussed
before you invest time in it.

## License

Apache-2.0. See [LICENSE](LICENSE).

