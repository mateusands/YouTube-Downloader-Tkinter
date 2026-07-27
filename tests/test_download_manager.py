"""
SDD — Especificação: interpretação do resultado do yt-dlp e relato de falhas

CONTRATO
  Depois de `_extract_info`, o `DownloadManager` precisa decidir duas coisas a
  partir de um dicionário que o yt-dlp devolve num formato variável:
  `_is_playlist_result(info)` — o que veio é mesmo uma playlist?
  `_count_items(info, playlist_mode)` — quantos itens serão baixados?
  E o `ReportingLogger` traduz warning/error do yt-dlp em `summary.failed_items`.

POR QUE EXISTE
  `ignoreerrors: True` faz o yt-dlp CONTINUAR a playlist quando um item falha e
  colocar `None` no lugar da entrada quebrada. Sem isso, `_count_items` contaria
  buracos como itens e o resumo final mentiria para o usuário. O modo playlist
  também é reavaliado aqui: a URL pode parecer playlist e o resultado vir único.

REGRA DE NEGÓCIO
  - Entrada `None` numa playlist é buraco, não item.
  - A contagem nunca é zero (mínimo 1), senão a barra de progresso divide por zero.
  - Falha repetida não é listada duas vezes no resumo.
"""

import queue

from app import DownloadManager, DownloadSummary, ReportingLogger

eh_playlist_resultado = DownloadManager._is_playlist_result
contar = DownloadManager._count_items


class TestClassificacaoDoResultado:
    def test_deve_ser_playlist_quando_ha_entries(self):
        assert eh_playlist_resultado({"entries": [{"id": "a"}]}) is True

    def test_deve_ser_playlist_quando_o_tipo_declara_playlist(self):
        assert eh_playlist_resultado({"_type": "playlist"}) is True

    def test_nao_deve_ser_playlist_quando_o_resultado_e_um_video_unico(self):
        assert eh_playlist_resultado({"id": "abc", "title": "Um vídeo"}) is False

    def test_nao_deve_ser_playlist_quando_entries_vem_vazio(self):
        # Caso real: URL de playlist que resolveu para um item só.
        assert eh_playlist_resultado({"entries": []}) is False


class TestContagemDeItens:
    def test_deve_contar_um_quando_nao_e_modo_playlist(self):
        assert contar({"entries": [1, 2, 3]}, playlist_mode=False) == 1

    def test_deve_contar_as_entradas_quando_e_modo_playlist(self):
        assert contar({"entries": [{"id": "a"}, {"id": "b"}]}, playlist_mode=True) == 2

    def test_nao_deve_contar_entradas_nulas_deixadas_por_ignoreerrors(self):
        info = {"entries": [{"id": "a"}, None, {"id": "b"}, None]}
        assert contar(info, playlist_mode=True) == 2

    def test_deve_contar_pelo_menos_um_quando_todas_as_entradas_falharam(self):
        # Proteção contra divisão por zero no cálculo de progresso.
        assert contar({"entries": [None, None]}, playlist_mode=True) == 1

    def test_deve_contar_pelo_menos_um_quando_nao_ha_entries(self):
        assert contar({}, playlist_mode=True) == 1


class TestRelatoDeFalhas:
    def _logger(self):
        fila = queue.Queue()
        resumo = DownloadSummary()
        return ReportingLogger(fila, resumo), fila, resumo

    def test_deve_registrar_a_falha_e_avisar_que_segue_com_os_demais(self):
        logger, fila, resumo = self._logger()

        logger.error("ERROR: Video unavailable")

        assert resumo.failed_items == ["Video unavailable"]
        evento = fila.get_nowait()
        assert evento["type"] == "status"
        assert "continuando" in evento["message"].lower()

    def test_deve_remover_o_prefixo_error_da_mensagem(self):
        logger, _, resumo = self._logger()

        logger.error("ERROR:   Private video  ")

        assert resumo.failed_items == ["Private video"]

    def test_nao_deve_listar_a_mesma_falha_duas_vezes(self):
        logger, fila, resumo = self._logger()

        logger.error("ERROR: Video unavailable")
        logger.error("ERROR: Video unavailable")

        assert resumo.failed_items == ["Video unavailable"]
        assert fila.qsize() == 1, "o segundo relato não deve gerar novo aviso"

    def test_deve_registrar_warning_como_falha(self):
        logger, _, resumo = self._logger()

        logger.warning("Alguma coisa deu errado")

        assert resumo.failed_items == ["Alguma coisa deu errado"]

    def test_nao_deve_registrar_mensagem_vazia(self):
        logger, fila, resumo = self._logger()

        logger.error("ERROR:   ")

        assert resumo.failed_items == []
        assert fila.empty()

    def test_debug_nao_deve_registrar_nada(self):
        logger, fila, resumo = self._logger()

        logger.debug("baixando fragmento 3/10")

        assert resumo.failed_items == []
        assert fila.empty()
