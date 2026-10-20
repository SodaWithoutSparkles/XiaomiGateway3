#!/usr/bin/env python3
"""
Generate a proposed DEVICES entry for a MIoT device.

Usage:
    python3 generate_device.py https://home.miot-spec.com/spec/xiaomi.switch.2wpro2
    python3 generate_device.py xiaomi.switch.2wpro2
    python3 generate_device.py "references/小米智能开关Pro（双开）(...).htm"

The script prints a ready-to-paste block for
`custom_components/xiaomi_gateway3/core/devices.py`. It is a DRAFT:
market names, hardware models and a few domain choices still need a
human decision, the output says so inline with TODO comments.

Data sources:
  - https://home.miot-spec.com/spec/<model> - service tree with iids,
    formats, value-lists and English descriptions
  - https://home.miot-spec.com/p/<model>    - product id (pdid), brand,
    protocol (BLE / Mesh)
  - https://miot-spec.org/miot-spec-v2/instance?type=<urn> - same spec
    as JSON, used when a miot-spec.org link is pasted

Only stdlib is used, so the script runs without Home Assistant installed.
"""

import argparse
import ast
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request

WEB = "https://home.miot-spec.com"
API = "https://miot-spec.org/miot-spec-v2"
DEVICES_PY = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "custom_components",
    "xiaomi_gateway3",
    "core",
    "devices.py",
)

TIMEOUT = 30
UA = "Mozilla/5.0 (compatible; XiaomiGateway3 device spec generator)"


# --- property conventions -------------------------------------------------
#
# MIoT property type -> (attribute name, hass domain).
#
# The attribute name is not cosmetic: `hass/entity_description.py` maps it
# to a device class, unit and category, and `device_trigger.py` builds the
# automation triggers from it. Unknown types fall back to a generic rule
# and are marked with a TODO comment in the output.

PROPERTY_MAP = {
    "fault": ("fault", "sensor"),
    "anti-flicker": ("anti_flicker", "switch"),
    "wiring-method": ("wiring_method", "sensor"),
    "temperature": ("temperature", "sensor"),
    "humidity": ("humidity", "sensor"),
    "battery-level": ("battery", "sensor"),
    "voltage": ("battery_voltage", "sensor"),
    "power-consumption": ("energy", "sensor"),
    "electric-power": ("power", "sensor"),
    "power-consumption-accumulation-way": (
        "power_consumption_accumulation_way",
        "binary_sensor",
    ),
    "illuminance": ("illuminance", "sensor"),
    "pm2.5": ("pm25", "sensor"),
    "co2": ("co_two", "sensor"),
    "tvoc": ("tvoc", "sensor"),
    "formaldehyde": ("formaldehyde", "sensor"),
    "brightness": ("brightness", "light"),
    "vol": ("voltage", "sensor"),
    "default-power-on-state": ("power_on_state", "select"),
    "power-on-state": ("power_on_state", "select"),
    "contact-state": ("contact", "binary_sensor"),
    "water-leak": ("water_leak", "binary_sensor"),
    "motion-detected": ("motion", "binary_sensor"),
    "occupancy": ("occupancy", "binary_sensor"),
    "smoke-state": ("smoke", "binary_sensor"),
    "gas-alarm": ("gas", "binary_sensor"),
    "child-lock": ("child_lock", "switch"),
    "mute": ("mute", "switch"),
}

# service type -> (attribute name, hass domain) for the "on" property
ON_MAP = {
    "switch": ("switch", "switch"),
    "outlet": ("outlet", "switch"),
    "indicator-light": ("indicator_light", "switch"),
    "light": ("light", "light"),
    "fan": ("fan", "switch"),
    "heater": ("heater", "switch"),
}

# unit -> (attribute name, hass domain) for numeric properties without a
# value list (the unit is lowercased before the lookup)
UNIT_MAP = {
    "celsius": ("temperature", "sensor"),
    "watt": ("power", "sensor"),
    "kwh": ("energy", "sensor"),
    "percentage": ("battery", "sensor"),
}

# event type -> button action constant
EVENT_MAP = {
    "click": "SINGLE",
    "double-click": "DOUBLE",
    "long-press": "HOLD",
    "triple-click": "TRIPLE",
}

