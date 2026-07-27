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
  - A release exibida é a de melhor procedência (oficial, álbum de estúdio),
    não a primeira que o MusicBrainz devolver: buscar "Like a Stone" trazia
    bootlegs de show no topo, todos sem capa no Cover Art Archive, e a prévia
    ficava sempre vazia. As demais releases da gravação ficam como alternativa
    para a capa.

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
  - A prévia mostra o que já está gravado no MP3 (artista e capa), lido pelo
    backend e publicado na fila — a thread gráfica não abre arquivo.
"""

import queue

from app import (
    DownloadManager,
    EmbeddedMetadata,
    MetadataPendingItem,
    MusicMetadataCandidate,
    MusicMetadataService,
    MusicSearchSuggestion,
    metadata_review_detail,
    metadata_review_reasons,
    suggest_music_search,
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


def _recording(recording_id: str, releases: list[dict]) -> dict:
    return {
        "id": recording_id,
        "title": "Like a Stone",
        "artist-credit": [{"name": "Audioslave"}],
        "releases": releases,
    }


_BOOTLEG_AO_VIVO = {
    "id": "release-bootleg",
    "title": "2003-03-07: Philadelphia, PA, USA",
    "status": "Bootleg",
    "date": "2003",
    "release-group": {"primary-type": "Album", "secondary-types": ["Live"]},
}
_ALBUM_OFICIAL = {
    "id": "release-oficial",
    "title": "Audioslave",
    "status": "Official",
    "date": "2002-11-19",
    "release-group": {"primary-type": "Album"},
}


class TestCandidatoDoCatalogo:
    def test_deve_exibir_dados_da_gravacao_e_da_primeira_release(self):
        candidate = MusicMetadataCandidate.from_musicbrainz({
            "id": "recording-id",
            "title": "Dancing Queen",
            "artist-credit": [{"name": "ABBA"}],
            "releases": [{
                "id": "release-id",
                "title": "Arrival",
                "date": "1976-10-11",
            }],
        })

        assert candidate.recording_id == "recording-id"
        assert candidate.artist == "ABBA"
        assert candidate.album == "Arrival"
        assert candidate.year == "1976"
        assert candidate.release_id == "release-id"

    def test_deve_preferir_o_album_oficial_ao_bootleg_de_show(self):
        candidate = MusicMetadataCandidate.from_musicbrainz(
            _recording("recording-id", [_BOOTLEG_AO_VIVO, _ALBUM_OFICIAL]),
        )

        assert candidate.album == "Audioslave"
        assert candidate.year == "2002"
        assert candidate.release_id == "release-oficial"

    def test_deve_guardar_as_demais_releases_como_alternativa_de_capa(self):
        candidate = MusicMetadataCandidate.from_musicbrainz(
            _recording("recording-id", [_BOOTLEG_AO_VIVO, _ALBUM_OFICIAL]),
        )

        assert candidate.release_ids == ("release-oficial", "release-bootleg")


class TestOrdemDosResultados:
    def _service(self, recordings: list[dict]):
        urls = []

        def responder(url: str):
            urls.append(url)
            return {"recordings": recordings}

        return MusicMetadataService(fetch_json=responder), urls

    def test_deve_listar_o_album_oficial_antes_do_registro_de_show(self):
        service, _ = self._service([
            _recording("gravacao-bootleg", [_BOOTLEG_AO_VIVO]),
            _recording("gravacao-oficial", [_ALBUM_OFICIAL]),
        ])

        candidates = service.search(MusicSearchSuggestion(title="Like a Stone", artist="Audioslave"))

        assert [candidate.recording_id for candidate in candidates] == [
            "gravacao-oficial", "gravacao-bootleg",
        ]

    def test_deve_consultar_alem_do_que_exibe_para_alcancar_a_versao_oficial(self):
        service, urls = self._service([
            _recording(f"gravacao-{indice}", [_BOOTLEG_AO_VIVO]) for indice in range(20)
        ])

        candidates = service.search(MusicSearchSuggestion(title="Like a Stone"))

        assert "limit=25" in urls[0]
        assert len(candidates) == 5


class TestCapaComReleaseAlternativa:
    def test_deve_tentar_a_proxima_release_quando_a_primeira_nao_tem_capa(self):
        tentativas = []

        def buscar_capa(release_id: str):
            tentativas.append(release_id)
            if release_id == "release-oficial":
                raise OSError("404")
            return b"capa", "image/jpeg"

        service = MusicMetadataService(fetch_cover=buscar_capa)
        candidate = MusicMetadataCandidate.from_musicbrainz(
            _recording("recording-id", [_BOOTLEG_AO_VIVO, _ALBUM_OFICIAL]),
        )

        assert service.get_cover_preview(candidate) == (b"capa", "image/jpeg")
        assert tentativas == ["release-oficial", "release-bootleg"]

    def test_deve_relatar_ausencia_quando_nenhuma_release_tem_capa(self):
        def buscar_capa(_release_id: str):
            raise OSError("404")

        service = MusicMetadataService(fetch_cover=buscar_capa)
        candidate = MusicMetadataCandidate.from_musicbrainz(
            _recording("recording-id", [_BOOTLEG_AO_VIVO]),
        )

        assert service.get_cover_preview(candidate) is None


class TestBuscaNoCatalogo:
    def test_deve_transformar_resultados_do_musicbrainz_em_candidatos(self):
        urls = []

        def responder(url: str):
            urls.append(url)
            return {"recordings": [{
                "id": "recording-id",
                "title": "Dancing Queen",
                "artist-credit": [{"name": "ABBA"}],
                "releases": [{"id": "release-id", "title": "Arrival", "date": "1976"}],
            }]}

        service = MusicMetadataService(fetch_json=responder)
        candidates = service.search(MusicSearchSuggestion(title="Dancing Queen", artist="ABBA"))

        assert [candidate.title for candidate in candidates] == ["Dancing Queen"]
        assert "recording%3A%22Dancing+Queen%22" in urls[0]
        assert "artist%3A%22ABBA%22" in urls[0]


class TestImportacaoDeCandidato:
    def test_deve_gravar_no_mp3_apenas_os_dados_do_candidato_escolhido(self, tmp_path):
        arquivo = tmp_path / "dancing-queen.mp3"
        ID3().save(arquivo)
        candidate = MusicMetadataCandidate(
            recording_id="recording-id", title="Dancing Queen", artist="ABBA",
            album="Arrival", year="1976", release_id=None,
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
            recording_id="recording-id", title="Dancing Queen", artist="ABBA",
            album="Arrival", year="1976", release_id="release-id",
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
            recording_id="recording-id", title="Dancing Queen", artist="ABBA",
            album="Arrival", year="1976", release_id="release-id",
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
            recording_id="recording-id", title="Dancing Queen", artist="ABBA",
            album="Arrival", year="1976", release_id="release-id",
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
