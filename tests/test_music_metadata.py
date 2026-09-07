"""
SDD — Especificação: sugestão e escolha de metadata musical

CONTRATO
  Quando um MP3 concluído não contém dados musicais suficientes, o aplicativo
  sugere uma busca a partir do título original e apresenta candidatos vindos do
  catálogo. A pessoa escolhe um candidato; texto inferido nunca vira tag por si
  só.

POR QUE EXISTE
  Vídeos musicais frequentemente usam títulos como "ABBA - Dancing Queen
  (Official Music Video)". Isso é útil para procurar a gravação correta, mas
  não é confiável o bastante para gravar artista ou álbum sem confirmação.

REGRA DE NEGÓCIO
  - O padrão "Artista - Faixa" gera artista e faixa sugeridos, removendo sufixo
    promocional conhecido.
  - Título sem separador continua pesquisável, mas sem artista inferido.
  - Um candidato exibe a primeira release disponível; a confirmação humana é
    obrigatória antes da importação para o MP3.
  - Quando o título sugere artista, a interface pede confirmação no catálogo;
    ela não afirma que o artista está ausente nem grava a sugestão como tag.
  - A capa de cada candidato é carregada pelo backend e publicada na fila para
    ser mostrada pela UI, sem acesso de rede pela thread gráfica.
  - A consulta é texto livre. O iTunes não usa sintaxe de busca, então título
    com aspas (`Best of You "Live"`) vai cru e funciona — no MusicBrainz isso
    fechava a frase Lucene no meio e devolvia zero resultados sem erro nenhum.
  - Arquivo inexistente não é arquivo sem tags. `read_embedded` recusa o caminho
    ausente (inclusive o caminho vazio) em vez de devolver metadata vazia, senão
    a interface anuncia "artista gravado: nenhum" para um arquivo que sumiu.
  - Um resultado do iTunes já traz faixa, artista, álbum, ano e a arte numa
    resposta só; a ordem que o catálogo devolve é respeitada, sem reordenação
    nossa.
  - A arte vem em miniatura de 100 px. O tamanho faz parte da URL, então a capa
    é pedida em `ITUNES_ARTWORK_SIZE`; a extensão do arquivo é preservada, que
    nem toda arte é `.jpg`.

DIAGNÓSTICO DO ARQUIVO BAIXADO (o motivo desta revisão)
  O yt-dlp só preenche `artist` quando a própria origem publica dado musical —
  em vídeo comum do YouTube ele é nulo, e o FFmpegMetadata grava no MP3 o nome
  do canal ("AudioslaveVEVO"). Dizer "faltam: artista" para
  "Audioslave - Like a Stone (Official Video)" era falso duas vezes: o arquivo
  tem artista gravado, e o título traz o artista real.

REGRA DE NEGÓCIO
  - Artista vindo da origem (artist/artists/creator/creators) não gera revisão.
  - Artista derivado do canal é PROVISÓRIO, não ausente: a revisão nomeia o
    canal que virou tag.
  - Só é "ausente" o que não tem nem origem nem canal.
  - Capa vinda da miniatura do vídeo é PROVISÓRIA. A miniatura do YouTube é
    16:9 — um quadro do vídeo, não arte de álbum — e o `EmbedThumbnail` grava
    ela como está. Tratar "existe miniatura" como "capa resolvida" fechava a
    revisão e deixava o arquivo com um PNG 1280x720 de 776 KB no lugar da capa.
  - Sem dimensões declaradas não se afirma nada sobre a capa: o diagnóstico
    descreve o que foi medido, não o que se supõe.
  - A prévia mostra o que já está gravado no MP3 (artista e capa), lido pelo
    backend e publicado na fila — a thread gráfica não abre arquivo.
"""

import queue
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from media_downloader.config import CATALOG_RESULTS_SHOWN, ITUNES_ARTWORK_SIZE
from media_downloader.downloader import DownloadManager
from media_downloader.metadata import (
    MusicMetadataService,
    metadata_review_detail,
    metadata_review_reasons,
    suggest_music_search,
)
from media_downloader.models import (
    EmbeddedMetadata,
    MetadataPendingItem,
    MusicMetadataCandidate,
    MusicSearchSuggestion,
)
from mutagen.id3 import APIC, ID3, TPE1


