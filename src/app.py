import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
import json
import time
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from tkinter import messagebox
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

import customtkinter as ctk
import yt_dlp
from mutagen import MutagenError
from mutagen.id3 import APIC, ID3, ID3NoHeaderError, TALB, TDRC, TIT2, TPE1
from PIL import Image, ImageOps


APP_TITLE = "Media Downloader"
BASE_DOWNLOADS_DIR = Path(__file__).resolve().parent.parent / "Downloads"
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
APP_ICON_PATH = ASSETS_DIR / "media-downloader-icon.png"
APP_ICON_ICO_PATH = ASSETS_DIR / "media-downloader-icon.ico"
SUPPORTED_SITES_URL = "https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md"
MUSICBRAINZ_API_URL = "https://musicbrainz.org/ws/2/recording"
COVER_ART_ARCHIVE_URL = "https://coverartarchive.org/release/{release_id}/front-250"
MUSICBRAINZ_USER_AGENT = "MediaDownloader/1.0 (metadata lookup)"
COVER_PREVIEW_SIZE = 88
CATALOG_SEARCH_LIMIT = 25
CATALOG_RESULTS_SHOWN = 5
COVER_SOURCE_ATTEMPTS = 3
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
    metadata_pending_items: list["MetadataPendingItem"] = field(default_factory=list)
    total_items: int = 0
    target_dir: str = ""
    playlist_mode: bool = False


@dataclass(frozen=True)
class MetadataPendingItem:
    title: str
    file_path: str
    review_reasons: tuple[str, ...]


@dataclass(frozen=True)
class EmbeddedMetadata:
    """O que já está gravado no MP3 — lido do arquivo, não inferido."""
    artist: str | None = None
    title: str | None = None
    album: str | None = None
    cover: bytes | None = None


@dataclass(frozen=True)
class MusicSearchSuggestion:
    title: str
    artist: str | None = None


_STATUS_QUALITY = {"official": 3, "promotion": 1, "pseudo-release": 1}
_PRIMARY_TYPE_QUALITY = {"album": 3, "ep": 2, "single": 2}
_SECONDARY_TYPE_PENALTY = {"live", "compilation", "remix", "demo", "dj-mix", "interview"}


def _release_quality(release: dict[str, Any]) -> tuple[int, str]:
    """Procedência da release: oficial e de estúdio primeiro, depois a mais antiga.

    A busca do MusicBrainz devolve gravações de show na frente do álbum, e
    bootleg raramente tem capa no Cover Art Archive — a prévia ficava vazia.
    """
    group = release.get("release-group") or {}
    secondary = {kind.lower() for kind in group.get("secondary-types") or []}
    quality = (
        _STATUS_QUALITY.get((release.get("status") or "").lower(), 0)
        + _PRIMARY_TYPE_QUALITY.get((group.get("primary-type") or "").lower(), 0)
        - (3 if secondary & _SECONDARY_TYPE_PENALTY else 0)
    )
    return quality, release.get("date") or "9999"


@dataclass(frozen=True)
class MusicMetadataCandidate:
    recording_id: str
    title: str
    artist: str
    album: str | None
    year: str | None
    release_id: str | None
    release_ids: tuple[str, ...] = ()
    quality: int = 0

    @classmethod
    def from_musicbrainz(cls, recording: dict[str, Any]) -> "MusicMetadataCandidate":
        artist = "".join(
            f"{credit.get('name', '')}{credit.get('joinphrase', '')}"
            for credit in recording.get("artist-credit", [])
        ) or "Artista desconhecido"

        def ranking(release: dict[str, Any]) -> tuple[int, str]:
            quality, date = _release_quality(release)
            return -quality, date

        releases = sorted(recording.get("releases") or [], key=ranking)
        release = releases[0] if releases else {}
        date = release.get("date") or ""
        return cls(
            recording_id=recording["id"],
            title=recording.get("title") or "Faixa sem titulo",
            artist=artist,
            album=release.get("title"),
            year=date[:4] or None,
            release_id=release.get("id"),
            release_ids=tuple(item["id"] for item in releases if item.get("id")),
            quality=_release_quality(release)[0] if release else 0,
        )


