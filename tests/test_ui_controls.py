"""
SDD — Especificação: acionamento dos controles principais

CONTRATO
  Um botão visual do Media Downloader deve preservar o mecanismo de clique do
  CustomTkinter: ao liberar o mouse dentro de um botão habilitado, o comando
  associado precisa ser executado.

POR QUE EXISTE
  `HoverButton` adicionava feedback visual sobrescrevendo `_on_release`, um
  método interno de `CTkButton` responsável por chamar `command`. O resultado
  era uma tela aparentemente normal em que "Baixar mídia" e "Abrir pasta" não
  faziam nada — inclusive a pasta Downloads não era criada.

REGRA DE NEGÓCIO
  Estilo visual adicional não pode impedir a ação solicitada pelo usuário.
"""

import app
from app import HoverButton, MediaDownloaderApp


class TestAcionamentoDosControles:
    def test_deve_executar_o_comando_quando_o_botao_e_liberado_dentro_da_area(self):
        chamadas = []
        botao = object.__new__(HoverButton)
        botao._mouse_inside = True
        botao._state = "normal"
        botao._command = lambda: chamadas.append("executado")
        botao._on_leave = lambda: None
        botao._click_animation = lambda: None
        botao.after = lambda _ms, _callback: None

        botao._on_release()

        assert chamadas == ["executado"]


class TestAberturaDaPastaDeDownloads:
    def test_deve_criar_e_abrir_a_pasta_com_xdg_open_no_linux(self, tmp_path, monkeypatch):
        chamadas = []
        aplicativo = object.__new__(MediaDownloaderApp)
        destino = tmp_path / "Downloads"
        monkeypatch.setattr(app, "BASE_DOWNLOADS_DIR", destino)
        monkeypatch.setattr(app.sys, "platform", "linux")
        monkeypatch.setattr(app.subprocess, "Popen", lambda argumentos: chamadas.append(argumentos))

        aplicativo.open_downloads_folder()

        assert destino.is_dir()
        assert chamadas == [["xdg-open", str(destino)]]
