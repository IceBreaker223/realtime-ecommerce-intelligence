"""Record a silent walkthrough of the running dashboard using its actual API data."""
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    output = Path("runtime/walkthrough")
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as driver:
        browser = driver.chromium.launch(
            channel=os.getenv("BROWSER_CHANNEL", "msedge" if os.name == "nt" else "chromium")
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            record_video_dir=str(output),
            record_video_size={"width": 1440, "height": 1000},
            timezone_id="Asia/Kolkata",
        )
        page = context.new_page()
        video = page.video
        try:
            page.goto(os.getenv("DASHBOARD_URL", "http://localhost:8000"))
            expect(page.locator("#metrics")).to_have_attribute("aria-busy", "false")
            expect(page.locator("#error")).to_be_hidden()
            page.locator("#auto-refresh").uncheck()
            page.get_by_role("button", name="1 hour", exact=True).click()
            expect(page.locator("#chart-period")).to_have_text("over the last 1 hour")
            page.wait_for_timeout(12000)
            page.locator("#performance").scroll_into_view_if_needed()
            page.wait_for_timeout(8000)
            page.get_by_role("button", name="Categories", exact=True).click()
            page.wait_for_timeout(8000)
            page.locator(".anomaly-panel").scroll_into_view_if_needed()
            page.wait_for_timeout(16000)
            page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
            page.wait_for_timeout(4000)
            page.get_by_role("button", name="24 hours", exact=True).click()
            page.wait_for_timeout(8000)
        finally:
            context.close()
            try:
                video.save_as(str(output / "ab-insights.webm"))
                video.delete()
            finally:
                browser.close()
    print(f"Saved silent dashboard walkthrough: {output / 'ab-insights.webm'}")


if __name__ == "__main__":
    main()
