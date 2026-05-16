"""
TalkFlow first-run setup wizard.

A 3-step Tk dialog that runs when config.json is missing:
  1. Pick transcription backend (Groq cloud / self-hosted server)
  2. Pick microphone
  3. Pick push-to-talk hotkey

The dialog returns a fully-populated config dict that the caller should
save. Returning None means the user cancelled — the caller should still
launch the main GUI with defaults so the user can configure manually.

This is intentionally self-contained (its own mainloop) so we can run it
before instantiating TalkFlowGUI.
"""

from __future__ import annotations

import platform
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Callable


# Imports from sibling modules are done lazily inside callbacks so the
# wizard can render even if optional deps (e.g. sounddevice) are missing.


class SetupWizard:
    PAGES = ("backend", "mic", "hotkey", "done")

    def __init__(self, defaults: dict):
        self.defaults = defaults
        self.result: Optional[dict] = None

        self.root = tk.Tk()
        self.root.title("TalkFlow Setup")
        self.root.geometry("560x460")
        self.root.resizable(False, False)

        # Working copy of config we'll mutate as the user clicks Next
        self.cfg = dict(defaults)

        self._page_index = 0
        self._build_chrome()
        self._render_page()

        # Center on screen
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - 560) // 2
        y = (self.root.winfo_screenheight() - 460) // 2
        self.root.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------------ chrome
    def _build_chrome(self):
        header = ttk.Frame(self.root, padding=(20, 15, 20, 5))
        header.pack(fill="x")
        ttk.Label(header, text="Welcome to TalkFlow",
                  font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(header,
                  text="A few quick questions and you'll be ready to dictate.",
                  foreground="gray").pack(anchor="w")
        ttk.Separator(self.root, orient="horizontal").pack(fill="x", padx=20, pady=(5, 0))

        self.body = ttk.Frame(self.root, padding=20)
        self.body.pack(fill="both", expand=True)

        footer = ttk.Frame(self.root, padding=(20, 5, 20, 15))
        footer.pack(fill="x", side="bottom")
        self.step_label = ttk.Label(footer, text="", foreground="gray")
        self.step_label.pack(side="left")
        self.next_btn = ttk.Button(footer, text="Next →", command=self._on_next)
        self.next_btn.pack(side="right")
        self.back_btn = ttk.Button(footer, text="← Back", command=self._on_back)
        self.back_btn.pack(side="right", padx=(0, 8))
        ttk.Button(footer, text="Skip", command=self._on_skip).pack(side="right", padx=(0, 8))

    def _render_page(self):
        for w in self.body.winfo_children():
            w.destroy()
        page = self.PAGES[self._page_index]
        self.step_label.config(text=f"Step {self._page_index + 1} of {len(self.PAGES)}")
        self.back_btn.config(state="normal" if self._page_index > 0 else "disabled")
        getattr(self, f"_page_{page}")()

    # ------------------------------------------------------------------ pages
    def _page_backend(self):
        ttk.Label(self.body, text="Where should transcription happen?",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 12))

        self.backend_var = tk.StringVar(value=self.cfg.get("backend", "groq"))

        groq = ttk.Radiobutton(self.body, variable=self.backend_var, value="groq",
                               text="Groq Cloud  (recommended — fastest, no GPU needed)")
        groq.pack(anchor="w", pady=4)
        ttk.Label(self.body, text="    Requires a free Groq API key from console.groq.com",
                  foreground="gray").pack(anchor="w")

        ttk.Frame(self.body, height=8).pack()

        srv = ttk.Radiobutton(self.body, variable=self.backend_var, value="server",
                              text="Self-Hosted Server  (your own GPU box running Whisper)")
        srv.pack(anchor="w", pady=4)
        ttk.Label(self.body, text="    Requires the TalkFlow Docker server reachable on your network",
                  foreground="gray").pack(anchor="w")

        ttk.Frame(self.body, height=12).pack()

        # Conditional fields
        creds = ttk.LabelFrame(self.body, text="  Connection details  ", padding=10)
        creds.pack(fill="x")

        ttk.Label(creds, text="Groq API key:").grid(row=0, column=0, sticky="w", pady=4)
        self.groq_var = tk.StringVar(value=self.cfg.get("groq_api_key", ""))
        ttk.Entry(creds, textvariable=self.groq_var, show="•", width=42).grid(
            row=0, column=1, sticky="ew", padx=8, pady=4)

        ttk.Label(creds, text="Server host:port:").grid(row=1, column=0, sticky="w", pady=4)
        self.server_var = tk.StringVar(value=self.cfg.get("server", ""))
        ttk.Entry(creds, textvariable=self.server_var, width=42).grid(
            row=1, column=1, sticky="ew", padx=8, pady=4)
        creds.columnconfigure(1, weight=1)

    def _page_mic(self):
        ttk.Label(self.body, text="Which microphone should TalkFlow listen to?",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 12))

        try:
            from audio_devices import list_microphones, test_microphone
        except Exception:
            list_microphones = lambda: []  # noqa
            test_microphone = None

        devs = list_microphones()
        self._mic_choices = [("System Default", None)] + [
            (f"{d['name']}  ({d['channels']}ch @ {d['rate']}Hz)", d["index"]) for d in devs
        ]
        labels = [c[0] for c in self._mic_choices]

        self.mic_var = tk.StringVar(value=labels[0])
        # Preselect current config if matching
        cur_idx = self.cfg.get("mic_device")
        for label, idx in self._mic_choices:
            if idx == cur_idx:
                self.mic_var.set(label)
                break

        ttk.Combobox(self.body, textvariable=self.mic_var, values=labels,
                     state="readonly", width=55).pack(anchor="w", pady=4)

        ttk.Frame(self.body, height=8).pack()

        row = ttk.Frame(self.body)
        row.pack(fill="x", pady=8)
        self.mic_status = ttk.Label(row, text="(no test run yet)", foreground="gray")
        self.mic_status.pack(side="right")

        def do_test():
            if test_microphone is None:
                self.mic_status.config(text="sounddevice not installed", foreground="red")
                return
            label = self.mic_var.get()
            idx = dict(self._mic_choices).get(label)
            self.mic_status.config(text="Recording 2s…", foreground="orange")

            def done(ok, msg):
                self.mic_status.config(text=msg, foreground="green" if ok else "red")

            test_microphone(idx, duration=2.0, on_done=done)

        ttk.Button(row, text="Test mic (speak for 2s)", command=do_test).pack(side="left")

        if platform.system() == "Darwin":
            ttk.Label(self.body,
                      text="macOS: you'll be asked for microphone permission the first time.",
                      foreground="gray", wraplength=500).pack(anchor="w", pady=(12, 0))

    def _page_hotkey(self):
        ttk.Label(self.body, text="Pick a push-to-talk hotkey",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 12))
        ttk.Label(self.body,
                  text="Hold this key to record, release to transcribe. Pick something\n"
                       "you won't hit by accident — F9 is a good default.",
                  foreground="gray").pack(anchor="w", pady=(0, 12))

        presets = [("F9", "f9"), ("F8", "f8"), ("F10", "f10"),
                   ("Right Ctrl", "ctrl_r"), ("Right Alt", "alt_r"),
                   ("Ctrl+Shift+D", "ctrl+shift+d")]
        self.hotkey_var = tk.StringVar(value=self.cfg.get("hotkey", "f9"))
        for label, value in presets:
            ttk.Radiobutton(self.body, text=label, variable=self.hotkey_var,
                            value=value).pack(anchor="w", pady=2)

        ttk.Frame(self.body, height=8).pack()
        ttk.Label(self.body, text="You can change this any time from Settings.",
                  foreground="gray").pack(anchor="w")

        if platform.system() == "Darwin":
            ttk.Label(self.body,
                      text="macOS: TalkFlow needs Accessibility permission to type\n"
                           "text into other apps. We'll guide you through that next.",
                      foreground="gray", wraplength=500).pack(anchor="w", pady=(12, 0))

    def _page_done(self):
        ttk.Label(self.body, text="You're all set!",
                  font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 12))
        backend = "Groq Cloud" if self.cfg.get("backend") == "groq" else "Self-hosted server"
        mic = self.cfg.get("mic_device_name", "System Default")
        hk = self.cfg.get("hotkey", "f9")
        summary = (f"Backend:   {backend}\n"
                   f"Mic:       {mic}\n"
                   f"Hotkey:    {hk}")
        ttk.Label(self.body, text=summary, font=("Courier", 11),
                  justify="left").pack(anchor="w", pady=4)
        ttk.Label(self.body,
                  text="Click Finish to open TalkFlow. You can change any of these\n"
                       "later from the settings window or system-tray menu.",
                  foreground="gray", wraplength=500).pack(anchor="w", pady=(16, 0))
        self.next_btn.config(text="Finish ✓")

    # ------------------------------------------------------------------ nav
    def _capture_current_page(self) -> bool:
        page = self.PAGES[self._page_index]
        if page == "backend":
            self.cfg["backend"] = self.backend_var.get()
            self.cfg["groq_api_key"] = self.groq_var.get().strip()
            self.cfg["server"] = self.server_var.get().strip()
            if self.cfg["backend"] == "groq" and not self.cfg["groq_api_key"]:
                if not messagebox.askyesno(
                        "Groq API key missing",
                        "You picked Groq Cloud but didn't enter an API key.\n\n"
                        "Continue anyway? You can paste the key later in Settings."):
                    return False
            if self.cfg["backend"] == "server" and not self.cfg["server"]:
                messagebox.showerror("Server required",
                                     "Enter the server address (host:port).")
                return False
        elif page == "mic":
            label = self.mic_var.get()
            idx = dict(self._mic_choices).get(label)
            self.cfg["mic_device"] = idx
            self.cfg["mic_device_name"] = label
        elif page == "hotkey":
            self.cfg["hotkey"] = self.hotkey_var.get()
        return True

    def _on_next(self):
        if not self._capture_current_page():
            return
        if self._page_index >= len(self.PAGES) - 1:
            self.result = self.cfg
            self.root.destroy()
            return
        self._page_index += 1
        self._render_page()

    def _on_back(self):
        if self._page_index == 0:
            return
        self._page_index -= 1
        self.next_btn.config(text="Next →")
        self._render_page()

    def _on_skip(self):
        if messagebox.askyesno(
                "Skip setup?",
                "Skip the wizard and open settings directly?\n\n"
                "You can configure everything from the main window."):
            self.result = None
            self.root.destroy()

    def run(self) -> Optional[dict]:
        self.root.mainloop()
        return self.result


def run_wizard_if_first_run(defaults: dict, already_configured: bool) -> Optional[dict]:
    """Show the wizard only on a true first run; otherwise return None."""
    if already_configured:
        return None
    wizard = SetupWizard(defaults)
    return wizard.run()
