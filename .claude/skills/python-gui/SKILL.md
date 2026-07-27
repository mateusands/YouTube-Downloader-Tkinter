---
name: python-gui
description: Desenvolvimento do YouTube Downloader (CustomTkinter + yt-dlp). Codifica as convenções do repo — a fronteira DownloadManager↔UI, comunicação por queue + polling, opções do yt-dlp, dependência de FFmpeg. Use ao mexer em src/app.py.
---

# Python GUI — YouTube Downloader

Guia para qualquer mexida no app. Segue o `CLAUDE.md`: **a fronteira backend↔UI é inegociável**,
**sem commit/push sem ordem**.

---

## A regra que define este projeto: `DownloadManager` não conhece a UI

`DownloadManager` **não importa widget, não chama `messagebox`, não recebe `root`**. Ele publica eventos
numa `queue.Queue`:

```python
def _emit(self, event_type: str, **payload: Any) -> None:
    self._q.put({"type": event_type, **payload})
```

A `YouTubeDownloaderApp` drena a fila sozinha, por polling:

```python
def _poll(self) -> None:
    while True:
        try:
            event = self._q.get_nowait()
        except queue.Empty:
            break
        self._handle(event)
    self.root.after(100, self._poll)     # se reagenda a cada 100 ms
```

**Por que isso importa:** é o que permite testar toda a lógica de download sem abrir janela — a melhor
característica do projeto. Passar `root` ou um widget para o manager "só dessa vez" destrói isso.

### Ao adicionar comunicação thread → UI

1. Publique um evento novo: `self._emit("meu_evento", campo=valor)`
2. Trate em `YouTubeDownloaderApp._handle(event)`, pelo `event["type"]`

**Não** chame `root.after(0, ...)` de dentro da thread de download. O projeto tem **um** mecanismo
(fila + polling); um segundo mecanismo em paralelo é o começo de bug de concorrência difícil de achar.

> Observação: `root.after(...)` na própria thread da UI é normal e usado aqui (`_poll`, `_reset_url_hint`).
> A regra é sobre a thread de trabalho.

---

## Um download por vez

`start_download` já protege:

```python
if self._thread and self._thread.is_alive():
    messagebox.showwarning("Download em andamento", ...)
    return
```

Mantenha o guard. Se algum dia for suportar fila de downloads, isso é mudança de arquitetura (a `queue`
hoje carrega eventos, não trabalho) — proponha antes de fazer.

---

## Mexer nas opções do yt-dlp (`_build_opts`)

As opções atuais e o porquê de cada uma:

| Opção | Por quê |
|---|---|
| `ignoreerrors: True` | um item ruim não aborta a playlist inteira — é o que alimenta `failed_items` |
| `noplaylist: not playlist_mode` | impede baixar a playlist toda quando o usuário quis só o vídeo |
| `quiet` + `no_warnings` + `logger` | a saída vai para `ReportingLogger`, não para o terminal |
| `progress_hooks` | alimenta a barra de progresso pela fila |
| `concurrent_fragment_downloads: 1` | progresso legível; aumentar acelera mas embaralha o percentual |
| `outtmpl` com `%(playlist_title,...)s` | agrupa a playlist numa subpasta |

**MP3** usa o postprocessor `FFmpegExtractAudio` (192 kbps). **MP4** usa
`bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b` + `merge_output_format` — o yt-dlp baixa vídeo e áudio
separados e junta. **Os dois caminhos dependem de FFmpeg no PATH.**

Ao mexer no seletor de formato, lembre que a cadeia com `/` é uma lista de fallbacks em ordem de
preferência — remover um degrau faz o download falhar em vídeos que só têm o formato de trás.

---

## FFmpeg: a dependência que não está no `requirements.txt`

É um **binário do sistema**, não um pacote pip:

```bash
sudo pacman -S ffmpeg          # Arch/CachyOS
sudo apt install ffmpeg        # Debian/Ubuntu
```

Sem ele o download **parece funcionar** e falha na conversão, com mensagem que não diz "instale o
ffmpeg". Se for melhorar isso, o lugar certo é uma checagem no boot (`shutil.which("ffmpeg")`) com aviso
claro — é uma melhoria de UX real, mas peça antes de fazer.

---

## Não travar a interface

Tkinter é single-threaded. O download já roda em `threading.Thread(daemon=True)`. Ao adicionar operação
nova que demore (varrer pasta, ler metadados, chamar rede):

- Vai para thread, publica na fila, a UI reage no `_handle`.
- **Nenhuma chamada de widget dentro da thread.**
- `daemon=True` para não segurar o processo ao fechar a janela.
- Desabilite os controles com `_set_busy(True)` e reabilite em **todos** os caminhos de saída, inclusive
  o de erro. Botão preso em "ocupado" após falha é o bug mais comum desse padrão.

---

## Estilo

As cores são constantes no topo do arquivo (`BG_DARK`, `CLR_RED`, `CLR_MUTED`…). Use as existentes; se
faltar, acrescente lá — nada de hex literal no meio do código de widget.

⚠️ `FONT_FAMILY = "Segoe UI"` **não existe no Linux**; o Tk faz fallback silencioso. Diferença visual
entre plataformas é esperada.

---

## Segurança e escopo

- **Não logue a URL completa** em nada persistente — pode conter parâmetros de sessão.
- **Não adicione opção que contorne restrição de acesso** (cookies de conta alheia, bypass de idade ou de
  bloqueio regional). A ferramenta baixa o que o usuário já pode acessar.
- **Título de vídeo é entrada não confiável** — vai para nome de arquivo. `/`, `\`, emoji e nomes longos
  quebram de formas diferentes em cada sistema de arquivos.
- **Nunca sobrescreva arquivo existente sem avisar**; o `outtmpl` pode colidir com download anterior.

---

## SDD + BDD + TDD (obrigatório) + validar verde

**Ordem: spec → comportamento → teste falhando → código.** Detalhe completo no `CLAUDE.md`.

- **SDD:** cabeçalho do arquivo de teste explica o **contrato** e o **porquê** (o bug ou a decisão que o
  originou). Veja `tests/test_download_manager.py` como modelo.
- **BDD:** `class Test<Cenário>` → `def test_deve_<resultado>_quando_<condição>`, em português, na
  linguagem da operação (download, playlist, item que falhou) — não na do código.
- **TDD:** Red (roda e **falha**) → Green (mínimo para passar) → Refactor.

**Alvo prioritário:** o backend. `DownloadManager` e os helpers estáticos (`_url_is_playlist`,
`_is_playlist_result`, `_count_items`, `_valid_url`) e o `ReportingLogger` são testáveis **sem abrir
janela** — mérito da fronteira descrita no topo desta skill. É por isso que ela é inegociável: quebrar a
separação backend↔UI derruba a suíte inteira junto.

**Mocks só para o externo** (yt-dlp, rede, FFmpeg). ⚠️ Se um comportamento só se manifesta com o yt-dlp
mockado, o mock está escondendo o caminho real — extraia a regra para uma função pura e teste ela direto.

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest                # suíte completa
pytest -k playlist    # um recorte
```

**Verde não basta.** A suíte cobre a lógica, não o download. Depois de passar, baixe de verdade — roteiro
em `/rodar-local`, no mínimo um vídeo único e uma playlist curta, nos dois formatos. Seja honesto no
relato sobre o que rodou de fato.
