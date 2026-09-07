"""Widgets reutilizaveis da interface."""

import customtkinter as ctk

from .theme import (
    BG_INPUT,
    CLR_ACCENT,
    CLR_ACCENT_LIGHT,
    CLR_BORDER,
    CLR_MUTED,
    CLR_TEXT,
    FONT_FAMILY,
)

class FormatCard(ctk.CTkFrame):
    """Selectable card for format choice (MP3/MP4)."""

    def __init__(self, parent, icon: str, title: str, subtitle: str,
                 value: str, variable: ctk.StringVar, command=None, **kwargs):
        super().__init__(parent, corner_radius=12, border_width=2,
                         fg_color=BG_INPUT, border_color=CLR_BORDER,
                         cursor="hand2", **kwargs)

        self._value = value
        self._variable = variable
        self._command = command
        self._selected = False

        self.grid_columnconfigure(1, weight=1)

        self._icon_label = ctk.CTkLabel(
            self, text=icon, font=(FONT_FAMILY, 13, "bold"),
            text_color=CLR_MUTED, width=48)
        self._icon_label.grid(row=0, column=0, rowspan=2, padx=(16, 8), pady=14)

        self._title_label = ctk.CTkLabel(
            self, text=title, font=(FONT_FAMILY, 13, "bold"),
            text_color=CLR_TEXT, anchor="w")
        self._title_label.grid(row=0, column=1, sticky="sw", padx=(0, 16), pady=(14, 0))

        self._sub_label = ctk.CTkLabel(
            self, text=subtitle, font=(FONT_FAMILY, 11),
            text_color=CLR_MUTED, anchor="w")
        self._sub_label.grid(row=1, column=1, sticky="nw", padx=(0, 16), pady=(0, 14))

        for widget in [self, self._icon_label, self._title_label, self._sub_label]:
            widget.bind("<Button-1>", self._on_click)
            widget.configure(cursor="hand2")

        self._variable.trace_add("write", lambda *_: self._update_visual())
        self._update_visual()

    def _on_click(self, _event=None):
        self._variable.set(self._value)
        if self._command:
            self._command()

    def _update_visual(self):
        selected = self._variable.get() == self._value
        if selected == self._selected:
            return
        self._selected = selected
        if selected:
            self.configure(border_color=CLR_ACCENT, fg_color="#1d1b35")
            self._icon_label.configure(text_color=CLR_ACCENT_LIGHT)
        else:
            self.configure(border_color=CLR_BORDER, fg_color=BG_INPUT)
            self._icon_label.configure(text_color=CLR_MUTED)


class HoverButton(ctk.CTkButton):
    """Button with hover brightness shift and press feedback."""

    def __init__(self, master, base_color: str, hover_color: str,
                 press_color: str | None = None, **kwargs):
        kwargs.setdefault("cursor", "hand2")
        kwargs.setdefault("corner_radius", 10)
        super().__init__(master, fg_color=base_color, hover_color=hover_color, **kwargs)
        self._base = base_color
        self._hover = hover_color
        self._press = press_color or hover_color
        self.bind("<ButtonPress-1>", self._apply_press_color)
        self.bind("<ButtonRelease-1>", self._restore_base_color)

    def _apply_press_color(self, _e=None):
        if str(self.cget("state")) != "disabled":
            self.configure(fg_color=self._press)

    def _restore_base_color(self, _e=None):
        if str(self.cget("state")) != "disabled":
            self.configure(fg_color=self._base)