# extra notes for known property types
NOTES = {
    "vol": "unit is mV - the repo has sensor.voltage (V) and sensor.battery_voltage (mV)",
    "power-consumption-accumulation-way": "read only diagnostic toggle",
    "wiring-method": "not reported by some firmwares, check on a real device",
}


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def fetch_page_props(url: str) -> dict:
    """Parse the JSON payload embedded into a home.miot-spec.com page."""
    html = fetch(url).decode("utf-8", errors="replace")
    match = re.search(
        r'<script data-page="app" type="application/json">(.*?)</script>', html, re.S
    )
    if not match:
        raise ValueError(f"Can't find spec data in {url}")
    return json.loads(match.group(1))["props"]


def fetch_instance(urn: str) -> dict:
    return json.loads(fetch(f"{API}/instance?type={urn}").decode("utf-8"))


def fetch_instances() -> list:
    """Download the list of all miot instances (cached for a day)."""
    cache = os.path.join(tempfile.gettempdir(), "miot-spec-instances.json")
    if os.path.isfile(cache):
        if time.time() - os.path.getmtime(cache) < 86400:
            with open(cache, encoding="utf-8") as f:
                return json.load(f)["instances"]
    print("downloading the list of miot instances...", file=sys.stderr)
    data = fetch(f"{API}/instances?status=all")
    with open(cache, "wb") as f:
        f.write(data)
    return json.loads(data)["instances"]


def model_from_urn(urn: str) -> str | None:
    """Find the miot model name for a spec urn."""
    for instance in fetch_instances():
        if instance.get("type") == urn:
            return instance.get("model")
    return None


def urn_from_model(model: str) -> str | None:
    """Find the spec urn for a miot model name."""
    for instance in fetch_instances():
        if instance.get("model") == model:
            return instance.get("type")
    return None


def pdid_from_url(url: str) -> int | None:
    match = re.search(r"iotweb-product-center/(\d+)\.png", url or "")
    return int(match.group(1)) if match else None


def model_from_source(source: str) -> str | None:
    """Extract the miot model name from a link or a plain model name."""
    match = re.search(r"home\.miot-spec\.com/(?:spec|p|s)/([^/?#]+)", source)
    if match:
        return match.group(1)
    match = re.search(r"miot-spec\.org/miot-spec-v2/instance\?type=([^&]+)", source)
    if match:
        return None  # resolved later from the instance json
    if re.match(r"^[\w.-]+\.[\w.-]+$", source):
        return source
    return None


class Device:
    """Everything the generator knows about one device."""

    def __init__(self):
        self.model = None
        self.pdid = None
        self.name = None  # market name (Chinese)
        self.brand = None
        self.protocol = None
        self.urn = None
        self.category = None  # switch, outlet, light, ...
        self.services = []

    @property
    def section(self) -> str:
        if self.protocol and "mesh" in self.protocol.lower():
            return "Mesh"
        if self.protocol and "ble" in self.protocol.lower():
            return "BLE"
        return "Mesh"

    def set_urn(self, urn: str) -> None:
        self.urn = urn
        # urn:miot-spec-v2:device:<category>:<model>:<version>:<type>
        parts = (urn or "").split(":")
        if len(parts) > 3 and parts[2] == "device":
            self.category = parts[3]


def load_device(source: str, offline: bool = False) -> Device:
    """Resolve any supported source into a Device with a service tree."""
    device = Device()

    # 1. local html file
    if os.path.isfile(source):
        with open(source, encoding="utf-8", errors="replace") as f:
            html = f.read()
        match = re.search(
            r'<script data-page="app" type="application/json">(.*?)</script>', html, re.S
        )
        if not match:
            raise ValueError("Can't find spec data in the local file")
        props = json.loads(match.group(1))["props"]
        device.model = props["spec"]["model"]
        device.set_urn(props["spec"]["urn"])
        device.services = props["tree"]["services"]
        product = props.get("product", {})
        device.name = product.get("name")
        device.pdid = pdid_from_url(product.get("icon", ""))
        if not offline:
            _fill_product(device)
        return device

    # 2. miot-spec.org instance link
    if "miot-spec.org/miot-spec-v2/instance" in source:
        urn = source.split("type=")[-1].split("&")[0]
        instance = fetch_instance(urn)
        device.set_urn(instance.get("type", urn))
        device.model = instance.get("model") or model_from_urn(device.urn)
        device.services = _services_from_instance(instance)
        if not device.model:
            raise ValueError(f"Can't find the model name for {device.urn}")
        if not offline:
            _fill_product(device)
        return device

    # 3. home.miot-spec.com link or plain model name
    model = model_from_source(source)
    if not model:
        raise ValueError(f"Unsupported source: {source}")
    device.model = model
    try:
        props = fetch_page_props(f"{WEB}/spec/{model}")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        # home.miot-spec.com doesn't know this model - use miot-spec.org
        urn = urn_from_model(model)
        if not urn:
            raise ValueError(f"Model {model} not found on {WEB} and {API}")
        instance = fetch_instance(urn)
        device.set_urn(instance.get("type", urn))
        device.services = _services_from_instance(instance)
        if not offline:
            _fill_product(device)
        return device
    device.set_urn(props["spec"]["urn"])
    device.services = props["tree"]["services"]
    product = props.get("product", {})
    device.name = product.get("name")
    device.pdid = pdid_from_url(product.get("icon", ""))
    _fill_product(device)
    return device


