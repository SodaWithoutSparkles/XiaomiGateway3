import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ast

from generate_device import (
    Device,
    build_converters,
    build_entry,
    check_value_list,
    channel_suffix,
    map_literal,
    py_str,
)

SWITCH_SERVICES = [
    {
        "iid": 2,
        "type": "switch",
        "properties": [
            {
                "iid": 1,
                "type": "on",
                "format": "bool",
                "access": ["read", "write", "notify"],
                "valueList": [],
            },
            {
                "iid": 2,
                "type": "mode",
                "format": "uint8",
                "access": ["read", "write", "notify"],
                "valueList": [
                    {"value": 0, "description": "Wired And Wireless"},
                    {"value": 1, "description": "Wireless"},
                ],
            },
            {
                "iid": 3,
                "type": "fault",
                "format": "uint8",
                "access": ["read", "notify"],
                "valueList": [
                    {"value": 0, "description": "No Faults"},
                    {"value": 1, "description": "Over Temperature"},
                ],
            },
        ],
        "events": [],
    },
    {
        "iid": 4,
        "type": "switch-sensor",
        "properties": [
            {
                "iid": 1,
                "type": "mode",
                "format": "uint8",
                "access": ["read", "write", "notify"],
                "valueList": [
                    {"value": 0, "description": "Quick Single Click"},
                    {"value": 1, "description": "Multiple Click"},
                ],
            }
        ],
        "events": [
            {"iid": 1, "type": "click", "description": "Click"},
            {"iid": 2, "type": "double-click", "description": "Double Click"},
            {"iid": 3, "type": "long-press", "description": "Long Press"},
        ],
    },
    {
        "iid": 7,
        "type": "indicator-light",
        "properties": [
            {
                "iid": 1,
                "type": "on",
                "format": "bool",
                "access": ["read", "write", "notify"],
                "valueList": [],
            }
        ],
        "events": [],
    },
]


def make_device(services=None) -> Device:
    device = Device()
    device.model = "xiaomi.switch.test"
    device.pdid = 12345
    device.services = services if services is not None else SWITCH_SERVICES
    return device


def test_py_str():
    assert py_str("abc") == '"abc"'
    assert py_str('a"b') == '"a\\"b"'


def test_map_literal():
    assert map_literal([{"value": 0, "description": "Off"}]) == '{0: "Off"}'


def test_channel_suffix():
    assert channel_suffix(1, 1) == ""
    assert channel_suffix(2, 2) == "_2"


def test_check_value_list():
    assert check_value_list([{"value": 0, "description": "A"}], "2.p.2") is None
    note = check_value_list(
        [{"value": 0, "description": "A"}, {"value": 1, "description": "A"}], "2.p.2"
    )
    assert note and "duplicate" in note


def test_build_converters():
    lines, notes = build_converters(make_device())
    text = "\n".join(lines)
    assert 'BaseConv("switch", "switch", mi="2.p.1")' in text
    assert 'MapConv("switch_mode", "select", mi="2.p.2"' in text
    assert 'MapConv("fault", "sensor", mi="2.p.3"' in text
    assert 'MapConv("sensor_mode", "select", mi="4.p.1"' in text
    assert 'BaseConv("indicator_light", "switch", mi="7.p.1")' in text
    assert 'BaseConv("action", "sensor")' in text
    assert 'value=BUTTON_SINGLE' in text
    assert 'value=BUTTON_DOUBLE' in text
    assert 'value=BUTTON_HOLD' in text
    assert notes == []


def test_build_converters_multi_channel():
    services = [dict(s) for s in SWITCH_SERVICES]
    # second switch channel
    services.append(
        {
            "iid": 3,
            "type": "switch",
            "properties": [
                {
                    "iid": 1,
                    "type": "on",
                    "format": "bool",
                    "access": ["read", "write", "notify"],
                    "valueList": [],
                }
            ],
            "events": [],
        }
    )
    lines, _ = build_converters(make_device(services))
    text = "\n".join(lines)
    assert 'BaseConv("switch_1", "switch", mi="2.p.1")' in text
    assert 'BaseConv("switch_2", "switch", mi="3.p.1")' in text
    # one switch sensor service - buttons have no channel number
    assert "value=BUTTON_SINGLE" in text


def test_build_converters_multi_button():
    services = [dict(s) for s in SWITCH_SERVICES]
    # second switch sensor channel
    services.append(
        {
            "iid": 5,
            "type": "switch-sensor",
            "properties": [],
            "events": [{"iid": 1, "type": "click", "description": "Click"}],
        }
    )
    lines, _ = build_converters(make_device(services))
    text = "\n".join(lines)
    assert "value=BUTTON_1_SINGLE" in text
    assert "value=BUTTON_2_SINGLE" in text


def test_build_converters_deduplicates_attrs():
    services = [dict(s) for s in SWITCH_SERVICES]
    # second indicator light service with the same attribute
    services.append(
        {
            "iid": 9,
            "type": "indicator-light",
            "properties": [
                {
                    "iid": 1,
                    "type": "on",
                    "format": "bool",
                    "access": ["read", "notify"],
                    "valueList": [],
                }
            ],
            "events": [],
        }
    )
    lines, _ = build_converters(make_device(services))
    text = "\n".join(lines)
    assert text.count('BaseConv("indicator_light"') == 1


def test_build_entry_is_valid_python():
    entry, check = build_entry(make_device(), "Xiaomi", "Test Switch", "XMS01BXS")
    ast.parse(check)
    assert "21504" not in entry
    assert '12345: ["Xiaomi", "Test Switch", "XMS01BXS", "xiaomi.switch.test"]' in entry
    assert entry.startswith("}, {")
