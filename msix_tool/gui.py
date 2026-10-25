from __future__ import annotations

import json
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .pipeline import run_pipeline


TEXT = {
    "ja": {
        "title": "Windows MSIX 自動ビルド & Identity 収集",
        "subtitle": "アプリ名からGitHubソースを確定し、既存手順でビルドします。不明点は安全にHOLDします。",
        "app": "アプリ名（必須）",
        "owner": "GitHub所有者",
        "workspace": "作業フォルダー",
        "browse": "参照",
        "build": "検索・ビルド・Identity収集",
        "resolve": "検索のみ",
        "idle": "アプリ名を入力してください",
        "running": "処理中…",
        "missing": "アプリ名を入力してください。",
        "done": "処理が完了しました。結果とHOLD項目を確認してください。",
        "open": "出力フォルダーを開く",
        "language": "Language",
    },
    "en": {
        "title": "Windows MSIX Auto Build & Identity Collector",
        "subtitle": "Resolve GitHub source by app name and use its existing build. Unknowns stop safely as HOLD.",
        "app": "Application name (required)",
        "owner": "GitHub owner",
        "workspace": "Workspace",
        "browse": "Browse",
        "build": "Resolve, build, and collect identity",
        "resolve": "Resolve only",
        "idle": "Enter an application name",
        "running": "Working…",
        "missing": "Enter an application name.",
        "done": "Completed. Review the result and HOLD items.",
        "open": "Open output folder",
        "language": "言語",
    },
}

