"""
SDD — Especificação: onde o aplicativo procura assets e grava downloads

CONTRATO
  `BASE_DOWNLOADS_DIR` e `ASSETS_DIR` apontam para a raiz do repositório,
  não para a pasta do módulo que os declara.

POR QUE EXISTE
  Os dois são derivados de `Path(__file__)`. Enquanto tudo morava em
  `src/app.py`, subir dois níveis chegava à raiz. Ao dividir o código em
  `src/media_downloader/`, o mesmo cálculo passou a parar em `src/`: a janela
  não abriu, porque o ícone foi procurado em `src/assets/`, e os downloads
  cairiam em `src/Downloads/`. A suíte continuou verde o tempo todo — nenhum
  teste olhava para caminho.

REGRA DE NEGÓCIO
  - A raiz é derivada aqui de forma independente (a partir de `tests/`), senão
    o teste repetiria o erro que deveria pegar.
  - O ícone da janela precisa existir no disco: é carregado no boot da UI, e
    ausência dele derruba o aplicativo antes de qualquer tela.
  - As quatro pastas de destino ficam sob `Downloads/`.
"""

from pathlib import Path

from media_downloader.config import (
    APP_ICON_PATH,
    ASSETS_DIR,
    BASE_DOWNLOADS_DIR,
    DOWNLOAD_FOLDERS,
)

RAIZ = Path(__file__).resolve().parent.parent


class TestCaminhosDoProjeto:
    def test_deve_gravar_os_downloads_na_raiz_do_repositorio(self):
        assert BASE_DOWNLOADS_DIR == RAIZ / "Downloads"

    def test_deve_procurar_os_assets_na_raiz_do_repositorio(self):
        assert ASSETS_DIR == RAIZ / "assets"

    def test_deve_encontrar_o_icone_usado_no_boot_da_janela(self):
        assert APP_ICON_PATH.is_file()

    def test_deve_manter_as_quatro_pastas_de_destino_sob_downloads(self):
        assert len(DOWNLOAD_FOLDERS) == 4
        assert all(pasta.parent == BASE_DOWNLOADS_DIR for pasta in DOWNLOAD_FOLDERS.values())
