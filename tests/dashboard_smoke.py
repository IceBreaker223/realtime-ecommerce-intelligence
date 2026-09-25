"""Browser tests against running API; screenshots use real data, fixtures stay in browser."""
import os
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

BASE = os.getenv("DASHBOARD_URL", "http://localhost:8000")


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.driver = sync_playwright().start()
        channel = os.getenv("BROWSER_CHANNEL", "msedge" if os.name == "nt" else "chromium")
        cls.browser = cls.driver.chromium.launch(channel=channel, headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 1440, "height": 1100}, timezone_id="Asia/Kolkata")
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    def mock(self, *, empty=False, offline=False, paginate=False):
        self.requests = []

        def handle(route):
            url = urlparse(route.request.url)
            query = parse_qs(url.query)
            self.requests.append((url.path, query))
            if offline:
                route.fulfill(status=503, json={"detail": "Unavailable"})
                return
            metrics = dict(order_count=0 if empty else 4, completed_order_count=0 if empty else 2,
                           completed_revenue="0" if empty else "600.00", failed_order_count=0 if empty else 1,
                           average_order_value=None if empty else "300.00", failed_order_rate=None if empty else "0.25",
                           last_updated=None if empty else datetime.now(timezone.utc).isoformat())
            if url.path.endswith("summary"):
                route.fulfill(json=dict(metrics, currency="INR", start=query["start"][0], end=query["end"][0]))
                return
            offset = int(query.get("offset", [0])[0])
            is_window = url.path.endswith("windows")
            name = "<img src=x onerror=alert(1)>"
            if is_window:
                item = dict(metrics, window_start=query["start"][0], dimension="all", dimension_value="")
            else:
                item = dict(metrics, dimension_value=name if offset == 0 else "Second page")
            items = [] if empty else [item]
            route.fulfill(json={"items": items, "has_more": paginate and offset == 0,
                                "limit": 500 if is_window else 5, "offset": offset})

        self.page.route("**/api/v1/metrics/**", handle)

    def loaded(self):
        expect(self.page.locator("#metrics")).to_have_attribute("aria-busy", "false")
        self.page.locator("#auto-refresh").uncheck()

    def test_live_desktop_and_mobile(self):
        self.page.goto(BASE)
        self.loaded()
        expect(self.page.locator("#error")).to_be_hidden()
        expect(self.page.locator("#orders")).not_to_have_text("—")
        expected = self.page.request.get(BASE + "/api/v1/metrics/summary").json()
        self.assertEqual(int(self.page.locator("#orders").inner_text().replace(",", "")), expected["order_count"])
        self.page.get_by_role("button", name="1 hour", exact=True).click()
        expect(self.page.locator("#chart-period")).to_have_text("over the last 1 hour")
        output = Path("runtime/dashboard")
        output.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(output / "desktop.png"), full_page=True)
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.screenshot(path=str(output / "mobile.png"), full_page=True)
        self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        self.assertLess(self.page.locator("#revenue").evaluate("element => element.getBoundingClientRect().height"), 35)
        expect(self.page.get_by_role("heading", name="Commerce overview.")).to_be_visible()

    def test_controls_pagination_and_safe_names(self):
        self.mock(paginate=True)
        self.page.goto(BASE)
        self.loaded()
        expect(self.page.locator("#revenue")).to_contain_text("600.00")
        expect(self.page.locator("#failure")).to_have_text("25.0%")
        expect(self.page.locator("#outcome-pending")).to_have_text("1")
        expect(self.page.locator("#performance-body img")).to_have_count(0)
        expect(self.page.locator(".product-name")).to_have_text("<img src=x onerror=alert(1)>")
        self.assertTrue(any(p.endswith("windows") and q["offset"] == ["500"] for p, q in self.requests))
        self.page.locator("#next").click()
        expect(self.page.locator(".product-name")).to_have_text("Second page")
        expect(self.page.locator("#previous")).to_be_enabled()
        self.page.get_by_role("button", name="Categories", exact=True).click()
        expect(self.page.locator("#dimension-title")).to_have_text("Category")
        expect(self.page.locator("#previous")).to_be_disabled()
        self.page.get_by_role("button", name="1 hour", exact=True).click()
        expect(self.page.locator("#chart-period")).to_have_text("over the last 1 hour")
        summary_requests = [q for p, q in self.requests if p.endswith("summary")]
        latest = summary_requests[-1]
        start = datetime.fromisoformat(latest["start"][0].replace("Z", "+00:00"))
        end = datetime.fromisoformat(latest["end"][0].replace("Z", "+00:00"))
        self.assertEqual((end - start).total_seconds(), 3600)

    def test_empty_state(self):
        self.mock(empty=True)
        self.page.goto(BASE)
        self.loaded()
        expect(self.page.locator("#orders")).to_have_text("0")
        expect(self.page.locator("#aov")).to_have_text("—")
        expect(self.page.locator("#failure")).to_have_text("—")
        expect(self.page.locator("#revenue-chart")).to_contain_text("No order activity")
        expect(self.page.locator("#connection-text")).to_have_text("No data in range")

    def test_failure_preserves_last_view_and_recovers(self):
        self.mock()
        self.page.goto(BASE)
        self.loaded()
        self.page.unroute("**/api/v1/metrics/**")
        self.mock(offline=True)
        self.page.locator("#refresh").click()
        expect(self.page.locator("#error")).to_contain_text("last successful view")
        expect(self.page.locator("#orders")).to_have_text("4")
        expect(self.page.locator("#connection-text")).to_have_text("Refresh unavailable")
        self.page.unroute("**/api/v1/metrics/**")
        self.mock()
        self.page.locator("#refresh").click()
        expect(self.page.locator("#error")).to_be_hidden()

    def test_initial_failure_does_not_show_zeroes(self):
        self.mock(offline=True)
        self.page.goto(BASE)
        self.loaded()
        expect(self.page.locator("#error")).to_contain_text("No analytics have loaded")
        expect(self.page.locator("#orders")).to_have_text("—")
        expect(self.page.locator("#performance-body")).to_contain_text("Analytics unavailable")

    def test_alert_evidence_and_pagination(self):
        self.mock()
        def alerts(route):
            query = parse_qs(urlparse(route.request.url).query)
            offset = int(query.get("offset", [0])[0])
            route.fulfill(json={
                "checked_count": 20, "insufficient_count": 4, "flagged_count": 6,
                "last_successful_run": datetime.now(timezone.utc).isoformat(), "has_more": offset == 0,
                "items": [{"window_start": datetime.now(timezone.utc).isoformat(),
                           "detector": "failure_rate_spike" if offset == 0 else "revenue_spike",
                           "unit": "fraction" if offset == 0 else "INR",
                           "observed_value": .6 if offset == 0 else 5000,
                           "threshold": .2 if offset == 0 else 1500, "baseline_value": .05 if offset == 0 else 1000,
                           "explanation": "<script>Not executable</script>", "current_orders": 20,
                           "baseline_orders": 200, "baseline_windows": 10}],
            })
        self.page.route("**/api/v1/anomalies?*", alerts)
        self.page.goto(BASE)
        self.loaded()
        expect(self.page.locator("#anomaly-status")).to_contain_text("6 signals")
        expect(self.page.locator(".signal-evidence")).to_contain_text("Observed 60.0%")
        expect(self.page.locator("#anomaly-items script")).to_have_count(0)
        self.page.locator("#alerts-next").click()
        expect(self.page.locator(".signal-card h3")).to_contain_text("Completed revenue spike")
        expect(self.page.locator("#alerts-next")).to_be_disabled()
        expect(self.page.locator("#alerts-previous")).to_be_enabled()

    def test_insufficient_baseline_and_detector_failure(self):
        self.mock()
        self.page.route("**/api/v1/anomalies?*", lambda route: route.fulfill(json={
            "checked_count": 6, "insufficient_count": 6, "flagged_count": 0,
            "last_successful_run": datetime.now(timezone.utc).isoformat(), "has_more": False, "items": [],
        }))
        self.page.goto(BASE)
        self.loaded()
        expect(self.page.locator("#anomaly-status")).to_contain_text("Building a baseline")
        self.page.unroute("**/api/v1/anomalies?*")
        self.page.route("**/api/v1/anomalies?*", lambda route: route.fulfill(status=503, json={"detail": "Unavailable"}))
        self.page.locator("#refresh").click()
        expect(self.page.locator("#anomaly-status")).to_contain_text("Detector unavailable")
        expect(self.page.locator("#error")).to_be_hidden()
        expect(self.page.locator("#orders")).to_have_text("4")


if __name__ == "__main__":
    result = unittest.main(verbosity=2, exit=False).result
    output = Path("runtime/evidence/browser.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(result="passed" if result.wasSuccessful() else "failed",
        tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
        completed_at=datetime.now(timezone.utc).isoformat()), indent=2), encoding="utf-8")
    sys.exit(0 if result.wasSuccessful() else 1)