def _fill_product(device: Device) -> None:
    """Get pdid, brand and protocol from the product page."""
    if not device.model:
        return
    try:
        props = fetch_page_props(f"{WEB}/p/{device.model}")
    except (urllib.error.URLError, ValueError, OSError) as e:
        print(f"warning: can't load product page: {e}", file=sys.stderr)
        return
    product = props.get("product", {})
    device.pdid = product.get("pdId") or device.pdid
    device.brand = product.get("brand") or device.brand
    device.protocol = product.get("protocolLabel") or device.protocol
    device.name = product.get("name") or device.name


def _services_from_instance(instance: dict) -> list:
    """Convert a miot-spec.org instance into the home.miot-spec tree shape."""
    services = []
    for service in instance.get("services", []):
        if service["iid"] == 1:  # device information
            continue
        services.append(
            {
                "iid": service["iid"],
                "type": service["type"].split(":")[3],
                "description": service.get("description", ""),
                "properties": [
                    {
                        "iid": p["iid"],
                        "type": p["type"].split(":")[3],
                        "description": p.get("description", ""),
                        "format": p.get("format", ""),
                        "unit": p.get("unit", ""),
                        "access": p.get("access", []),
                        "valueList": [
                            {"value": v["value"], "description": v.get("description", "")}
                            for v in p.get("value-list", [])
                        ],
                        "valueRange": p.get("value-range"),
                    }
                    for p in service.get("properties", [])
                ],
                "events": [
                    {
                        "iid": e["iid"],
                        "type": e["type"].split(":")[3],
                        "description": e.get("description", ""),
                    }
                    for e in service.get("events", [])
                ],
                "actions": [],
            }
        )
    return services


# --- code generation ------------------------------------------------------