class TestSugestaoDeBuscaMusical:
    def test_deve_sugerir_artista_e_faixa_quando_o_titulo_tem_formato_conhecido(self):
        sugestao = suggest_music_search("ABBA - Dancing Queen (Official Music Video)")

        assert sugestao.artist == "ABBA"
        assert sugestao.title == "Dancing Queen"

    def test_deve_manter_o_titulo_sem_inventar_artista_quando_nao_ha_separador(self):
        sugestao = suggest_music_search("Dancing Queen official video")

        assert sugestao.artist is None
        assert sugestao.title == "Dancing Queen official video"

    def test_deve_pedir_confirmacao_em_vez_de_dizer_que_o_artista_falta_quando_o_titulo_sugere_artista(self):
        item = MetadataPendingItem(
            "Audioslave - Like a Stone (Official Video)", "/tmp/musica.mp3",
            ("artista provisorio: canal AudioslaveVEVO",),
        )

        detail = metadata_review_detail(item)

        assert "Audioslave" in detail
        assert "AudioslaveVEVO" in detail
        assert "ausente" not in detail.lower()
        assert "faltam: artista" not in detail.lower()


class TestDiagnosticoDoMp3Baixado:
    def test_deve_apontar_artista_provisorio_quando_a_tag_veio_do_canal(self):
        motivos = metadata_review_reasons({
            "title": "Audioslave - Like a Stone (Official Video)",
            "uploader": "AudioslaveVEVO",
            "thumbnail": "https://exemplo.com/capa.jpg",
        })

        assert motivos == ("artista provisorio: canal AudioslaveVEVO",)

    def test_deve_apontar_artista_ausente_quando_nao_ha_artista_nem_canal(self):
        motivos = metadata_review_reasons({
            "title": "Faixa sem dados", "thumbnail": "https://exemplo.com/capa.jpg",
        })

        assert motivos == ("artista ausente",)

    def test_nao_deve_pedir_revisao_quando_a_origem_informa_artista_e_capa(self):
        motivos = metadata_review_reasons({
            "title": "Dancing Queen", "artist": "ABBA", "uploader": "ABBAVEVO",
            "thumbnail": "https://exemplo.com/capa.jpg",
        })

        assert motivos == ()

    def test_deve_apontar_capa_ausente_quando_a_origem_nao_publica_miniatura(self):
        motivos = metadata_review_reasons({"title": "Dancing Queen", "artist": "ABBA"})

        assert motivos == ("capa ausente",)

    def test_deve_apontar_capa_provisoria_quando_a_miniatura_e_do_formato_do_video(self):
        motivos = metadata_review_reasons({
            "title": "PinkPantheress - Girl Like Me (Official Video)",
            "artist": "PinkPantheress",
            "thumbnails": [{"width": 640, "height": 360}, {"width": 1920, "height": 1080}],
        })

        assert motivos == ("capa provisoria: miniatura do video",)

    def test_nao_deve_reclamar_da_capa_quando_a_miniatura_e_quadrada(self):
        motivos = metadata_review_reasons({
            "title": "Like a Stone", "artist": "Audioslave",
            "thumbnails": [{"width": 544, "height": 544}],
        })

        assert motivos == ()

    def test_nao_deve_supor_o_formato_quando_a_miniatura_nao_informa_dimensoes(self):
        motivos = metadata_review_reasons({
            "title": "Like a Stone", "artist": "Audioslave",
            "thumbnail": "https://exemplo.com/capa.jpg",
        })

        assert motivos == ()


_RESULTADO_ITUNES = {
    "trackId": 265452073,
    "trackName": "Like a Stone",
    "artistName": "Audioslave",
    "collectionName": "Audioslave",
    "releaseDate": "2002-11-19T08:00:00Z",
    "artworkUrl100": "https://is1-ssl.mzstatic.com/image/thumb/Music/dj.jpg/100x100bb.jpg",
}


class TestCandidatoDoCatalogo:
    def test_deve_mapear_faixa_artista_album_e_ano_do_resultado(self):
        candidate = MusicMetadataCandidate.from_itunes(_RESULTADO_ITUNES)

        assert candidate.track_id == "265452073"
        assert candidate.title == "Like a Stone"
        assert candidate.artist == "Audioslave"
        assert candidate.album == "Audioslave"
        assert candidate.year == "2002"

    def test_deve_pedir_a_arte_em_tamanho_util_no_lugar_da_miniatura(self):
        candidate = MusicMetadataCandidate.from_itunes(_RESULTADO_ITUNES)

        assert candidate.artwork_url.endswith(f"/{ITUNES_ARTWORK_SIZE}x{ITUNES_ARTWORK_SIZE}bb.jpg")

    def test_deve_preservar_a_extensao_da_arte_ao_trocar_o_tamanho(self):
        candidate = MusicMetadataCandidate.from_itunes(
            {**_RESULTADO_ITUNES, "artworkUrl100": "https://exemplo.com/arte/100x100bb.png"})

        assert candidate.artwork_url == (
            f"https://exemplo.com/arte/{ITUNES_ARTWORK_SIZE}x{ITUNES_ARTWORK_SIZE}bb.png")

    def test_deve_aceitar_resultado_sem_arte(self):
        candidate = MusicMetadataCandidate.from_itunes(
            {k: v for k, v in _RESULTADO_ITUNES.items() if k != "artworkUrl100"})

        assert candidate.artwork_url is None

    def test_deve_nomear_o_desconhecido_quando_o_resultado_vem_incompleto(self):
        candidate = MusicMetadataCandidate.from_itunes({"trackId": 1})

        assert candidate.artist == "Artista desconhecido"
        assert candidate.title == "Faixa sem titulo"
        assert candidate.album is None
        assert candidate.year is None


