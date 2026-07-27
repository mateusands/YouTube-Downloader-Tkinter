"""
SDD — Especificação: validação e classificação de URL

CONTRATO
  `MediaDownloaderApp._valid_url(url)` decide se o botão de download pode ser
  acionado. Como o aplicativo delega a compatibilidade de plataformas ao
  yt-dlp, ele aceita links HTTP/HTTPS bem formados de qualquer domínio e deixa
  a validação de suporte real para a extração. `DownloadManager._url_is_playlist`
  preserva a identificação explícita de playlists do YouTube, que decide o modo
  (playlist ou item único), a pasta de destino e o `noplaylist` do yt-dlp.

POR QUE EXISTE
  O produto deixou de ser específico do YouTube: bloquear Vimeo, TikTok ou
  outras plataformas suportadas pelo yt-dlp contradiz sua proposta. Ainda assim,
  a distinção da playlist do YouTube é sutil: um link de vídeo QUE ESTÁ dentro de
  uma playlist (`/watch?v=...&list=...`) é URL válida mas NÃO é modo playlist —
  o path tem que ser exatamente `/playlist`. Trocar isso faz o app baixar a
  playlist inteira quando o usuário queria um vídeo só.

REGRA DE NEGÓCIO
  - Qualquer URL HTTP/HTTPS com host é aceita; isso não assegura que o site ou
    conteúdo seja suportado, acessível ou disponível.
  - Modo playlist exige path `/playlist` E o parâmetro `list`.
  - `_valid_url` valida FORMATO, nunca existência ou acessibilidade do vídeo.
"""

import pytest

from app import DownloadManager, MediaDownloaderApp, SUPPORTED_PLATFORM_NAMES

valida = MediaDownloaderApp._valid_url
eh_playlist = DownloadManager._url_is_playlist


class TestValidacaoDeUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtube.com/watch?v=dQw4w9WgXcQ",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/abc123",
            "https://www.youtube.com/playlist?list=PLabc",
            "http://www.youtube.com/watch?v=abc",
        ],
    )
    def test_deve_aceitar_quando_o_link_e_http_ou_https_e_bem_formado(self, url):
        assert valida(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://vimeo.com/76979871",
            "https://www.tiktok.com/@usuario/video/123456789",
            "https://soundcloud.com/artista/faixa",
            "https://www.dailymotion.com/video/x123abc",
        ],
    )
    def test_deve_aceitar_quando_o_link_e_de_outra_plataforma_compativel(self, url):
        assert valida(url) is True

    @pytest.mark.parametrize(
        "url, motivo",
        [
            ("", "string vazia"),
            ("abc", "não é URL"),
            ("ftp://www.youtube.com/watch?v=abc", "esquema não é http/https"),
            ("https:///video", "host ausente"),
        ],
    )
    def test_deve_recusar_quando_o_link_e_invalido(self, url, motivo):
        assert valida(url) is False, f"deveria recusar: {motivo}"


class TestDeteccaoDePlaylist:
    def test_deve_detectar_playlist_quando_o_path_e_playlist_e_ha_parametro_list(self):
        assert eh_playlist("https://www.youtube.com/playlist?list=PLabc") is True

    def test_deve_detectar_playlist_mesmo_com_barra_no_fim(self):
        assert eh_playlist("https://www.youtube.com/playlist/?list=PLabc") is True

    def test_nao_deve_detectar_playlist_quando_e_video_dentro_de_playlist(self):
        # A distinção que mais custa: o link tem `list=`, mas o usuário pediu UM vídeo.
        assert eh_playlist("https://www.youtube.com/watch?v=abc&list=PLabc") is False

    def test_nao_deve_detectar_playlist_quando_falta_o_parametro_list(self):
        assert eh_playlist("https://www.youtube.com/playlist") is False

    @pytest.mark.parametrize("url", ["", "abc", "não é url"])
    def test_deve_devolver_falso_quando_a_url_e_lixo(self, url):
        assert eh_playlist(url) is False


class TestPlataformasIndicadas:
    def test_deve_exibir_plataformas_populares_compativeis_na_tela_inicial(self):
        assert {"YouTube", "Vimeo", "TikTok", "Instagram", "SoundCloud", "Dailymotion"} <= set(
            SUPPORTED_PLATFORM_NAMES
        )
