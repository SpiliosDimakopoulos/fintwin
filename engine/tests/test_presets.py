import pytest

from fintwin.scenarios.presets import KNOBS, PRESETS, build_scenario


def test_every_preset_uses_only_known_knobs():
    for name, preset in PRESETS.items():
        unknown = set(preset["knobs"]) - set(KNOBS)
        assert not unknown, f"preset {name!r} uses unknown knobs: {sorted(unknown)}"


def test_every_preset_has_a_label_and_description():
    for name, preset in PRESETS.items():
        assert isinstance(preset.get("label"), str) and preset["label"].strip(), (
            f"preset {name!r} needs a non-empty label"
        )
        assert isinstance(preset.get("desc"), str) and preset["desc"].strip(), (
            f"preset {name!r} needs a non-empty description"
        )


def test_gfc_2008_preset_follows_its_calibration():
    s = build_scenario(PRESETS["gfc_2008"]["knobs"], 12)
    # Revenue bottoms at -20% and is back to baseline after 3 + 7 quarters.
    assert s["sales_shock"].min() == pytest.approx(-0.2)
    assert list(s["sales_shock"][10:]) == [0.0, 0.0]
    # Spreads +400bp for 3 quarters, debt markets shut for 2, rates end 300bp lower.
    assert list(s["spread_shift"][:4]) == pytest.approx([0.04, 0.04, 0.04, 0.0])
    assert list(s["refi_access"][:3]) == [0.0, 0.0, 1.0]
    assert s["rate_shift"][-1] == pytest.approx(-0.03)