_PROMOTIONAL_SUFFIX = re.compile(
    r"\s*[\[(](?:official\s+(?:music\s+)?video|official\s+audio|lyrics?|hd|4k)[\])]\s*$",
    flags=re.IGNORECASE,
)


def suggest_music_search(source_title: str) -> MusicSearchSuggestion:
    """Cria uma consulta de catálogo sem transformar inferência em metadata."""
    cleaned = _PROMOTIONAL_SUFFIX.sub("", source_title).strip()
    if " - " not in cleaned:
        return MusicSearchSuggestion(title=cleaned)
    artist, title = (part.strip() for part in cleaned.split(" - ", 1))
    if artist and title:
        return MusicSearchSuggestion(title=title, artist=artist)
    return MusicSearchSuggestion(title=cleaned)


def metadata_review_reasons(info: dict[str, Any]) -> tuple[str, ...]:
    """Descreve o que o yt-dlp realmente gravou, sem chamar de ausente o que existe.

    O FFmpegMetadata usa artist/artists/creator/creators e, faltando todos,
    cai para o nome do canal. Vídeo comum do YouTube nunca traz `artist`, então
    o MP3 sai com o canal como artista — provisório, não ausente.
    """
    reasons = []
    if not any(info.get(key) for key in ("artist", "artists", "creator", "creators")):
        channel = info.get("uploader") or info.get("uploader_id")
        reasons.append(
            f"artista provisorio: canal {channel}" if channel else "artista ausente")
    if not (info.get("thumbnail") or info.get("thumbnails")):
        reasons.append("capa ausente")
    return tuple(reasons)


def metadata_review_detail(pending_item: MetadataPendingItem) -> str:
    """Explica a revisão sem confundir sugestão de busca com tag ausente."""
    suggestion = suggest_music_search(pending_item.title)
    parts = list(pending_item.review_reasons)
    if suggestion.artist:
        parts.append(f"titulo sugere {suggestion.artist} — {suggestion.title}")
    parts.append("confirme um resultado no catalogo")
    detail = " · ".join(parts)
    return detail[:1].upper() + detail[1:]


