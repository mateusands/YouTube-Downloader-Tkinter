import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import messagebox
from typing import Any
from urllib.parse import parse_qs, urlparse

import customtkinter as ctk
import yt_dlp


APP_TITLE = "Media Downloader"
BASE_DOWNLOADS_DIR = Path(__file__).resolve().parent.parent / "Downloads"
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
APP_ICON_PATH = ASSETS_DIR / "media-downloader-icon.png"
APP_ICON_ICO_PATH = ASSETS_DIR / "media-downloader-icon.ico"
SUPPORTED_SITES_URL = "https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md"
SUPPORTED_PLATFORM_NAMES = (
    "YouTube", "Vimeo", "TikTok", "Instagram", "SoundCloud", "Dailymotion",
)
DOWNLOAD_FOLDERS = {
    ("mp3", False): BASE_DOWNLOADS_DIR / "audios_unicos",
    ("mp4", False): BASE_DOWNLOADS_DIR / "videos_unicos",
    ("mp3", True):  BASE_DOWNLOADS_DIR / "playlist_audio",
    ("mp4", True):  BASE_DOWNLOADS_DIR / "playlist_video",
}

# ── Palette ───────────────────────────────────────────────────────────────────
BG_DARK       = "#0f0f0f"
BG_CARD       = "#1a1a1a"
BG_INPUT      = "#262626"
BG_HOVER      = "#2a2a2a"
CLR_TEXT      = "#ffffff"
CLR_MUTED     = "#888888"
CLR_BORDER    = "#333333"
CLR_ACCENT    = "#6d5dfc"
CLR_ACCENT_DARK = "#5144d9"
CLR_ACCENT_LIGHT = "#8b7cff"
CLR_GREEN     = "#22c55e"
CLR_ERROR     = "#ef4444"
FONT_FAMILY   = "Segoe UI"


# ── Data / backend ────────────────────────────────────────────────────────────

@dataclass
class DownloadSummary:
    downloaded_count: int = 0
    failed_items: list[str] = field(default_factory=list)
    total_items: int = 0
    target_dir: str = ""
    playlist_mode: bool = False


