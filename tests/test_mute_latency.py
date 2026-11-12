from actions import computer_settings
from actions.intent_router import route


def test_mute_sound_uses_direct_intent():
    intent = route("mute the sound")

    assert intent.matched
    assert not intent.requires_ai
    assert intent.handler_name == "computer_settings"
    assert intent.handler_params["description"] == "volume_mute"


def test_linux_mute_command_has_timeout(monkeypatch):
    calls = []
    monkeypatch.setattr(computer_settings, "_OS", "Linux")
    monkeypatch.setattr(
        computer_settings.subprocess,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    computer_settings.volume_mute()

    assert calls[0][1]["timeout"] == 2