class TestCapaDoCandidato:
    def _candidato(self, artwork_url):
        return MusicMetadataCandidate(
            track_id="1", title="Like a Stone", artist="Audioslave",
            album="Audioslave", year="2002", artwork_url=artwork_url)

    def test_deve_devolver_a_arte_do_candidato(self):
        pedidos = []

        def buscar(url):
            pedidos.append(url)
            return b"capa", "image/jpeg"

        service = MusicMetadataService(fetch_cover=buscar)

        assert service.get_cover_preview(self._candidato("https://exemplo.com/600.jpg")) == (
            b"capa", "image/jpeg")
        assert pedidos == ["https://exemplo.com/600.jpg"]

    def test_deve_relatar_ausencia_quando_o_candidato_nao_tem_arte(self):
        assert MusicMetadataService().get_cover_preview(self._candidato(None)) is None

    def test_deve_relatar_ausencia_quando_a_arte_nao_pode_ser_baixada(self):
        def buscar(_url):
            raise OSError("404")

        service = MusicMetadataService(fetch_cover=buscar)

        assert service.get_cover_preview(self._candidato("https://exemplo.com/600.jpg")) is None


class TestBuscaNoCatalogo:
    def _servico(self, resultados):
        urls = []

        def responder(url: str):
            urls.append(url)
            return {"resultCount": len(resultados), "results": resultados}

        return MusicMetadataService(fetch_json=responder), urls

    def test_deve_transformar_resultados_do_itunes_em_candidatos(self):
        service, urls = self._servico([_RESULTADO_ITUNES])

        candidates = service.search(
            MusicSearchSuggestion(title="Like a Stone", artist="Audioslave"))

        assert [candidate.title for candidate in candidates] == ["Like a Stone"]
        parametros = parse_qs(urlparse(urls[0]).query)
        assert parametros["term"] == ["Audioslave Like a Stone"]
        assert parametros["entity"] == ["song"]
        assert parametros["media"] == ["music"]

    def test_deve_buscar_so_pelo_titulo_quando_o_titulo_nao_sugere_artista(self):
        service, urls = self._servico([])

        service.search(MusicSearchSuggestion(title="Dancing Queen official video"))

        assert parse_qs(urlparse(urls[0]).query)["term"] == ["Dancing Queen official video"]

    def test_deve_mandar_aspas_do_titulo_sem_tratamento_especial(self):
        # O iTunes recebe texto livre; o escape que o MusicBrainz exigia sumiu.
        service, urls = self._servico([])

        service.search(
            MusicSearchSuggestion(title='Best of You "Live"', artist="Foo Fighters"))

        assert parse_qs(urlparse(urls[0]).query)["term"] == ['Foo Fighters Best of You "Live"']

    def test_deve_limitar_o_que_exibe_ao_numero_de_resultados_mostrados(self):
        service, urls = self._servico([_RESULTADO_ITUNES] * 10)

        candidates = service.search(MusicSearchSuggestion(title="Like a Stone"))

        assert parse_qs(urlparse(urls[0]).query)["limit"] == [str(CATALOG_RESULTS_SHOWN)]
        assert len(candidates) == CATALOG_RESULTS_SHOWN


class TestImportacaoDeCandidato:
    def test_deve_gravar_no_mp3_apenas_os_dados_do_candidato_escolhido(self, tmp_path):
        arquivo = tmp_path / "dancing-queen.mp3"
        ID3().save(arquivo)
        candidate = MusicMetadataCandidate(
            track_id="265452073", title="Dancing Queen", artist="ABBA",
            album="Arrival", year="1976", artwork_url=None,
        )

        MusicMetadataService().apply_to_mp3(arquivo, candidate)

        tags = ID3(arquivo)
        assert tags["TIT2"].text == ["Dancing Queen"]
        assert tags["TPE1"].text == ["ABBA"]
        assert tags["TALB"].text == ["Arrival"]
        assert [str(value) for value in tags["TDRC"].text] == ["1976"]

    def test_deve_incorporar_a_capa_quando_o_candidato_tem_release(self, tmp_path):
        arquivo = tmp_path / "dancing-queen.mp3"
        ID3().save(arquivo)
        candidate = MusicMetadataCandidate(
            track_id="265452073", title="Dancing Queen", artist="ABBA",
            album="Arrival", year="1976", artwork_url="https://exemplo.com/600x600bb.jpg",
        )
        service = MusicMetadataService(fetch_cover=lambda _release_id: (b"capa", "image/jpeg"))

        service.apply_to_mp3(arquivo, candidate)

        tags = ID3(arquivo)
        assert tags.getall("APIC")[0].data == b"capa"


