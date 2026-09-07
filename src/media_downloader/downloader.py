"""Backend do download. Publica eventos na fila; nunca toca na interface."""

import queue
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import yt_dlp

from .config import DOWNLOAD_FOLDERS
from .metadata import MusicMetadataService, metadata_review_reasons, suggest_music_search
from .models import DownloadSummary, MetadataPendingItem, MusicMetadataCandidate

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

# Quantas falhas o resumo lista antes de virar contagem. `messagebox` nao rola:
# lista longa cresce a caixa ate passar da tela e esconder o proprio botao.
FAILURES_SHOWN = 5


def summary_lines(summary: DownloadSummary) -> list[str]:
    """Monta o texto do resumo final.

    O resumo responde "o que aconteceu?"; a revisao que abre logo depois
    responde "o que corrigir?", item a item e com previa da capa. Repetir o
    detalhe de cada pendencia aqui so fazia a caixa crescer sem informar nada
    novo — numa playlist de sete faixas ela ja ocupava a tela inteira.
    """
    failed = len(summary.failed_items)
    pending = len(summary.metadata_pending_items)
    lines = [
        f"OK  {summary.downloaded_count} item(s) baixado(s) com sucesso",
        f"--  {failed} item(s) com falha",
        f"--  {pending} MP3 com metadata a confirmar",
    ]
    if failed:
        lines += ["", "Itens com falha:"]
        lines += [f"  - {item}" for item in summary.failed_items[:FAILURES_SHOWN]]
        if failed > FAILURES_SHOWN:
            lines.append(f"  ... e mais {failed - FAILURES_SHOWN}")
    if summary.extractor_notices and (failed or not summary.downloaded_count):
        lines += ["", "Avisos do extrator:"]
        lines += [f"  - {aviso}" for aviso in summary.extractor_notices[:FAILURES_SHOWN]]
    if pending:
        lines += ["", f"A revisao abre em seguida, com {pending} item(s) para confirmar."]
    return lines


class ReportingLogger:
    def __init__(self, event_queue: queue.Queue, summary: DownloadSummary):
        self._q = event_queue
        self._summary = summary

    def debug(self, _: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        # Aviso do extrator não é item que falhou: o alerta de runtime
        # JavaScript ausente aparece em download que conclui inteiro.
        self._capture(msg, failure=False)

    def error(self, msg: str) -> None:
        self._capture(msg, failure=True)

    def _capture(self, msg: str, *, failure: bool) -> None:
        # A saída do yt-dlp vem colorida: sem tirar o escape ANSI, o prefixo não
        # casa e o resumo mostra "\x1b[0;31mERROR:\x1b[0m ..." como texto.
        # Prefixo sem o espaço: o .strip() anterior já removeu o espaço de
        # "ERROR: " quando a mensagem vinha vazia, e "ERROR:" virava um item.
        cleaned = _ANSI_ESCAPE.sub("", msg).strip()
        for prefix in ("ERROR:", "WARNING:"):
            cleaned = cleaned.removeprefix(prefix).strip()
        if not cleaned:
            return
        destination = (
            self._summary.failed_items if failure else self._summary.extractor_notices)
        if cleaned in destination:
            return
        destination.append(cleaned)
        if failure:
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
            "no_color": True,
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
            summary.extractor_notices.clear()

    def _emit(self, event_type: str, **payload: Any) -> None:
        self._q.put({"type": event_type, **payload})
