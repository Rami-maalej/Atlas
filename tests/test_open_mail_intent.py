"""Intent + declaration wiring for the new mail screen and Jev tool."""

from __future__ import annotations

from actions.intent_router import route


def test_open_mail_screen_matches() -> None:
    result = route("open mail screen")
    assert result.matched
    assert result.handler_name == "open_mail_screen"


def test_open_my_inbox_screen_matches() -> None:
    result = route("open my inbox screen")
    assert result.matched
    assert result.handler_name == "open_mail_screen"


def test_show_mail_app_matches() -> None:
    result = route("show the email app")
    assert result.matched
    assert result.handler_name == "open_mail_screen"


def test_french_open_mail_matches() -> None:
    result = route("ouvre mes mails")
    assert result.matched
    assert result.handler_name == "open_mail_screen"


def test_read_emails_never_opens_screen() -> None:
    """Regression: reading mails by voice must not open the screen."""
    result = route("read my emails")
    assert result.matched
    assert result.handler_name != "open_mail_screen"
    assert result.handler_name in ("read_emails", "gmail_get_unread")


def test_open_app_still_routes_to_open_app() -> None:
    result = route("open firefox")
    assert result.matched
    assert result.handler_name == "open_app"


def test_declarations_contain_new_tools() -> None:
    from core.tools.declarations import TOOL_DECLARATIONS

    names = {d["name"] for d in TOOL_DECLARATIONS}
    assert "open_mail_screen" in names
    assert "type_safe_decide" in names
    assert "read_emails" in names


def test_executor_handles_new_tools() -> None:
    """The dispatch chain must contain both new branches (read as source:
    importing executor pulls in cv2/playwright and other optional deps)."""
    from pathlib import Path

    source = (Path("core/tools/executor.py")).read_text(encoding="utf-8")
    assert 'name == "open_mail_screen"' in source
    assert 'name == "type_safe_decide"' in source
