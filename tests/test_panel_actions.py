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
            f"StatusBar and Footer collide at y={sb.region.y}; got sb={sb.region}, ft={ft.region}"
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


# ---------------------------------------------------------------------------
# Cursor-row highlight bar should span the full visible width of the table,
# not just sum-of-content-widths. Before fit_last_column the highlight ended
# wherever the last cell's text ended, leaving a misaligned strip on the
# right of the panel.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hidden_panel_refresh_skips_work():
    """Background panels' set_interval should no-op when their tab is hidden.

    Before this fix every panel kept calling rclpy + rebuilding its table at
    1-2 Hz even when its tab wasn't visible, multiplied by 9 panels.
    """
    from lazyrosplus.widgets.nodes_panel import NodesPanel
    from lazyrosplus.widgets.topics_panel import TopicsPanel

    async with _app().run_test(headless=True, size=(160, 40)) as pilot:
        await pilot.pause()
        # Default active tab is Messages — NodesPanel must be hidden.
        nodes = pilot.app.query_one(NodesPanel)
        topics = pilot.app.query_one(TopicsPanel)
        assert nodes.region.width == 0, "expected NodesPanel to be hidden"
        assert topics.region.width > 0, "expected TopicsPanel to be visible"

        # Calling _refresh on a hidden panel must be effectively free —
        # don't even touch the (potentially unstarted) backend.
        called = {"list_nodes": 0}

        class _Spy:
            started = True

            def list_nodes(self):
                called["list_nodes"] += 1
                return []

        # Swap in a counting backend; _refresh would normally hit it.
        nodes_panel_app = nodes.app
        original_ros = nodes_panel_app.ros
        nodes_panel_app.ros = _Spy()  # type: ignore[assignment]
        try:
            for _ in range(20):
                nodes._refresh()
            assert called["list_nodes"] == 0, (
                f"hidden panel should not query the backend, but called list_nodes "
                f"{called['list_nodes']} times"
            )
        finally:
            nodes_panel_app.ros = original_ros  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_domain_command_invokes_set_domain_id():
    """`:domain N` should call RosBackend.set_domain_id(N) and notify the user."""
    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        calls: list[int | None] = []

        def fake_set(new_id: int | None) -> None:
            calls.append(new_id)

        pilot.app.ros.set_domain_id = fake_set  # type: ignore[assignment]
        notes = _capture_notifications(pilot.app)
        pilot.app._on_command_submitted("domain 7")
        await pilot.pause()
        assert calls == [7]
        body = " ".join(str(a[0]) for a, _ in notes)
        assert "ROS_DOMAIN_ID=7" in body


@pytest.mark.asyncio
async def test_domain_command_rejects_garbage():
    """Non-integer / out-of-range domain ids should warn, not crash."""
    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        called = {"n": 0}

        def fake_set(_new_id: int | None) -> None:
            called["n"] += 1

        pilot.app.ros.set_domain_id = fake_set  # type: ignore[assignment]
        notes = _capture_notifications(pilot.app)
        pilot.app._on_command_submitted("domain abc")
        pilot.app._on_command_submitted("domain 999")
        await pilot.pause()
        assert called["n"] == 0
        body = " ".join(str(a[0]) for a, _ in notes)
        assert "invalid" in body
        assert "outside valid range" in body


@pytest.mark.asyncio
async def test_services_table_fills_panel_width_on_first_render():
    from textual.widgets import DataTable

    from lazyrosplus.widgets.services_panel import ServicesPanel

    async with _app().run_test(headless=True, size=(160, 40)) as pilot:
        await pilot.pause()
        pilot.app.query_one(TabbedContent).active = "services"
        for _ in range(3):
            await pilot.pause()
        panel = pilot.app.query_one(ServicesPanel)
        panel._svc_cache = [_service(f"/controller/foo{i}/call_service", "") for i in range(5)]
        panel._render_table()
        await pilot.pause()
        table = pilot.app.query_one("#srv-table", DataTable)
        gap = table.region.width - table.virtual_size.width
        # Within 2 cells of the visible region; a perfect zero gap is fragile
        # (depends on whether a scrollbar slot is reserved).
        assert -2 <= gap <= 2, (
            f"row highlight will not span full width: region={table.region.width} "
            f"virtual={table.virtual_size.width}"
        )
