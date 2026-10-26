from __future__ import annotations

import json
from pathlib import Path

from .gui import App, TEXT


def validate_gui(width: int, height: int, output: Path) -> dict[str, object]:
    if width < 800 or height < 600:
        raise ValueError("GUI validation size is too small")
    app = App()
    try:
        app.geometry(f"{width}x{height}+0+0")
        app.update()
        checks: dict[str, bool] = {
            "window_width": app.winfo_width() >= width,
            "window_height": app.winfo_height() >= height,
            "app_entry_visible": bool(app.app_entry.winfo_ismapped()),
            "build_button_visible": bool(app.build_button.winfo_ismapped()),
            "resolve_button_visible": bool(app.resolve_button.winfo_ismapped()),
            "result_visible": bool(app.result.winfo_ismapped()),
            "ja_idle": app.status.get() == TEXT["ja"]["idle"],
        }
        app.language.set("en")
        app._translate()
        app.update_idletasks()
        checks["en_title"] = app.title() == TEXT["en"]["title"]
        checks["en_idle"] = app.status.get() == TEXT["en"]["idle"]
        checks["content_within_width"] = max(
            widget.winfo_x() + widget.winfo_width()
            for widget in (app.app_entry, app.build_button, app.resolve_button, app.result)
        ) <= app.winfo_width()
        checks["content_within_height"] = max(
            widget.winfo_y() + widget.winfo_height()
            for widget in (app.app_entry, app.build_button, app.resolve_button, app.result)
        ) <= app.winfo_height()
        payload: dict[str, object] = {
            "schema_version": 1,
            "requested_size": {"width": width, "height": height},
            "observed_size": {"width": app.winfo_width(), "height": app.winfo_height()},
            "checks": checks,
            "status": "PASS" if all(checks.values()) else "FAIL",
        }
    finally:
        app.destroy()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload
