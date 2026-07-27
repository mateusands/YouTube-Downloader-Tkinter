"""
SDD — Especificação: diagnóstico da metadata gravada no MP3

CONTRATO
  Quando a opção de capa e metadata está ligada, o yt-dlp grava no MP3 o que a
  origem publicou. `metadata_review_reasons(info)` diz o que de fato foi
  gravado, e `metadata_review_detail` transforma isso na frase que a interface
  mostra. `suggest_music_search` interpreta o título só para formular a busca —
  texto inferido nunca vira tag por si só.

POR QUE EXISTE
  O yt-dlp só preenche `artist` quando a própria origem publica dado musical —
  em vídeo comum do YouTube ele é nulo, e o `FFmpegMetadata` grava no MP3 o nome
  do canal ("AudioslaveVEVO"). Dizer "faltam: artista" para
  "Audioslave - Like a Stone (Official Video)" era falso duas vezes: o arquivo
  tem artista gravado, e o título traz o artista real.

REGRA DE NEGÓCIO
  - Artista vindo da origem (artist/artists/creator/creators) não gera revisão.
  - Artista derivado do canal é PROVISÓRIO, não ausente: a revisão nomeia o
    canal que virou tag.
  - Só é "ausente" o que não tem nem origem nem canal.
  - O padrão "Artista - Faixa" gera artista e faixa sugeridos, removendo sufixo
    promocional conhecido.
  - Título sem separador continua pesquisável, mas sem artista inferido.
  - Quando o título sugere artista, a interface pede confirmação no catálogo;
    ela não afirma que o artista está ausente nem grava a sugestão como tag.
"""

from app import (
    MetadataPendingItem,
    metadata_review_detail,
    metadata_review_reasons,
    suggest_music_search,
)


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