class MusicMetadataService:
    """Cliente mínimo do catálogo; não conhece arquivos nem widgets."""

    def __init__(
        self,
        fetch_json: Callable[[str], dict[str, Any]] | None = None,
        fetch_cover: Callable[[str], tuple[bytes, str]] | None = None,
    ):
        self._fetch_json = fetch_json or self._request_json
        self._fetch_cover = fetch_cover or self._request_cover
        self._last_request_at = 0.0

    def search(self, suggestion: MusicSearchSuggestion) -> list[MusicMetadataCandidate]:
        terms = [f'recording:"{self._escape_term(suggestion.title)}"']
        if suggestion.artist:
            terms.append(f'artist:"{self._escape_term(suggestion.artist)}"')
        # Consulta mais do que exibe: o álbum oficial costuma vir depois de
        # dezenas de gravações de show com a mesma pontuação de busca.
        query = urlencode({
            "query": " AND ".join(terms), "fmt": "json", "limit": CATALOG_SEARCH_LIMIT,
        })
        payload = self._fetch_json(f"{MUSICBRAINZ_API_URL}?{query}")
        candidates = [
            MusicMetadataCandidate.from_musicbrainz(recording)
            for recording in payload.get("recordings", [])
        ]
        candidates.sort(key=lambda candidate: -candidate.quality)
        return candidates[:CATALOG_RESULTS_SHOWN]

    @staticmethod
    def _escape_term(term: str) -> str:
        """Protege a frase Lucene: aspas soltas do título encerram a busca cedo."""
        return term.replace("\\", "\\\\").replace('"', '\\"')

    def get_cover_preview(
        self, candidate: MusicMetadataCandidate,
    ) -> tuple[bytes, str] | None:
        for release_id in self._cover_sources(candidate):
            try:
                return self._fetch_cover(release_id)
            except Exception:
                continue
        return None

    @staticmethod
    def _cover_sources(candidate: MusicMetadataCandidate) -> tuple[str, ...]:
        """A melhor release nem sempre tem capa; as demais da gravação servem."""
        sources = candidate.release_ids or (
            (candidate.release_id,) if candidate.release_id else ()
        )
        return sources[:COVER_SOURCE_ATTEMPTS]

    def _request_json(self, url: str) -> dict[str, Any]:
        wait = 1.0 - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        request = Request(url, headers={"User-Agent": MUSICBRAINZ_USER_AGENT, "Accept": "application/json"})
        with urlopen(request, timeout=10) as response:
            payload = json.load(response)
        self._last_request_at = time.monotonic()
        return payload

    def read_embedded(self, file_path: Path) -> EmbeddedMetadata:
        """Lê as tags já gravadas — a prévia mostra o arquivo, não uma suposição."""
        # Arquivo que sumiu não é arquivo sem tags: devolver metadata vazia aqui
        # faria a interface anunciar "artista gravado: nenhum" para o que não existe.
        if not file_path.name or not file_path.is_file():
            raise FileNotFoundError(f"MP3 nao encontrado: {file_path}")
        try:
            tags = ID3(file_path)
        except (ID3NoHeaderError, MutagenError):
            return EmbeddedMetadata()
        covers = tags.getall("APIC")
        return EmbeddedMetadata(
            artist=self._first_text(tags, "TPE1"),
            title=self._first_text(tags, "TIT2"),
            album=self._first_text(tags, "TALB"),
            cover=covers[0].data if covers else None,
        )

    @staticmethod
    def _first_text(tags: ID3, frame_id: str) -> str | None:
        frames = tags.getall(frame_id)
        if not frames or not frames[0].text:
            return None
        return str(frames[0].text[0]) or None

    def apply_to_mp3(self, file_path: Path, candidate: MusicMetadataCandidate) -> bool:
        try:
            tags = ID3(file_path)
        except ID3NoHeaderError:
            tags = ID3()

        for frame_id in ("TIT2", "TPE1", "TALB", "TDRC", "APIC"):
            tags.delall(frame_id)
        tags.add(TIT2(encoding=3, text=candidate.title))
        tags.add(TPE1(encoding=3, text=candidate.artist))
        if candidate.album:
            tags.add(TALB(encoding=3, text=candidate.album))
        if candidate.year:
            tags.add(TDRC(encoding=3, text=candidate.year))

        cover_embedded = False
        cover = self.get_cover_preview(candidate)
        if cover:
            data, mime = cover
            tags.add(APIC(encoding=3, mime=mime, type=3, desc="Capa", data=data))
            cover_embedded = True
        tags.save(file_path)
        return cover_embedded

    @staticmethod
    def _request_cover(release_id: str) -> tuple[bytes, str]:
        request = Request(
            COVER_ART_ARCHIVE_URL.format(release_id=release_id),
            headers={"User-Agent": MUSICBRAINZ_USER_AGENT},
        )
        with urlopen(request, timeout=10) as response:
            return response.read(), response.headers.get_content_type()


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
    def __init__(
        self,
        event_queue: queue.Queue,
        metadata_service: MusicMetadataService | None = None,
    ):
        self._q = event_queue
        self._metadata_service = metadata_service or MusicMetadataService()

    def search_metadata(self, pending_item: MetadataPendingItem) -> None:
        try:
            suggestion = suggest_music_search(pending_item.title)
            candidates = self._metadata_service.search(suggestion)
            self._emit(
                "metadata_results", pending_item=pending_item, candidates=candidates,
            )
        except Exception as exc:
            self._emit("metadata_search_error", pending_item=pending_item, message=str(exc))

    def apply_metadata(
        self, pending_item: MetadataPendingItem, candidate: MusicMetadataCandidate,
    ) -> None:
        try:
            cover_embedded = self._metadata_service.apply_to_mp3(
                Path(pending_item.file_path), candidate,
            )
            self._emit(
                "metadata_applied",
                pending_item=pending_item,
                candidate=candidate,
                cover_embedded=cover_embedded,
            )
        except Exception as exc:
            self._emit("metadata_import_error", pending_item=pending_item, message=str(exc))

    def load_embedded_metadata(self, pending_item: MetadataPendingItem) -> None:
        try:
            embedded = self._metadata_service.read_embedded(Path(pending_item.file_path))
            self._emit("metadata_embedded", pending_item=pending_item, embedded=embedded)
        except Exception:
            self._emit("metadata_embedded_unavailable", pending_item=pending_item)

    def load_metadata_cover_preview(self, candidate: MusicMetadataCandidate) -> None:
        try:
            preview = self._metadata_service.get_cover_preview(candidate)
            if preview is None:
                self._emit("metadata_cover_unavailable", candidate=candidate)
                return
            data, mime = preview
            self._emit(
                "metadata_cover_preview", candidate=candidate, data=data, mime=mime,
            )
        except Exception:
            self._emit("metadata_cover_unavailable", candidate=candidate)

    def download(self, url: str, file_format: str, include_metadata: bool = False) -> None:
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

            opts = self._build_opts(
                target_dir, file_format, playlist_mode, summary, include_metadata,
            )
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])

            self._reconcile_failure_reports(summary)
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
        include_metadata: bool = False,
    ) -> dict[str, Any]:
        if playlist_mode:
            outtmpl = str(target_dir / "%(playlist_title,playlist|Playlist)s" / "%(title)s.%(ext)s")
        else:
            outtmpl = str(target_dir / "%(title)s.%(ext)s")

        opts: dict[str, Any] = {
            "outtmpl": outtmpl,
            "ignoreerrors": True,
            "noplaylist": not playlist_mode,
            "progress_hooks": [self._make_progress_hook(summary, include_metadata)],
            "quiet": True,
            "no_warnings": True,
            "concurrent_fragment_downloads": 1,
            "logger": ReportingLogger(self._q, summary),
            "remote_components": ["ejs:github"],
        }

        if file_format == "mp3":
            postprocessors = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
            if include_metadata:
                postprocessors += [
                    {"key": "FFmpegMetadata", "add_metadata": True},
                    {"key": "EmbedThumbnail"},
                ]
            opts.update({
                "format": "bestaudio/best",
                "postprocessors": postprocessors,
            })
            if include_metadata:
                opts["writethumbnail"] = True
        else:
            opts.update({
                "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
                "merge_output_format": "mp4",
            })

        return opts

    def _make_progress_hook(self, summary: DownloadSummary, include_metadata: bool = False):
        seen: set[str] = set()
        metadata_seen: set[str] = set()

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
                if include_metadata and uid not in metadata_seen:
                    metadata_seen.add(uid)
                    review_reasons = metadata_review_reasons(info_dict)
                    if review_reasons:
                        filename = data.get("filename") or info_dict.get("filepath") or ""
                        summary.metadata_pending_items.append(MetadataPendingItem(
                            title=title,
                            file_path=str(Path(filename).with_suffix(".mp3")) if filename else "",
                            review_reasons=review_reasons,
                        ))
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

    @staticmethod
    def _reconcile_failure_reports(summary: DownloadSummary) -> None:
        """Remove diagnósticos do extrator quando o resultado final foi íntegro."""
        if summary.total_items and summary.downloaded_count >= summary.total_items:
            summary.failed_items.clear()

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
        self._metadata_review_rows: dict[
            "MetadataPendingItem", tuple[ctk.CTkLabel, ctk.CTkLabel, "HoverButton"],
        ] = {}
        self._metadata_embedded_images: dict["MetadataPendingItem", ctk.CTkImage] = {}
        self._metadata_review_window: ctk.CTkToplevel | None = None

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

        self.include_metadata_var = ctk.BooleanVar(value=False)
        self.metadata_checkbox = ctk.CTkCheckBox(
            parent, text="Adicionar capa e metadados",
            variable=self.include_metadata_var,
            onvalue=True, offvalue=False,
            font=(FONT_FAMILY, 12, "bold"), text_color=CLR_TEXT,
            fg_color=CLR_ACCENT, hover_color=CLR_ACCENT_DARK,
            border_color=CLR_BORDER, checkmark_color=CLR_TEXT,
        )
        self.metadata_checkbox.pack(anchor="w", pady=(14, 0))
        ctk.CTkLabel(
            parent,
            text=("Usa titulo, artista e capa disponiveis na plataforma. "
                  "Títulos no formato Artista - Musica podem ajudar depois."),
            font=(FONT_FAMILY, 10), text_color=CLR_MUTED,
        ).pack(anchor="w", pady=(3, 0))
        self.format_var.trace_add("write", lambda *_: self._update_metadata_option())
        self._update_metadata_option()

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
            args=(url, self.format_var.get(), self.include_metadata_var.get()),
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

        elif etype == "metadata_results":
            self._show_metadata_candidates(
                event["pending_item"], event.get("candidates", []),
            )

        elif etype == "metadata_search_error":
            messagebox.showerror(
                "Busca de metadata",
                f"Nao foi possivel buscar metadata para {event['pending_item'].title}.\n\n"
                f"{event.get('message', 'Erro desconhecido.')}",
            )

        elif etype == "metadata_applied":
            self._resolve_metadata_review(event["pending_item"])
            candidate: MusicMetadataCandidate = event["candidate"]
            cover_message = " com capa incorporada" if event.get("cover_embedded") else " sem capa disponivel"
            messagebox.showinfo(
                "Metadata importada",
                f"Metadata de {candidate.artist} — {candidate.title} importada{cover_message}.",
            )

        elif etype == "metadata_import_error":
            messagebox.showerror(
                "Importacao de metadata",
                f"Nao foi possivel atualizar {event['pending_item'].title}.\n\n"
                f"{event.get('message', 'Erro desconhecido.')}",
            )

        elif etype == "metadata_embedded":
            self._show_embedded_metadata(event["pending_item"], event["embedded"])

        elif etype == "metadata_embedded_unavailable":
            self._show_embedded_unavailable(event["pending_item"])

        elif etype == "metadata_cover_preview":
            self._show_metadata_cover_preview(
                event["candidate"], event["data"], event["mime"],
            )

        elif etype == "metadata_cover_unavailable":
            self._show_metadata_cover_unavailable(event["candidate"])

    def _show_summary(self, s: DownloadSummary) -> None:
        failed = len(s.failed_items)
        pending_metadata = len(s.metadata_pending_items)
        self.status_var.set(
            f"Concluido — {s.downloaded_count} baixado(s)"
            + (f", {failed} com falha" if failed else "")
            + (f", {pending_metadata} com metadata a confirmar" if pending_metadata else ""))
        self.info_var.set(f"Destino: {s.target_dir}")

        lines = [
            f"OK  {s.downloaded_count} item(s) baixado(s) com sucesso",
            f"--  {failed} item(s) com falha",
            f"--  {pending_metadata} MP3 com metadata a confirmar",
        ]
        if failed:
            lines += ["", "Itens com falha:"] + [f"  - {i}" for i in s.failed_items]
        if pending_metadata:
            lines += ["", "MP3 com metadata a confirmar:"]
            lines += [
                f"  - {item.title} ({metadata_review_detail(item)})"
                for item in s.metadata_pending_items
            ]

        messagebox.showinfo("Resumo do download", "\n".join(lines))
        if pending_metadata:
            self._show_metadata_pending_dialog(s.metadata_pending_items)

    def _show_metadata_pending_dialog(self, pending_items: list[MetadataPendingItem]) -> None:
        window = ctk.CTkToplevel(self.root)
        window.title("MP3 com metadata a confirmar")
        window.geometry("760x480")
        # A largura minima acompanha o wraplength da linha de motivos: coluna
        # mais estreita que o texto corta a frase em vez de quebrar a linha.
        window.minsize(720, 380)
        window.configure(fg_color=BG_DARK)
        window.transient(self.root)
        self._metadata_review_window = window
        self._metadata_review_rows = {}
        self._metadata_embedded_images = {}

        ctk.CTkLabel(
            window, text="Confirmar metadata do MP3 concluido",
            font=(FONT_FAMILY, 18, "bold"), text_color=CLR_TEXT,
        ).pack(anchor="w", padx=24, pady=(22, 3))
        ctk.CTkLabel(
            window,
            text=("A previa mostra o que ja esta gravado no arquivo. Busque no catalogo "
                  "para substituir; a selecao do catalogo, e nao o titulo sugerido, e o "
                  "que sera importado."),
            font=(FONT_FAMILY, 11), text_color=CLR_MUTED, wraplength=650, justify="left",
        ).pack(anchor="w", padx=24, pady=(0, 16))

        items_frame = ctk.CTkScrollableFrame(window, fg_color=BG_CARD, corner_radius=12)
        items_frame.pack(fill="both", expand=True, padx=24, pady=(0, 22))
        for pending_item in pending_items:
            row = ctk.CTkFrame(items_frame, fg_color=BG_INPUT, corner_radius=10)
            row.pack(fill="x", pady=5, padx=4)
            row.grid_columnconfigure(1, weight=1)

            cover_label = ctk.CTkLabel(
                row, text="Lendo\ncapa...", width=COVER_PREVIEW_SIZE, height=COVER_PREVIEW_SIZE,
                font=(FONT_FAMILY, 9), text_color=CLR_MUTED, fg_color=BG_HOVER,
                corner_radius=8, justify="center",
            )
            cover_label.grid(row=0, column=0, rowspan=3, padx=(10, 4), pady=10)
            ctk.CTkLabel(
                row, text=pending_item.title, font=(FONT_FAMILY, 12, "bold"),
                text_color=CLR_TEXT, anchor="w",
            ).grid(row=0, column=1, sticky="ew", padx=12, pady=(10, 1))
            embedded_label = ctk.CTkLabel(
                row, text="Lendo o que ja esta gravado...",
                font=(FONT_FAMILY, 10), text_color=CLR_TEXT, anchor="w",
            )
            embedded_label.grid(row=1, column=1, sticky="ew", padx=12)
            ctk.CTkLabel(
                row, text=metadata_review_detail(pending_item),
                font=(FONT_FAMILY, 10), text_color=CLR_MUTED, anchor="w",
                wraplength=340, justify="left",
            ).grid(row=2, column=1, sticky="ew", padx=12, pady=(1, 10))
            search_btn = HoverButton(
                row, text="Buscar metadata", width=145, height=32,
                font=(FONT_FAMILY, 11, "bold"),
                base_color=CLR_ACCENT, hover_color=CLR_ACCENT_DARK,
                text_color=CLR_TEXT,
                command=lambda item=pending_item: self._start_metadata_search(item),
            )
            search_btn.grid(row=0, column=2, rowspan=3, padx=10, pady=10)

            # Chaveado pelo próprio item: dois pendentes podem compartilhar o
            # caminho (o yt-dlp nem sempre informa o nome do arquivo), e aí a
            # prévia de um sobrescrevia a linha do outro.
            self._metadata_review_rows[pending_item] = (
                row, cover_label, embedded_label, search_btn,
            )
            threading.Thread(
                target=self._manager.load_embedded_metadata,
                args=(pending_item,), daemon=True,
            ).start()

    def _show_embedded_metadata(
        self, pending_item: MetadataPendingItem, embedded: EmbeddedMetadata,
    ) -> None:
        row = self._metadata_review_rows.get(pending_item)
        if not row:
            return
        _, cover_label, embedded_label, _ = row
        if embedded_label.winfo_exists():
            gravado = [f"Artista gravado: {embedded.artist or 'nenhum'}"]
            if embedded.album:
                gravado.append(f"album: {embedded.album}")
            embedded_label.configure(text=" · ".join(gravado))
        if not cover_label.winfo_exists():
            return
        image = self._make_cover_image(embedded.cover) if embedded.cover else None
        if image is None:
            cover_label.configure(text="Sem capa\nno arquivo")
            return
        self._metadata_embedded_images[pending_item] = image
        cover_label.configure(image=image, text="")

    def _show_embedded_unavailable(self, pending_item: MetadataPendingItem) -> None:
        """Sem arquivo para ler, importar so produziria erro — a acao sai de cena."""
        row = self._metadata_review_rows.get(pending_item)
        if not row:
            return
        _, cover_label, embedded_label, search_btn = row
        if cover_label.winfo_exists():
            cover_label.configure(text="Arquivo\nnao lido")
        if embedded_label.winfo_exists():
            embedded_label.configure(
                text="Arquivo nao localizado — verifique se a conversao terminou.",
                text_color=CLR_ERROR,
            )
        if search_btn.winfo_exists():
            search_btn.configure(state="disabled")

    def _resolve_metadata_review(self, pending_item: MetadataPendingItem) -> None:
        """Item confirmado sai de cena; sem pendencia restante, a revisao fecha."""
        row = self._metadata_review_rows.pop(pending_item, None)
        self._metadata_embedded_images.pop(pending_item, None)
        if row and row[0].winfo_exists():
            row[0].destroy()
        if self._metadata_review_rows:
            return
        window = self._metadata_review_window
        if window is not None and window.winfo_exists():
            window.destroy()
        self._metadata_review_window = None

    @staticmethod
    def _make_cover_image(data: bytes) -> ctk.CTkImage | None:
        try:
            with Image.open(BytesIO(data)) as source:
                preview = ImageOps.fit(
                    source.convert("RGB"),
                    (COVER_PREVIEW_SIZE, COVER_PREVIEW_SIZE),
                    method=Image.Resampling.LANCZOS,
                )
        except Exception:
            return None
        return ctk.CTkImage(
            light_image=preview, dark_image=preview,
            size=(COVER_PREVIEW_SIZE, COVER_PREVIEW_SIZE),
        )

    def _start_metadata_search(self, pending_item: MetadataPendingItem) -> None:
        if self._metadata_thread and self._metadata_thread.is_alive():
            messagebox.showinfo("Busca de metadata", "Aguarde a busca atual terminar.")
            return
        self._metadata_thread = threading.Thread(
            target=self._manager.search_metadata, args=(pending_item,), daemon=True,
        )
        self._metadata_thread.start()

    def _show_metadata_candidates(
        self, pending_item: MetadataPendingItem, candidates: list[MusicMetadataCandidate],
    ) -> None:
        window = ctk.CTkToplevel(self.root)
        window.title("Resultados de metadata")
        window.geometry("680x440")
        window.minsize(560, 320)
        window.configure(fg_color=BG_DARK)
        window.transient(self.root)
        self._metadata_cover_labels = {}
        self._metadata_cover_images = {}

        ctk.CTkLabel(
            window, text=f"Resultados para: {pending_item.title}",
            font=(FONT_FAMILY, 16, "bold"), text_color=CLR_TEXT, wraplength=620,
            justify="left",
        ).pack(anchor="w", padx=24, pady=(22, 14))

        if not candidates:
            ctk.CTkLabel(
                window,
                text="Nenhum resultado encontrado. Tente novamente quando tiver mais dados na origem.",
                font=(FONT_FAMILY, 12), text_color=CLR_MUTED, wraplength=620, justify="left",
            ).pack(anchor="w", padx=24, pady=(0, 22))
            return

        candidates_frame = ctk.CTkScrollableFrame(window, fg_color=BG_CARD, corner_radius=12)
        candidates_frame.pack(fill="both", expand=True, padx=24, pady=(0, 22))
        for candidate in candidates:
            row = ctk.CTkFrame(candidates_frame, fg_color=BG_INPUT, corner_radius=10)
            row.pack(fill="x", pady=5, padx=4)
            row.grid_columnconfigure(0, weight=1)
            cover_label = ctk.CTkLabel(
                row, text="Carregando\ncapa...",
                width=COVER_PREVIEW_SIZE, height=COVER_PREVIEW_SIZE,
                font=(FONT_FAMILY, 9), text_color=CLR_MUTED, fg_color=BG_HOVER,
                corner_radius=8, justify="center",
            )
            cover_label.grid(row=0, column=1, rowspan=2, padx=(8, 2), pady=8)
            self._metadata_cover_labels[candidate.recording_id] = cover_label
            ctk.CTkLabel(
                row, text=f"{candidate.artist} — {candidate.title}",
                font=(FONT_FAMILY, 12, "bold"), text_color=CLR_TEXT, anchor="w",
            ).grid(row=0, column=0, sticky="ew", padx=12, pady=(9, 1))
            details = " · ".join(part for part in [candidate.album, candidate.year] if part)
            ctk.CTkLabel(
                row, text=details or "Album nao informado",
                font=(FONT_FAMILY, 10), text_color=CLR_MUTED, anchor="w",
            ).grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 9))
            HoverButton(
                row, text="Importar", width=105, height=32,
                font=(FONT_FAMILY, 11, "bold"),
                base_color=CLR_ACCENT, hover_color=CLR_ACCENT_DARK,
                text_color=CLR_TEXT,
                command=lambda item=pending_item, result=candidate, dialog=window:
                    self._start_metadata_import(item, result, dialog),
            ).grid(row=0, column=2, rowspan=2, padx=10, pady=10)

            threading.Thread(
                target=self._manager.load_metadata_cover_preview,
                args=(candidate,), daemon=True,
            ).start()

    def _show_metadata_cover_preview(
        self, candidate: MusicMetadataCandidate, data: bytes, _mime: str,
    ) -> None:
        label = self._metadata_cover_labels.get(candidate.recording_id)
        if not label or not label.winfo_exists():
            return
        image = self._make_cover_image(data)
        if image is None:
            self._show_metadata_cover_unavailable(candidate)
            return
        self._metadata_cover_images[candidate.recording_id] = image
        label.configure(image=image, text="")

    def _show_metadata_cover_unavailable(self, candidate: MusicMetadataCandidate) -> None:
        label = self._metadata_cover_labels.get(candidate.recording_id)
        if label and label.winfo_exists():
            label.configure(image=None, text="Capa\nindisponivel")

    def _start_metadata_import(
        self,
        pending_item: MetadataPendingItem,
        candidate: MusicMetadataCandidate,
        window: ctk.CTkToplevel,
    ) -> None:
        if self._metadata_thread and self._metadata_thread.is_alive():
            messagebox.showinfo("Importacao de metadata", "Aguarde a operacao atual terminar.")
            return
        window.destroy()
        self._metadata_thread = threading.Thread(
            target=self._manager.apply_metadata, args=(pending_item, candidate), daemon=True,
        )
        self._metadata_thread.start()

    # ── State helpers ─────────────────────────────────────────────────────────

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.download_btn.configure(
            state=state,
            text="Baixando..." if busy else "Baixar midia")
        self.url_entry.configure(state=state)
        self.paste_btn.configure(state=state)
        self.folder_btn.configure(state=state)
        if busy:
            self.metadata_checkbox.configure(state="disabled")
        else:
            self._update_metadata_option()

    def _update_metadata_option(self) -> None:
        if self.format_var.get() == "mp3":
            self.metadata_checkbox.configure(state="normal", text_color=CLR_TEXT)
        else:
            self.include_metadata_var.set(False)
            self.metadata_checkbox.configure(state="disabled", text_color=CLR_MUTED)

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