def py_str(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def map_literal(value_list: list) -> str:
    items = ", ".join(
        f"{v['value']}: {py_str(v['description'])}" for v in value_list
    )
    return "{" + items + "}"


def channel_suffix(index: int, total: int) -> str:
    return "" if total <= 1 else f"_{index}"


def check_value_list(value_list: list, mi: str) -> str | None:
    """Warn about suspicious value lists, e.g. the known spec typo."""
    descriptions = [v["description"] for v in value_list]
    if len(set(descriptions)) != len(descriptions):
        return (
            f"value list of {mi} has duplicate descriptions "
            f"({', '.join(descriptions)}) - the miot spec is probably wrong here"
        )
    return None


def build_converters(device: Device) -> tuple[list[str], list[str]]:
    """Return (list of converter lines, list of notes)."""
    lines: list[str] = []
    notes: list[str] = []

    switch_services = [s for s in device.services if s["type"] == "switch"]
    sensor_services = [s for s in device.services if s["type"] == "switch-sensor"]

    # action sensor and button events
    actions = []
    for index, service in enumerate(sensor_services, 1):
        for event in service.get("events", []):
            action = EVENT_MAP.get(event["type"])
            if not action:
                notes.append(
                    f"skipped event {event['type']} "
                    f"({service['iid']}.e.{event['iid']}), no constant for it"
                )
                continue
            if len(sensor_services) > 1:
                constant = f"BUTTON_{index}_{action}"
            else:
                constant = f"BUTTON_{action}"
            actions.append(
                f'        ConstConv("action", mi="{service["iid"]}.e.{event["iid"]}", '
                f"value={constant}),"
            )
    if actions:
        lines.append('        BaseConv("action", "sensor"),')
        lines += actions

    # properties
    used: set[str] = set()

    def add(line: str, attr: str | None = None):
        if attr and attr in used:
            return
        if attr:
            used.add(attr)
        lines.append(line)

    for index, service in enumerate(switch_services, 1):
        suffix = channel_suffix(index, len(switch_services))
        for prop in service.get("properties", []):
            line, note, attr = convert_property(device, service, prop, suffix, index)
            if line:
                add(line, attr)
            if note:
                notes.append(note)

    for index, service in enumerate(sensor_services, 1):
        suffix = channel_suffix(index, len(sensor_services))
        for prop in service.get("properties", []):
            line, note, attr = convert_property(device, service, prop, suffix, index)
            if line:
                add(line, attr)
            if note:
                notes.append(note)

    for service in device.services:
        if service["type"] in ("switch", "switch-sensor"):
            continue
        for prop in service.get("properties", []):
            line, note, attr = convert_property(device, service, prop, "", 0)
            if line:
                add(line, attr)
            if note:
                notes.append(note)

    return lines, notes


def convert_property(
    device: Device, service: dict, prop: dict, suffix: str, index: int
) -> tuple[str | None, str | None, str | None]:
    """Convert one MIoT property into a converter line, a note and an attr."""
    mi = f'{service["iid"]}.p.{prop["iid"]}'
    ptype = prop["type"]
    service_type = service["type"]
    writable = "write" in prop.get("access", [])
    value_list = prop.get("valueList") or []

    # "on" property
    if ptype == "on":
        if service_type in ON_MAP:
            attr, domain = ON_MAP[service_type]
            if service_type in ("switch", "outlet"):
                attr += suffix
            # a switch service of an outlet device is an outlet in hass
            if attr == "switch" and device.category == "outlet":
                attr = "outlet"
            return (
                f'        BaseConv({py_str(attr)}, {py_str(domain)}, mi="{mi}"),',
                None,
                attr,
            )
        return (
            None,
            f"skipped property {service_type}.{ptype} ({mi}), no domain for it",
            None,
        )

    # "mode" property
    if ptype == "mode":
        if service_type == "switch":
            attr = "switch_mode" + suffix
        elif service_type == "switch-sensor":
            attr = "sensor_mode" + suffix
        elif service_type == "light":
            attr = "light_mode"
        elif service_type == "fan":
            attr = "fan_mode"
        else:
            attr = "mode"
        if not value_list:
            return None, f"skipped property {mi} (mode without value list)", None
        return (
            f'        MapConv({py_str(attr)}, "select", mi="{mi}", '
            f"map={map_literal(value_list)}),",
            check_value_list(value_list, mi),
            attr,
        )

    # known property types
    if ptype in PROPERTY_MAP:
        attr, domain = PROPERTY_MAP[ptype]
        if domain == "switch" and not writable:
            domain = "binary_sensor"
        if value_list:
            return (
                f'        MapConv({py_str(attr)}, {py_str(domain)}, mi="{mi}", '
                f"map={map_literal(value_list)}),",
                check_value_list(value_list, mi),
                attr,
            )
        if prop["format"] == "bool":
            entity = ""
            if ptype == "power-consumption-accumulation-way":
                entity = ", entity=ENTITY_DIAGNOSTIC"
            return (
                f'        BaseConv({py_str(attr)}, {py_str(domain)}, mi="{mi}"{entity}),',
                None,
                attr,
            )
        if domain == "sensor" and prop["format"] not in ("bool",):
            conv = "BaseConv"
            extra = ""
            if prop["type"] == "power-consumption":
                conv, extra = "MathConv", ", round=2, step=0.01"
            elif prop["type"] == "electric-power":
                conv, extra = "MathConv", ", round=1"
            return (
                f'        {conv}({py_str(attr)}, {py_str(domain)}, mi="{mi}"{extra}),',
                NOTES.get(ptype),
                attr,
            )
        return (
            f'        BaseConv({py_str(attr)}, {py_str(domain)}, mi="{mi}"),',
            None,
            attr,
        )

    # color temperature needs a special converter
    if ptype == "color-temperature":
        mink, maxk = 2700, 6500
        value_range = prop.get("valueRange")
        if value_range and len(value_range) >= 2:
            mink, maxk = int(value_range[0]), int(value_range[1])
        return (
            f'        ColorTempKelvin("color_temp", mi="{mi}", '
            f"mink={mink}, maxk={maxk}),",
            None,
            "color_temp",
        )

    # unknown property types - generic rules
    vendor = (
        " - vendor extension property"
        if prop["iid"] >= 1000
        else ""
    )
    if value_list and prop["format"] in ("uint8", "uint16", "int8", "int16", "int32"):
        attr = ptype.replace("-", "_")
        return (
            f'        MapConv({py_str(attr)}, "select", mi="{mi}", '
            f"map={map_literal(value_list)}),",
            f"check domain and name of {ptype} ({mi}){vendor}",
            attr,
        )
    if prop["format"] == "bool":
        domain = "switch" if writable else "binary_sensor"
        attr = ptype.replace("-", "_")
        return (
            f'        BaseConv({py_str(attr)}, {py_str(domain)}, mi="{mi}"),',
            f"check domain and name of {ptype} ({mi}){vendor}",
            attr,
        )
    if prop["format"] in ("uint8", "uint16", "int8", "int16", "int32", "float"):
        unit = (prop.get("unit") or "").lower()
        if unit in UNIT_MAP:
            attr, domain = UNIT_MAP[unit]
            return (
                f'        BaseConv({py_str(attr)}, {py_str(domain)}, mi="{mi}"),',
                None,
                attr,
            )
        attr = ptype.replace("-", "_")
        return (
            f'        BaseConv({py_str(attr)}, "sensor", mi="{mi}"),',
            f"check name, unit and rounding of {ptype} ({mi}){vendor}",
            attr,
        )

    return (
        None,
        f"skipped property {ptype} ({mi}), unknown format {prop['format']}",
        None,
    )


def build_entry(device: Device, brand: str, name: str, market_model: str) -> tuple[str, str]:
    """Return (entry to paste, same entry as valid python for a syntax check)."""
    lines, notes = build_converters(device)

    if device.pdid is None:
        key = "TODO_PDID"
    else:
        key = str(device.pdid)

    info = [py_str(brand), py_str(name)]
    if market_model:
        info.append(py_str(market_model))
    info.append(py_str(device.model))

    body = [
        f"    # {WEB}/spec/{device.model}",
        f"    {key}: [{', '.join(info)}],",
        '    "spec": [',
    ]
    body += lines
    body.append("    ],")

    if notes:
        body.append("")
        for note in notes:
            body.append(f"    # TODO: {note}")

    entry = "\n".join(["}, {"] + body)
    check = "\n".join(["DEVICES = [{"] + body + ["}]"])
    return entry, check


def check_existing(device: Device) -> list[str]:
    """Report entries of devices.py that match this device."""
    result = []
    if not os.path.isfile(DEVICES_PY):
        return result
    with open(DEVICES_PY, encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            if line.lstrip().startswith("#"):
                continue
            if device.model and device.model in line:
                result.append(f"model {device.model} already in devices.py at line {number}")
            if device.pdid and re.match(rf"^\s*{device.pdid}: \[", line):
                result.append(f"pdid {device.pdid} already in devices.py at line {number}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a proposed DEVICES entry for a MIoT device.",
    )
    parser.add_argument(
        "source",
        help="link to home.miot-spec.com / miot-spec.org, miot model name "
        "or path to a saved html page",
    )
    parser.add_argument("--pdid", type=int, help="override product id (pdid)")
    parser.add_argument("--brand", default="TODO", help="market brand")
    parser.add_argument("--name", default="TODO", help="market name")
    parser.add_argument(
        "--market-model", default="", help="hardware model, e.g. XMS01BXS"
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="don't load the product page (pdid, brand, protocol)",
    )
    args = parser.parse_args()

    try:
        device = load_device(args.source, offline=args.offline)
    except (urllib.error.URLError, ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.pdid:
        device.pdid = args.pdid

    if device.pdid is None:
        print(
            "warning: unknown pdid, the key is TODO_PDID - pass it with --pdid",
            file=sys.stderr,
        )

    entry, check = build_entry(device, args.brand, args.name, args.market_model)

    # sanity check: the generated code should be valid python
    try:
        ast.parse(check)
    except SyntaxError as e:
        print(f"error: generated code is not valid python: {e}", file=sys.stderr)
        return 1

    print("/* proposed entry - review before pasting into devices.py */")
    print(entry)
    print()

    print("--- info", file=sys.stderr)
    print(f"model:     {device.model}", file=sys.stderr)
    print(f"urn:       {device.urn}", file=sys.stderr)
    print(f"pdid:      {device.pdid}", file=sys.stderr)
    print(f"section:   {device.section} (protocol: {device.protocol})", file=sys.stderr)
    if device.name:
        print(f"cn name:   {device.name}", file=sys.stderr)
    if device.brand:
        print(f"cn brand:  {device.brand}", file=sys.stderr)
    for line in check_existing(device):
        print(f"warning:   {line}", file=sys.stderr)
    print(
        "note:      --brand, --name and --market-model are not in the MIoT "
        "spec, fill them manually",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