PROGRESS_JA = {
    "Resolving GitHub repository": "GitHubリポジトリを検索しています",
    "Running the repository's existing Windows EXE build": "既存手順でWindows EXEをビルドしています",
    "MSIX build held because required approvals are incomplete": "必要な承認が不足しているためMSIX生成をHOLDしました",
    "Running the repository's existing MSIX build": "既存手順でMSIXをビルドしています",
    "Extracting identity from the generated MSIX": "生成したMSIXからIdentityを抽出しています",
}


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.geometry("900x680")
        self.minsize(760, 560)
        self.language = tk.StringVar(value="ja")
        self.app_name = tk.StringVar()
        self.owner = tk.StringVar(value="shihuiarenjinba-png")
        self.workspace = tk.StringVar(value=str(Path.home() / "Documents" / "MSIX-Workspace"))
        self.status = tk.StringVar()
        self.messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self.output_directory = ""
        self._build_widgets()
        self._translate()
        self.after(100, self._poll)

    def _build_widgets(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        header = ttk.Frame(self, padding=(22, 18, 22, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        self.title_label = ttk.Label(header, font=("Segoe UI", 18, "bold"))
        self.title_label.grid(row=0, column=0, sticky="w")
        self.subtitle_label = ttk.Label(header, wraplength=720)
        self.subtitle_label.grid(row=1, column=0, sticky="w", pady=(5, 0))
        self.language_box = ttk.Combobox(
            header, textvariable=self.language, values=("ja", "en"), state="readonly", width=5
        )
        self.language_box.grid(row=0, column=1, rowspan=2, sticky="ne")
        self.language_box.bind("<<ComboboxSelected>>", lambda _event: self._translate())
        body = ttk.Frame(self, padding=(22, 8, 22, 22))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(1, weight=1)
        body.rowconfigure(5, weight=1)
        self.app_label = ttk.Label(body)
        self.app_label.grid(row=0, column=0, sticky="w", pady=6)
        self.app_entry = ttk.Entry(body, textvariable=self.app_name)
        self.app_entry.grid(row=0, column=1, columnspan=2, sticky="ew", pady=6)
        self.owner_label = ttk.Label(body)
        self.owner_label.grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(body, textvariable=self.owner).grid(row=1, column=1, columnspan=2, sticky="ew", pady=6)
        self.workspace_label = ttk.Label(body)
        self.workspace_label.grid(row=2, column=0, sticky="w", pady=6)
        ttk.Entry(body, textvariable=self.workspace).grid(row=2, column=1, sticky="ew", pady=6)
        self.browse_button = ttk.Button(body, command=self._browse)
        self.browse_button.grid(row=2, column=2, padx=(8, 0), pady=6)
        buttons = ttk.Frame(body)
        buttons.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(12, 8))
        self.build_button = ttk.Button(buttons, command=lambda: self._start(True))
        self.build_button.pack(side="left")
        self.resolve_button = ttk.Button(buttons, command=lambda: self._start(False))
        self.resolve_button.pack(side="left", padx=8)
        self.open_button = ttk.Button(buttons, command=self._open_output, state="disabled")
        self.open_button.pack(side="right")
        ttk.Label(body, textvariable=self.status).grid(row=4, column=0, columnspan=3, sticky="w", pady=5)
        self.result = tk.Text(body, wrap="word", font=("Consolas", 10), state="disabled")
        self.result.grid(row=5, column=0, columnspan=3, sticky="nsew")
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.result.yview)
        scrollbar.grid(row=5, column=3, sticky="ns")
        self.result.configure(yscrollcommand=scrollbar.set)

    def _t(self, key: str) -> str:
        return TEXT[self.language.get()][key]

    def _translate(self) -> None:
        self.title(self._t("title"))
        self.title_label.configure(text=self._t("title"))
        self.subtitle_label.configure(text=self._t("subtitle"))
        self.app_label.configure(text=self._t("app"))
        self.owner_label.configure(text=self._t("owner"))
        self.workspace_label.configure(text=self._t("workspace"))
        self.browse_button.configure(text=self._t("browse"))
        self.build_button.configure(text=self._t("build"))
        self.resolve_button.configure(text=self._t("resolve"))
        self.open_button.configure(text=self._t("open"))
        if not self.status.get() or self.status.get() in {
            TEXT["ja"]["idle"],
            TEXT["en"]["idle"],
        }:
            self.status.set(self._t("idle"))

    def _browse(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.workspace.get())
        if selected:
            self.workspace.set(selected)

    def _start(self, execute_build: bool) -> None:
        if not self.app_name.get().strip():
            messagebox.showwarning(self._t("title"), self._t("missing"))
            self.app_entry.focus_set()
            return
        self.build_button.configure(state="disabled")
        self.resolve_button.configure(state="disabled")
        self.open_button.configure(state="disabled")
        self.status.set(self._t("running"))
        self._set_result("")
        thread = threading.Thread(target=self._worker, args=(execute_build,), daemon=True)
        thread.start()

    def _worker(self, execute_build: bool) -> None:
        try:
            report = run_pipeline(
                app_name=self.app_name.get(),
                workspace=Path(self.workspace.get()),
                owner=self.owner.get(),
                execute_build=execute_build,
                progress=lambda message: self.messages.put(("progress", message)),
            )
            self.messages.put(("done", report))
        except Exception as exc:  # GUI boundary: retain an actionable message.
            self.messages.put(("error", str(exc)))

    def _poll(self) -> None:
        try:
            while True:
                kind, value = self.messages.get_nowait()
                if kind == "progress":
                    message = str(value)
                    if self.language.get() == "ja":
                        message = (
                            "ソースを取得しています: " + message.removeprefix("Checking out ")
                            if message.startswith("Checking out ")
                            else PROGRESS_JA.get(message, message)
                        )
                    self.status.set(message)
                elif kind == "error":
                    self.status.set("ERROR")
                    self._set_result(str(value))
                    self._unlock()
                else:
                    report = value
                    self.status.set(f"{report.status} | {self._t('done')}")
                    self._set_result(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
                    self.output_directory = str(Path(report.output_json).parent) if report.output_json else ""
                    if self.output_directory:
                        self.open_button.configure(state="normal")
                    self._unlock()
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _unlock(self) -> None:
        self.build_button.configure(state="normal")
        self.resolve_button.configure(state="normal")

    def _set_result(self, text: str) -> None:
        self.result.configure(state="normal")
        self.result.delete("1.0", "end")
        self.result.insert("1.0", text)
        self.result.configure(state="disabled")

    def _open_output(self) -> None:
        if self.output_directory and Path(self.output_directory).is_dir():
            os.startfile(self.output_directory)  # type: ignore[attr-defined]


def main() -> None:
    App().mainloop()
