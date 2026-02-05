"""Tests for V4L2 control discovery and parsing."""

from multiwebcam.sources.controls import V4L2Control, parse_controls


def test_parse_controls_integer():
    """Parse integer control from v4l2-ctl output."""
    output = """
                     brightness 0x00980900 (int)    : min=0 max=255 step=1 default=128 value=128
    """

    controls = parse_controls(output)

    assert len(controls) == 1
    ctrl = controls[0]
    assert ctrl.name == "brightness"
    assert ctrl.type == "int"
    assert ctrl.min == 0
    assert ctrl.max == 255
    assert ctrl.step == 1
    assert ctrl.default == 128
    assert ctrl.current == 128
    assert ctrl.menu_items is None


def test_parse_controls_menu():
    """Parse menu control with items."""
    output = """
                  exposure_auto 0x009a0901 (menu)   : min=0 max=3 default=3 value=3
                                    1: Manual Mode
                                    3: Aperture Priority Mode
    """

    controls = parse_controls(output)

    assert len(controls) == 1
    ctrl = controls[0]
    assert ctrl.name == "exposure_auto"
    assert ctrl.type == "menu"
    assert ctrl.min == 0
    assert ctrl.max == 3
    assert ctrl.default == 3
    assert ctrl.current == 3
    assert ctrl.menu_items == {1: "Manual Mode", 3: "Aperture Priority Mode"}


def test_parse_controls_multiple():
    """Parse multiple controls from output."""
    output = """
                     brightness 0x00980900 (int)    : min=0 max=255 step=1 default=128 value=128
                       contrast 0x00980901 (int)    : min=0 max=255 step=1 default=128 value=128
                  exposure_auto 0x009a0901 (menu)   : min=0 max=3 default=3 value=3
                                    1: Manual Mode
                                    3: Aperture Priority Mode
             exposure_absolute 0x009a0902 (int)    : min=3 max=2047 step=1 default=250 value=166
    """

    controls = parse_controls(output)

    assert len(controls) == 4
    assert controls[0].name == "brightness"
    assert controls[1].name == "contrast"
    assert controls[2].name == "exposure_auto"
    assert controls[3].name == "exposure_absolute"


def test_parse_controls_bool():
    """Parse boolean control."""
    output = """
               focus_automatic 0x009a090c (bool)   : default=1 value=1
    """

    controls = parse_controls(output)

    assert len(controls) == 1
    ctrl = controls[0]
    assert ctrl.name == "focus_automatic"
    assert ctrl.type == "bool"
    assert ctrl.default == 1
    assert ctrl.current == 1


def test_v4l2_control_str_integer():
    """String representation of integer control."""
    ctrl = V4L2Control(
        name="brightness",
        type="int",
        min=0,
        max=255,
        step=1,
        default=128,
        current=150,
    )

    assert "brightness" in str(ctrl)
    assert "150" in str(ctrl)
    assert "[0-255]" in str(ctrl)


def test_v4l2_control_str_menu():
    """String representation of menu control."""
    ctrl = V4L2Control(
        name="exposure_auto",
        type="menu",
        min=0,
        max=3,
        step=None,
        default=3,
        current=1,
        menu_items={1: "Manual Mode", 3: "Aperture Priority Mode"},
    )

    s = str(ctrl)
    assert "exposure_auto" in s
    assert "Manual Mode" in s
    assert "(menu)" in s


def test_v4l2_control_str_bool():
    """String representation of boolean control."""
    ctrl = V4L2Control(
        name="focus_auto",
        type="bool",
        min=None,
        max=None,
        step=None,
        default=1,
        current=0,
    )

    s = str(ctrl)
    assert "focus_auto" in s
    assert "OFF" in s


def test_v4l2_control_immutability():
    """V4L2Control is frozen."""
    ctrl = V4L2Control(
        name="brightness",
        type="int",
        min=0,
        max=255,
        step=1,
        default=128,
        current=128,
    )

    try:
        ctrl.current = 200  # type: ignore[misc]
        assert False, "Should not allow mutation"
    except AttributeError:
        pass  # Expected


if __name__ == "__main__":
    """Debug harness for manual testing."""
    from pathlib import Path

    debug_dir = Path(__file__).parent / "tmp"
    debug_dir.mkdir(parents=True, exist_ok=True)

    print("=== Running manual tests ===\n")

    # Test parsing
    print("Test: parse integer control")
    output = """
                     brightness 0x00980900 (int)    : min=0 max=255 step=1 default=128 value=128
    """
    controls = parse_controls(output)
    print(f"Parsed: {controls[0]}")

    print("\nTest: parse menu control")
    output = """
                  exposure_auto 0x009a0901 (menu)   : min=0 max=3 default=3 value=3
                                    1: Manual Mode
                                    3: Aperture Priority Mode
    """
    controls = parse_controls(output)
    print(f"Parsed: {controls[0]}")
    print(f"Menu items: {controls[0].menu_items}")

    print("\nDone.")
