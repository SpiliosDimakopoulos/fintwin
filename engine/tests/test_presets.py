from fintwin.scenarios.presets import KNOBS, PRESETS


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
