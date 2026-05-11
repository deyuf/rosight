"""Headless unit tests for panel actions and layout.

These don't need rclpy — they use a non-started RosBackend (so ``ros.started``
is False) plus stubbed in-memory caches on the panels themselves.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("textual")

from textual.widgets import Footer, Static, TabbedContent

from lazyrosplus.app import LazyrosPlusApp
from lazyrosplus.ros.backend import RosBackend
from lazyrosplus.widgets.status_bar import StatusBar


def _app() -> LazyrosPlusApp:
    return LazyrosPlusApp(ros=RosBackend())


def _topic(name: str, type_name: str = "std_msgs/msg/String", pubs: int = 1) -> SimpleNamespace:
    """A duck-typed TopicInfo that matches what the panels read."""
    return SimpleNamespace(
        name=name,
        types=(type_name,),
        primary_type=type_name,
        publisher_count=pubs,
        subscriber_count=0,
    )


def _service(name: str, type_name: str = "std_srvs/srv/Empty") -> SimpleNamespace:
    return SimpleNamespace(name=name, types=(type_name,), primary_type=type_name)


# ---------------------------------------------------------------------------
# Bug #1: status bar and footer must not overlap.
# Before the fix both were `dock: bottom; height: 1`, so they rendered on the
# same row and Footer hid every push_status / notify-like message.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_bar_and_footer_do_not_overlap():
    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        sb = pilot.app.query_one(StatusBar)
        ft = pilot.app.query_one(Footer)
        assert sb.region.y != ft.region.y, (
            f"StatusBar and Footer collide at y={sb.region.y}; "
            f"got sb={sb.region}, ft={ft.region}"
        )
        # The status bar should sit immediately above the footer.
        assert sb.region.y + sb.region.height == ft.region.y


# ---------------------------------------------------------------------------
# Bug #2: topics `i` info was clobbered by the 0.25 s `_refresh_detail` tick.
# After the fix the info lives in its own #info-area Static.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topics_action_info_writes_to_info_area_and_survives_refresh():
    from lazyrosplus.widgets.topics_panel import TopicsPanel

    async with _app().run_test(headless=True, size=(160, 40)) as pilot:
        await pilot.pause()
        # Switch to topics tab so the panel is mounted.
        pilot.app.query_one(TabbedContent).active = "topics"
        await pilot.pause()

        panel = pilot.app.query_one(TopicsPanel)
        panel._topic_cache = [_topic("/odom", "nav_msgs/msg/Odometry")]
        panel.selected_topic = "/odom"
        panel.action_info()
        await pilot.pause()

        info_area = pilot.app.query_one("#info-area", Static)
        rendered = str(getattr(info_area, "renderable", "") or info_area.content)
        assert "/odom" in rendered
        assert "nav_msgs/msg/Odometry" in rendered

        # Run `_refresh_detail` explicitly several times — it must NOT touch
        # `#info-area`, only the realtime `#detail-header`.
        for _ in range(5):
            panel._refresh_detail()
        await pilot.pause()
        rendered_after = str(getattr(info_area, "renderable", "") or info_area.content)
        assert "/odom" in rendered_after


# ---------------------------------------------------------------------------
# Bug #3: services `c` (call) and topics `P` (publish) silently pushed to a
# hidden status bar. After the fix they use `app.notify` so the user gets a
# visible toast even before the call form is implemented.
# ---------------------------------------------------------------------------


def _capture_notifications(app: LazyrosPlusApp) -> list[tuple[tuple, dict]]:
    recorded: list[tuple[tuple, dict]] = []
    real_notify = app.notify

    def fake(*args, **kwargs):
        recorded.append((args, kwargs))
        return real_notify(*args, **kwargs)

    app.notify = fake  # type: ignore[method-assign]
    return recorded


@pytest.mark.asyncio
async def test_services_action_call_notifies_with_selected_service():
    from lazyrosplus.widgets.services_panel import ServicesPanel

    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        pilot.app.query_one(TabbedContent).active = "services"
        await pilot.pause()

        panel = pilot.app.query_one(ServicesPanel)
        panel._svc_cache = [_service("/add_two_ints", "example_interfaces/srv/AddTwoInts")]
        panel.selected = "/add_two_ints"

        notes = _capture_notifications(pilot.app)
        panel.action_call()
        await pilot.pause()

        body = " ".join(str(a[0]) for a, _ in notes)
        assert "/add_two_ints" in body
        assert "not yet implemented" in body


@pytest.mark.asyncio
async def test_services_action_call_warns_when_nothing_selected():
    from lazyrosplus.widgets.services_panel import ServicesPanel

    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        pilot.app.query_one(TabbedContent).active = "services"
        await pilot.pause()
        panel = pilot.app.query_one(ServicesPanel)
        panel._svc_cache = []
        panel.selected = None
        notes = _capture_notifications(pilot.app)
        panel.action_call()
        await pilot.pause()
        # Should warn user, not silently no-op.
        assert any("no service" in str(a[0]) for a, _ in notes)


@pytest.mark.asyncio
async def test_topics_action_publish_notifies():
    from lazyrosplus.widgets.topics_panel import TopicsPanel

    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        pilot.app.query_one(TabbedContent).active = "topics"
        await pilot.pause()
        panel = pilot.app.query_one(TopicsPanel)
        panel._topic_cache = [_topic("/x")]
        panel.selected_topic = "/x"
        notes = _capture_notifications(pilot.app)
        panel.action_publish()
        await pilot.pause()
        assert any("publish" in str(a[0]).lower() for a, _ in notes)
