"""Exports portfolio assets in one command (starts its own temporary server):

    outputs/thumbnail.png              1600x1200 Contra cover (from /dashboard?mode=thumbnail)
    outputs/dashboard_full.png         full results dashboard
    outputs/flowchart_pipeline.png     research pipeline (auto-generated from the code)
    outputs/flowchart_n8n.png          n8n workflow (auto-generated from the workflow file)
    outputs/review_page.png            review page showing the latest lead
    outputs/flowchart_trace.png        step-by-step trace of the latest lead, if any
    docs/architecture.md               Mermaid sources for GitHub README rendering

Setup once:  pip install playwright  &&  python -m playwright install chromium
Run:         python -m scripts.export_assets
"""
from __future__ import annotations

import socket
import sys
import threading
import time

from app.config import get_settings
from app.flowchart import latest_lead_id, write_docs


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(port: int):
    import uvicorn
    config = uvicorn.Config("app.main:app", host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            return server
        time.sleep(0.1)
    sys.exit("Server did not start.")


def main() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("Playwright is missing. Run: pip install playwright && python -m playwright install chromium")

    settings = get_settings()
    out = settings.outputs_dir
    out.mkdir(parents=True, exist_ok=True)
    print(f"Wrote {write_docs(settings)}")

    port = _free_port()
    server = _start_server(port)
    base = f"http://127.0.0.1:{port}"
    has_eval = settings.eval_results_path.exists()

    shots = [
        ("thumbnail.png", "/dashboard?mode=thumbnail", {"width": 1600, "height": 1200}, 1, False),
        ("dashboard_full.png", "/dashboard", {"width": 1440, "height": 900}, 2, True),
        ("flowchart_pipeline.png", "/flowchart?view=pipeline&export=1", {"width": 1800, "height": 900}, 2, True),
        ("flowchart_n8n.png", "/flowchart?view=n8n&export=1", {"width": 1500, "height": 700}, 2, True),
        ("review_page.png", "/review", {"width": 1440, "height": 1000}, 2, False),
    ]
    lid = latest_lead_id(settings)
    if lid:
        shots.append(("flowchart_trace.png", f"/flowchart?view=trace&export=1&lead={lid}", {"width": 1200, "height": 900}, 2, True))
        shots[-2] = ("review_page.png", f"/review?lead={lid}", {"width": 1440, "height": 1000}, 2, False)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for name, path, viewport, scale, full in shots:
                page = browser.new_page(viewport=viewport, device_scale_factor=scale)
                page.goto(base + path, wait_until="networkidle")
                if not path.startswith("/review"):
                    page.wait_for_function("window.__ready === true", timeout=30_000)
                page.wait_for_timeout(400)
                if path.startswith("/flowchart"):
                    page.locator("main.page").screenshot(path=str(out / name))
                else:
                    page.screenshot(path=str(out / name), full_page=full)
                page.close()
                print(f"Saved outputs/{name}")
            browser.close()
    finally:
        server.should_exit = True
        time.sleep(0.5)

    if not has_eval:
        print("\nNote: no evaluation results found, so the thumbnail is marked as a preview. "
              "Run `python -m eval.run_eval --judge` first, then export again.")


if __name__ == "__main__":
    main()