class ReportingLogger:
    def __init__(self, event_queue: queue.Queue, summary: DownloadSummary):
        self._q = event_queue
        self._summary = summary

    def debug(self, _: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        self._capture(msg)

    def error(self, msg: str) -> None:
        self._capture(msg)

    def _capture(self, msg: str) -> None:
        # Prefixo sem o espaço: o .strip() anterior já removeu o espaço de
        # "ERROR: " quando a mensagem vinha vazia, e "ERROR:" virava um item.
        cleaned = msg.strip().removeprefix("ERROR:").strip()
        if cleaned and cleaned not in self._summary.failed_items:
            self._summary.failed_items.append(cleaned)
            self._q.put({"type": "status", "message": "Um item falhou — continuando com os demais..."})


class DownloadManager:
    def __init__(self, event_queue: queue.Queue):
        self._q = event_queue

    def download(self, url: str, file_format: str) -> None:
        summary = DownloadSummary()
        try:
            playlist_mode = self._url_is_playlist(url)
            info = self._extract_info(url, playlist_mode)

            if playlist_mode and not self._is_playlist_result(info):
                playlist_mode = False

            target_dir = self._ensure_output_dir(file_format, playlist_mode)
            summary.target_dir = str(target_dir)
            summary.playlist_mode = playlist_mode
            summary.total_items = self._count_items(info, playlist_mode)

            label = "colecao" if playlist_mode else "midia"
            self._emit("status", message=f"Preparando download ({label})...")
            self._emit(
                "meta",
                total_items=summary.total_items,
                playlist_mode=playlist_mode,
                target_dir=str(target_dir),
            )

            opts = self._build_opts(target_dir, file_format, playlist_mode, summary)
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])

            self._emit("done", summary=summary)
        except Exception as exc:
            self._emit("error", message=str(exc))

    @staticmethod
    def _url_is_playlist(url: str) -> bool:
        try:
            p = urlparse(url)
            return p.path.rstrip("/") == "/playlist" and bool(parse_qs(p.query).get("list"))
        except Exception:
            return False

    def _extract_info(self, url: str, playlist_mode: bool) -> dict[str, Any]:
        self._emit("status", message="Analisando link...")
        opts = {
            "quiet": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "noplaylist": not playlist_mode,
            "ignoreerrors": True,
            "remote_components": ["ejs:github"],
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            raise ValueError("Nao foi possivel obter informacoes do link informado.")
        return info

    def _build_opts(
        self,
        target_dir: Path,
        file_format: str,
        playlist_mode: bool,
        summary: DownloadSummary,
    ) -> dict[str, Any]:
        if playlist_mode:
            outtmpl = str(target_dir / "%(playlist_title,playlist|Playlist)s" / "%(title)s.%(ext)s")
        else:
            outtmpl = str(target_dir / "%(title)s.%(ext)s")

        opts: dict[str, Any] = {
            "outtmpl": outtmpl,
            "ignoreerrors": True,
            "noplaylist": not playlist_mode,
            "progress_hooks": [self._make_progress_hook(summary)],
            "quiet": True,
            "no_warnings": True,
            "concurrent_fragment_downloads": 1,
            "logger": ReportingLogger(self._q, summary),
            "remote_components": ["ejs:github"],
        }

        if file_format == "mp3":
            opts.update({
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            })
        else:
            opts.update({
                "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
                "merge_output_format": "mp4",
            })

        return opts

    def _make_progress_hook(self, summary: DownloadSummary):
        seen: set[str] = set()

        def hook(data: dict[str, Any]) -> None:
            status = data.get("status")
            info_dict = data.get("info_dict") or {}
            title = info_dict.get("title") or data.get("filename") or "Arquivo"
            idx = info_dict.get("playlist_index")

            if status == "downloading":
                dl = data.get("downloaded_bytes", 0)
                total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
                item_pct = (dl / total * 100) if total else 0

                if summary.total_items > 1:
                    overall = (summary.downloaded_count + item_pct / 100) / summary.total_items * 100
                else:
                    overall = item_pct

                suffix = f" ({idx}/{summary.total_items})" if idx and summary.total_items > 1 else ""
                self._emit("progress", progress=max(0.0, min(overall, 100.0)),
                           message=f"Baixando: {title}{suffix}")

            elif status == "finished":
                uid = info_dict.get("id") or data.get("filename") or title
                if uid not in seen:
                    seen.add(uid)
                    summary.downloaded_count += 1
                overall = (summary.downloaded_count / summary.total_items * 100
                           if summary.total_items else 100.0)
                self._emit("progress", progress=max(0.0, min(overall, 100.0)),
                           message=f"Processando: {title}")

        return hook

    def _ensure_output_dir(self, file_format: str, playlist_mode: bool) -> Path:
        path = DOWNLOAD_FOLDERS[(file_format, playlist_mode)]
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _is_playlist_result(info: dict[str, Any]) -> bool:
        return bool(info.get("entries")) or info.get("_type") == "playlist"

    @staticmethod
    def _count_items(info: dict[str, Any], playlist_mode: bool) -> int:
        if not playlist_mode:
            return 1
        return max(sum(1 for e in (info.get("entries") or []) if e), 1)

    def _emit(self, event_type: str, **payload: Any) -> None:
        self._q.put({"type": event_type, **payload})


# ── UI ────────────────────────────────────────────────────────────────────────

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


class MediaDownloaderApp:
    _W, _H = 860, 760

    def __init__(self, root: ctk.CTk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.minsize(740, 700)
        self.root.configure(fg_color=BG_DARK)
        self._app_icon = tk.PhotoImage(file=str(APP_ICON_PATH))
        self._header_icon = self._app_icon.subsample(8, 8)
        if sys.platform.startswith("win"):
            self.root.iconbitmap(default=str(APP_ICON_ICO_PATH))
        self.root.iconphoto(True, self._app_icon)

        self._q: queue.Queue = queue.Queue()
        self._manager = DownloadManager(self._q)
        self._thread: threading.Thread | None = None
        self._metadata_thread: threading.Thread | None = None
        self._metadata_cover_labels: dict[str, ctk.CTkLabel] = {}
        self._metadata_cover_images: dict[str, ctk.CTkImage] = {}
        self._metadata_embedded_labels: dict[str, tuple[ctk.CTkLabel, ctk.CTkLabel]] = {}
        self._metadata_embedded_images: dict[str, ctk.CTkImage] = {}

        self._build_ui()
        self._center(self._W, self._H)
        self.root.after(100, self._poll)

    def _center(self, w: int, h: int) -> None:
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._build_header()
        self._build_body()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self.root, fg_color=BG_DARK, corner_radius=0, height=108)
        header.pack(fill="x")
        header.pack_propagate(False)

        inner = ctk.CTkFrame(header, fg_color="transparent")
        inner.pack(fill="x", padx=32, pady=(18, 0))

        title_row = ctk.CTkFrame(inner, fg_color="transparent")
        title_row.pack(anchor="w")

        tk.Label(
            title_row, image=self._header_icon, bg=BG_DARK,
            borderwidth=0, highlightthickness=0,
        ).pack(side="left", padx=(0, 12))

        ctk.CTkLabel(
            title_row, text=APP_TITLE,
            font=(FONT_FAMILY, 24, "bold"), text_color=CLR_TEXT,
        ).pack(side="left")

        ctk.CTkLabel(
            inner,
            text="Baixe video ou audio de plataformas compativeis com o yt-dlp.",
            font=(FONT_FAMILY, 12), text_color=CLR_MUTED,
        ).pack(anchor="w", pady=(6, 0))

    def _build_body(self) -> None:
        card = ctk.CTkFrame(self.root, fg_color=BG_CARD, corner_radius=16, border_width=1,
                            border_color=CLR_BORDER)
        card.pack(fill="both", expand=True, padx=24, pady=(12, 24))

        container = ctk.CTkFrame(card, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=28, pady=24)

        self._build_url_section(container)
        self._divider(container)
        self._build_format_section(container)
        self._divider(container)
        self._build_button_section(container)
        self._divider(container)
        self._build_progress_section(container)

    def _divider(self, parent) -> None:
        ctk.CTkFrame(parent, fg_color=CLR_BORDER, height=1, corner_radius=0).pack(
            fill="x", pady=16)

    # ── URL Section ───────────────────────────────────────────────────────────

    def _build_url_section(self, parent) -> None:
        ctk.CTkLabel(
            parent, text="Link da midia",
            font=(FONT_FAMILY, 13, "bold"), text_color=CLR_TEXT,
        ).pack(anchor="w")

        input_frame = ctk.CTkFrame(parent, fg_color=BG_INPUT, corner_radius=10,
                                   border_width=2, border_color=CLR_BORDER)
        input_frame.pack(fill="x", pady=(8, 0))
        self._input_frame = input_frame

        inner = ctk.CTkFrame(input_frame, fg_color="transparent")
        inner.pack(fill="x", padx=4, pady=4)
        inner.grid_columnconfigure(0, weight=1)

        self.url_var = ctk.StringVar()
        self.url_entry = ctk.CTkEntry(
            inner, textvariable=self.url_var,
            font=(FONT_FAMILY, 12),
            placeholder_text="https://exemplo.com/video",
            fg_color="transparent", border_width=0,
            text_color=CLR_TEXT, placeholder_text_color=CLR_MUTED,
            height=36,
        )
        self.url_entry.grid(row=0, column=0, sticky="ew", padx=(12, 4))

        self.paste_btn = HoverButton(
            inner, text="Colar", width=70, height=32,
            font=(FONT_FAMILY, 11, "bold"),
            base_color=CLR_BORDER, hover_color="#444444", press_color="#555555",
            text_color=CLR_TEXT, command=self._paste_url,
        )
        self.paste_btn.grid(row=0, column=1, padx=(0, 4))

        self.url_entry.bind("<FocusIn>", lambda _: input_frame.configure(border_color=CLR_ACCENT))
        self.url_entry.bind("<FocusOut>", lambda _: input_frame.configure(border_color=CLR_BORDER))

        self._url_hint = ctk.CTkLabel(
            parent, text="Cole um link de video, audio ou colecao.",
            font=(FONT_FAMILY, 11), text_color=CLR_MUTED,
        )
        self._url_hint.pack(anchor="w", pady=(4, 0))

        self._build_supported_sites_section(parent)

    def _build_supported_sites_section(self, parent) -> None:
        ctk.CTkLabel(
            parent, text="Plataformas populares compativeis",
            font=(FONT_FAMILY, 11, "bold"), text_color=CLR_TEXT,
        ).pack(anchor="w", pady=(14, 0))

        sites_row = ctk.CTkFrame(parent, fg_color="transparent")
        sites_row.pack(anchor="w", pady=(7, 0))
        for site in SUPPORTED_PLATFORM_NAMES:
            ctk.CTkLabel(
                sites_row, text=site, font=(FONT_FAMILY, 10), text_color=CLR_MUTED,
                fg_color=BG_HOVER, corner_radius=8, padx=10, pady=5,
            ).pack(side="left", padx=(0, 6))

        link = ctk.CTkLabel(
            parent, text="Ver lista completa e atualizada do yt-dlp",
            font=(FONT_FAMILY, 10), text_color=CLR_ACCENT_LIGHT, cursor="hand2",
        )
        link.pack(anchor="w", pady=(8, 0))
        link.bind("<Button-1>", lambda _: self._open_supported_sites())

    @staticmethod
    def _open_supported_sites() -> None:
        webbrowser.open_new_tab(SUPPORTED_SITES_URL)

    def _paste_url(self) -> None:
        try:
            text = self.root.clipboard_get()
            self.url_var.set(text.strip())
        except tk.TclError:
            pass

    # ── Format Section ────────────────────────────────────────────────────────

    def _build_format_section(self, parent) -> None:
        ctk.CTkLabel(
            parent, text="Formato de saida",
            font=(FONT_FAMILY, 13, "bold"), text_color=CLR_TEXT,
        ).pack(anchor="w")

        self.format_var = ctk.StringVar(value="mp3")

        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(10, 0))
        row.grid_columnconfigure(0, weight=1)
        row.grid_columnconfigure(1, weight=1)

        self._mp3_card = FormatCard(
            row, icon="MP3", title="Audio MP3",
            subtitle="192 kbps — apenas audio",
            value="mp3", variable=self.format_var)
        self._mp3_card.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self._mp4_card = FormatCard(
            row, icon="MP4", title="Video MP4",
            subtitle="Melhor qualidade disponivel",
            value="mp4", variable=self.format_var)
        self._mp4_card.grid(row=0, column=1, sticky="ew", padx=(8, 0))

    # ── Button Section ────────────────────────────────────────────────────────

    def _build_button_section(self, parent) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(anchor="w")

        self.download_btn = HoverButton(
            row, text="Baixar midia",
            font=(FONT_FAMILY, 13, "bold"),
            base_color=CLR_ACCENT, hover_color=CLR_ACCENT_DARK, press_color="#4036aa",
            text_color="#ffffff", width=200, height=44,
            command=self.start_download,
        )
        self.download_btn.pack(side="left", padx=(0, 12))

        self.folder_btn = HoverButton(
            row, text="Abrir pasta",
            font=(FONT_FAMILY, 12),
            base_color="transparent", hover_color=BG_HOVER, press_color=CLR_BORDER,
            text_color=CLR_TEXT, border_width=2, border_color=CLR_BORDER,
            width=180, height=44,
            command=self.open_downloads_folder,
        )
        self.folder_btn.pack(side="left")

    # ── Progress Section ──────────────────────────────────────────────────────

    def _build_progress_section(self, parent) -> None:
        hdr = ctk.CTkFrame(parent, fg_color="transparent")
        hdr.pack(fill="x")

        ctk.CTkLabel(
            hdr, text="Progresso",
            font=(FONT_FAMILY, 13, "bold"), text_color=CLR_TEXT,
        ).pack(side="left")

        self.pct_var = ctk.StringVar(value="0%")
        self._pct_label = ctk.CTkLabel(
            hdr, textvariable=self.pct_var,
            font=(FONT_FAMILY, 13, "bold"), text_color=CLR_MUTED,
        )
        self._pct_label.pack(side="right")

        self.progress_var = ctk.DoubleVar(value=0)
        self.progress_bar = ctk.CTkProgressBar(
            parent, variable=self.progress_var,
            height=12, corner_radius=6,
            fg_color=CLR_BORDER, progress_color=CLR_ACCENT,
        )
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", pady=(10, 12))

        self.status_var = ctk.StringVar(value="Pronto para iniciar.")
        self._status_label = ctk.CTkLabel(
            parent, textvariable=self.status_var,
            font=(FONT_FAMILY, 12), text_color=CLR_TEXT,
            anchor="w", justify="left", wraplength=720,
        )
        self._status_label.pack(fill="x")

        self.info_var = ctk.StringVar(
            value="Os arquivos serao organizados automaticamente por formato e tipo.")
        ctk.CTkLabel(
            parent, textvariable=self.info_var,
            font=(FONT_FAMILY, 11), text_color=CLR_MUTED,
            anchor="w", justify="left", wraplength=720,
        ).pack(fill="x", pady=(4, 0))

    # ── Actions ───────────────────────────────────────────────────────────────

    def start_download(self) -> None:
        url = self.url_var.get().strip()
        if not self._valid_url(url):
            self._input_frame.configure(border_color=CLR_ERROR)
            self._url_hint.configure(
                text="URL invalida — informe um link HTTP ou HTTPS valido.",
                text_color=CLR_ERROR)
            self.root.after(3000, self._reset_url_hint)
            return

        self._input_frame.configure(border_color=CLR_BORDER)
        self._reset_url_hint()

        if self._thread and self._thread.is_alive():
            messagebox.showwarning(
                "Download em andamento",
                "Aguarde o download atual terminar antes de iniciar outro.")
            return

        self._set_busy(True)
        self.progress_bar.set(0)
        self.pct_var.set("0%")
        self._pct_label.configure(text_color=CLR_MUTED)
        self.status_var.set("Iniciando...")
        self._status_label.configure(text_color=CLR_TEXT)
        self.info_var.set("Analisando link...")

        self._thread = threading.Thread(
            target=self._manager.download,
            args=(url, self.format_var.get()),
            daemon=True,
        )
        self._thread.start()

    def _reset_url_hint(self):
        self._url_hint.configure(
            text="Cole um link de video, audio ou colecao.",
            text_color=CLR_MUTED)

    def open_downloads_folder(self) -> None:
        BASE_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                os.startfile(BASE_DOWNLOADS_DIR)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(BASE_DOWNLOADS_DIR)])
            else:
                subprocess.Popen(["xdg-open", str(BASE_DOWNLOADS_DIR)])
        except Exception as exc:
            messagebox.showerror("Erro ao abrir pasta", str(exc))

    # ── Event loop ────────────────────────────────────────────────────────────

    def _poll(self) -> None:
        while True:
            try:
                event = self._q.get_nowait()
            except queue.Empty:
                break
            self._handle(event)
        self.root.after(100, self._poll)

    def _handle(self, event: dict[str, Any]) -> None:
        etype = event.get("type")

        if etype == "status":
            self.status_var.set(event.get("message", ""))

        elif etype == "meta":
            total = event.get("total_items", 0)
            is_pl = event.get("playlist_mode", False)
            dest  = event.get("target_dir", "")
            tipo  = "Colecao" if is_pl else "Midia"
            self.info_var.set(f"Tipo: {tipo}  |  Itens: {total}  |  Destino: {dest}")

        elif etype == "progress":
            pct = event.get("progress", 0.0)
            self.progress_bar.set(pct / 100.0)
            self.pct_var.set(f"{pct:.0f}%")
            self.status_var.set(event.get("message", "Baixando..."))

        elif etype == "done":
            summary: DownloadSummary = event["summary"]
            self._set_busy(False)
            pct = 100.0 if summary.downloaded_count else 0.0
            self.progress_bar.set(pct / 100.0)
            self.pct_var.set(f"{pct:.0f}%")
            if summary.downloaded_count:
                self._pct_label.configure(text_color=CLR_GREEN)
                self._status_label.configure(text_color=CLR_GREEN)
            self._show_summary(summary)

        elif etype == "error":
            self._set_busy(False)
            self.progress_bar.set(0)
            self.pct_var.set("0%")
            self._pct_label.configure(text_color=CLR_ERROR)
            self._status_label.configure(text_color=CLR_ERROR)
            self.status_var.set("Falha no download.")
            self.info_var.set("Verifique o link informado e tente novamente.")
            messagebox.showerror("Erro no download",
                                 event.get("message", "Erro desconhecido."))

    def _show_summary(self, s: DownloadSummary) -> None:
        failed = len(s.failed_items)
        self.status_var.set(
            f"Concluido — {s.downloaded_count} baixado(s)"
            + (f", {failed} com falha" if failed else ""))
        self.info_var.set(f"Destino: {s.target_dir}")

        lines = [
            f"OK  {s.downloaded_count} item(s) baixado(s) com sucesso",
            f"--  {failed} item(s) com falha",
        ]
        if failed:
            lines += ["", "Itens com falha:"] + [f"  - {i}" for i in s.failed_items]

        messagebox.showinfo("Resumo do download", "\n".join(lines))

    # ── State helpers ─────────────────────────────────────────────────────────

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.download_btn.configure(
            state=state,
            text="Baixando..." if busy else "Baixar midia")
        self.url_entry.configure(state=state)
        self.paste_btn.configure(state=state)
        self.folder_btn.configure(state=state)

    @staticmethod
    def _valid_url(url: str) -> bool:
        try:
            p = urlparse(url)
        except ValueError:
            return False
        if p.scheme not in {"http", "https"}:
            return False
        return bool(p.hostname)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    root = ctk.CTk()
    app = MediaDownloaderApp(root)
    app.url_entry.focus()
    root.mainloop()


if __name__ == "__main__":
    main()
