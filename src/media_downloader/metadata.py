"""Catalogo musical e tags do arquivo — nao conhece widget nem fila."""

import json
import re
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from mutagen import MutagenError
from mutagen.id3 import APIC, ID3, ID3NoHeaderError, TALB, TDRC, TIT2, TPE1

from .config import CATALOG_RESULTS_SHOWN, CATALOG_USER_AGENT, ITUNES_SEARCH_URL
from .models import (
    EmbeddedMetadata,
    MetadataPendingItem,
    MusicMetadataCandidate,
    MusicSearchSuggestion,
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
        # Texto livre: o iTunes não tem sintaxe de busca, e a ordem que ele
        # devolve já traz o álbum de estúdio na frente das gravações ao vivo.
        term = " ".join(part for part in (suggestion.artist, suggestion.title) if part)
        query = urlencode({
            "term": term, "media": "music", "entity": "song",
            "limit": CATALOG_RESULTS_SHOWN,
        })
        payload = self._fetch_json(f"{ITUNES_SEARCH_URL}?{query}")
        candidates = [
            MusicMetadataCandidate.from_itunes(result)
            for result in payload.get("results", [])
        ]
        return candidates[:CATALOG_RESULTS_SHOWN]

    def get_cover_preview(
        self, candidate: MusicMetadataCandidate,
    ) -> tuple[bytes, str] | None:
        if not candidate.artwork_url:
            return None
        try:
            return self._fetch_cover(candidate.artwork_url)
        except Exception:
            return None

    def _request_json(self, url: str) -> dict[str, Any]:
        wait = 1.0 - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        request = Request(url, headers={"User-Agent": CATALOG_USER_AGENT, "Accept": "application/json"})
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
    def _request_cover(artwork_url: str) -> tuple[bytes, str]:
        request = Request(artwork_url, headers={"User-Agent": CATALOG_USER_AGENT})
        with urlopen(request, timeout=10) as response:
            return response.read(), response.headers.get_content_type()