class TestPreviaDoQueJaEstaNoArquivo:
    def test_deve_ler_artista_e_capa_gravados_no_mp3(self, tmp_path):
        arquivo = tmp_path / "like-a-stone.mp3"
        tags = ID3()
        tags.add(TPE1(encoding=3, text="AudioslaveVEVO"))
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Capa", data=b"capa"))
        tags.save(arquivo)

        embedded = MusicMetadataService().read_embedded(arquivo)

        assert embedded.artist == "AudioslaveVEVO"
        assert embedded.cover == b"capa"

    def test_deve_relatar_arquivo_sem_tags_sem_quebrar(self, tmp_path):
        arquivo = tmp_path / "sem-tags.mp3"
        arquivo.write_bytes(b"")

        embedded = MusicMetadataService().read_embedded(arquivo)

        assert embedded == EmbeddedMetadata()

    def test_deve_recusar_arquivo_inexistente_em_vez_de_dizer_que_esta_vazio(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            MusicMetadataService().read_embedded(tmp_path / "nao-existe.mp3")

    def test_deve_recusar_pendencia_sem_caminho_de_arquivo(self):
        with pytest.raises(FileNotFoundError):
            MusicMetadataService().read_embedded(Path(""))

    def test_deve_publicar_a_previa_na_fila_sem_abrir_arquivo_pela_ui(self):
        class CatalogoComArquivo:
            def read_embedded(self, _file_path):
                return EmbeddedMetadata(artist="AudioslaveVEVO", cover=b"capa")

        fila = queue.Queue()
        manager = DownloadManager(fila, metadata_service=CatalogoComArquivo())
        pending = MetadataPendingItem(
            "Audioslave - Like a Stone", "/tmp/musica.mp3",
            ("artista provisorio: canal AudioslaveVEVO",),
        )

        manager.load_embedded_metadata(pending)

        event = fila.get_nowait()
        assert event["type"] == "metadata_embedded"
        assert event["pending_item"] == pending
        assert event["embedded"].artist == "AudioslaveVEVO"
        assert event["embedded"].cover == b"capa"

    def test_deve_avisar_quando_o_arquivo_nao_pode_ser_lido(self):
        class CatalogoQuebrado:
            def read_embedded(self, _file_path):
                raise OSError("arquivo removido")

        fila = queue.Queue()
        manager = DownloadManager(fila, metadata_service=CatalogoQuebrado())
        pending = MetadataPendingItem("Faixa", "/tmp/sumiu.mp3", ("capa ausente",))

        manager.load_embedded_metadata(pending)

        event = fila.get_nowait()
        assert event["type"] == "metadata_embedded_unavailable"
        assert event["pending_item"] == pending


class TestEventosDeBuscaDeMetadata:
    def test_deve_publicar_candidatos_na_fila_sem_tocar_na_ui(self):
        candidate = MusicMetadataCandidate(
            track_id="265452073", title="Dancing Queen", artist="ABBA",
            album="Arrival", year="1976", artwork_url="https://exemplo.com/600x600bb.jpg",
        )

        class CatalogoFalso:
            def search(self, _suggestion):
                return [candidate]

        fila = queue.Queue()
        manager = DownloadManager(fila, metadata_service=CatalogoFalso())
        pending = MetadataPendingItem("ABBA - Dancing Queen", "/tmp/musica.mp3", ("artista",))

        manager.search_metadata(pending)

        event = fila.get_nowait()
        assert event["type"] == "metadata_results"
        assert event["pending_item"] == pending
        assert event["candidates"] == [candidate]

    def test_deve_publicar_preview_da_capa_na_fila_sem_acessar_a_ui(self):
        candidate = MusicMetadataCandidate(
            track_id="265452073", title="Dancing Queen", artist="ABBA",
            album="Arrival", year="1976", artwork_url="https://exemplo.com/600x600bb.jpg",
        )

        class CatalogoComCapa:
            def get_cover_preview(self, _candidate):
                return b"capa", "image/jpeg"

        fila = queue.Queue()
        manager = DownloadManager(fila, metadata_service=CatalogoComCapa())

        manager.load_metadata_cover_preview(candidate)

        event = fila.get_nowait()
        assert event["type"] == "metadata_cover_preview"
        assert event["candidate"] == candidate
        assert event["data"] == b"capa"
        assert event["mime"] == "image/jpeg"
