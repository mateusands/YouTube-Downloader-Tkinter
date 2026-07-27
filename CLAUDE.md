# CLAUDE.md — Media Downloader

## Propósito do projeto

Aplicação desktop em Python com interface dark mode (CustomTkinter) para baixar vídeo ou áudio de plataformas
compatíveis com o yt-dlp. Aceita links HTTP/HTTPS e deixa a confirmação de suporte para o yt-dlp; preserva a
detecção explícita de playlists do YouTube para não baixar uma coleção inteira quando o usuário forneceu o link de
um único vídeo. Organiza os downloads em pastas por tipo, mostra progresso em tempo real e um resumo com os itens
que falharam.

Projeto de portfólio.

---

## Fonte da verdade

**O estado real do sistema é o código.** É um arquivo — `src/app.py` — mas bem separado em
camadas (ver abaixo). Leia a camada relevante antes de mudar.

---

## Stack

- **Python 3.10+** (o ambiente local está em 3.14)
- **yt-dlp** — download e extração de metadados
- **mutagen** — leitura e escrita de tags ID3 e capa em MP3
- **CustomTkinter** — widgets dark mode sobre Tkinter
- **FFmpeg** (binário do sistema) — obrigatório para MP3 e para juntar vídeo+áudio em MP4
- **pytest** — suíte da lógica pura (backend), sem abrir janela

### Estrutura

```
youtube-downloader-tkinter/
├── requirements.txt        # dependências para rodar o app
├── requirements-dev.txt    # + pytest (desenvolvimento)
├── pytest.ini              # pythonpath=src, testpaths=tests
├── src/
│   └── app.py              # tudo, em 3 camadas: dados · backend (DownloadManager) · UI (MediaDownloaderApp)
├── assets/                 # ícone SVG mestre, PNG da UI e ICO para Windows
└── tests/
    ├── test_url.py             # validação e classificação de URL
    └── test_download_manager.py # interpretação do resultado do yt-dlp + relato de falhas
    └── test_music_metadata.py  # sugestão, catálogo e importação de metadata escolhida
```

Os downloads vão para `Downloads/` na raiz do repo, em subpastas:

| Formato | Item único | Playlist |
|---|---|---|
| mp3 | `Downloads/audios_unicos/` | `Downloads/playlist_audio/` |
| mp4 | `Downloads/videos_unicos/` | `Downloads/playlist_video/` |

---

## Arquitetura — a separação que dá valor a este projeto

O arquivo é único, mas as camadas são de verdade e **não devem ser misturadas**:

### 1. Dados
- `DownloadSummary` (dataclass) — contadores, itens que falharam, pendências de metadata, pasta de destino e modo playlist.
- `MetadataPendingItem` e `MusicMetadataCandidate` — dados imutáveis que atravessam a fila; nenhum campo
  de tag é inferido e gravado sem confirmação.

### 2. Backend — `DownloadManager`
**Não conhece a UI.** Não importa widget, não chama `messagebox`, não toca em `root`. Comunica-se
exclusivamente por uma `queue.Queue`, publicando eventos com `_emit(tipo, **payload)`.

- `download(url, file_format, include_metadata)` — orquestra: detecta playlist → extrai info → monta opções → baixa
- `_build_opts(...)` — opções do yt-dlp (formato, template de saída, hooks)
- `_make_progress_hook(...)` — traduz o progresso do yt-dlp em evento na fila
- `MusicMetadataService` — pesquisa candidatos no MusicBrainz e incorpora no MP3 apenas o candidato selecionado;
  busca a capa no Cover Art Archive, tentando as releases da gravação em ordem de procedência.
  `read_embedded` lê de volta o que já está gravado no arquivo — é a fonte da prévia mostrada na UI.
- `metadata_review_reasons(info)` — diz o que o yt-dlp realmente gravou (artista da origem, artista
  provisório vindo do canal, ou ausente); `metadata_review_detail` transforma isso na frase da UI.
- `ReportingLogger` — captura warning/error do yt-dlp e acumula em `summary.failed_items`; ao concluir,
  `_reconcile_failure_reports` remove diagnósticos técnicos quando todos os itens previstos baixaram.

### 3. UI — `MediaDownloaderApp`
Consome a fila por **polling**: `self.root.after(100, self._poll)` reagenda a cada 100 ms, drenando a
`queue` com `get_nowait()` e despachando para `_handle(event)`.

> **Este é o padrão de concorrência do projeto: fila + polling.** Não é `root.after(0, callback)` chamado
> de dentro da thread — é a thread publicando na fila e a UI lendo sozinha. Ao adicionar comunicação
> thread→UI, **use a fila existente**, não invente um segundo mecanismo.

O download roda em `threading.Thread(target=self._manager.download, daemon=True)`, guardada em
`self._thread` para o guard de "download em andamento".

---

## Regras de desenvolvimento

- **`DownloadManager` nunca importa nem toca em widget.** Essa fronteira é o que torna a lógica testável
  isolada — é a melhor característica do projeto, não a quebre por conveniência.
- **Comunicação thread→UI só pela `queue`.** Evento novo = novo `type` tratado em `_handle`.
- **Um download por vez.** `start_download` já bloqueia se `self._thread.is_alive()`. Mantenha o guard.
- **Metadata pendente não é falha.** `metadata_pending_items` precisa continuar separado de `failed_items`,
  sobretudo no resumo de playlists.
- **Inferência nunca é importação.** `suggest_music_search` pode interpretar o título para formular a busca,
  mas somente `MusicMetadataCandidate` confirmado pela pessoa pode ser gravado no arquivo.
- **Não chame de ausente o que está gravado.** O `FFmpegMetadata` do yt-dlp cai para o nome do canal quando
  a origem não publica `artist` — o MP3 sai com artista provisório (`AudioslaveVEVO`), não sem artista.
  A revisão nomeia o canal; dizer "faltam: artista" era falso e foi o que originou `metadata_review_reasons`.
- **A prévia mostra o arquivo, não a suposição.** O que aparece no diálogo de revisão vem de
  `read_embedded`, lido pelo backend numa thread e publicado na fila — a thread gráfica não abre arquivo.
- **`ignoreerrors: True`** faz o yt-dlp continuar a playlist quando um item falha — por isso existe
  `failed_items` no resumo. Não "conserte" isso para abortar tudo no primeiro erro.
- **Não logue a URL completa** em nada persistente; pode conter parâmetros de sessão.
- **Não adicione opção de yt-dlp que contorne restrição de acesso.** A ferramenta baixa o que o usuário já
  pode acessar.

---

## Regra inegociável: SDD + BDD + TDD

Nenhum código de produção é escrito sem spec (SDD) → comportamento (BDD) → teste vermelho (TDD).
Sem exceções, mesmo em mudança pequena. Os três andam juntos, **nessa ordem**, no mesmo arquivo de teste.

### 1. SDD — a spec vem primeiro, e mora no topo do arquivo de teste

Cabeçalho explicando **qual é o contrato**, **por que existe** (o bug ou a decisão que o originou) e
**o que é regra de negócio**. É a spec que sobrevive ao esquecimento; o teste sozinho não explica o porquê.

### 2. BDD — descreva COMPORTAMENTO, não implementação

`class Test<CenárioDeNegócio>` → `def test_deve_<resultado>_quando_<condição>`, em português, na
linguagem da operação (download, playlist, item que falhou). Se o nome do teste cita variável interna,
você está testando implementação — reescreva.

### 3. TDD — ciclo obrigatório

**Red** (escreva o teste, rode, **tem que falhar**) → **Green** (mínimo para passar) → **Refactor**.

### O que testar (por prioridade)

| Prioridade | Alvo | Exemplos |
|---|---|---|
| 🔴 Alta | Helpers puros do backend | `_valid_url`, `_url_is_playlist`, `_is_playlist_result`, `_count_items` |
| 🔴 Alta | Tradução de eventos | `ReportingLogger` (dedup de falha, remoção de prefixo) |
| 🟡 Média | Montagem de opções | `_build_opts` — formato, `outtmpl`, `noplaylist` |
| 🟢 Baixa | UI | jsdom não existe aqui; comportamento de widget valida-se à mão |

**Mocks só para o externo** (yt-dlp, rede, FFmpeg). O `DownloadManager` já é testável sem mock porque
não conhece a UI — **essa fronteira é o que sustenta a suíte**, por isso ela é inegociável.

⚠️ **Cuidado com mock que esconde bug:** se o comportamento só existe quando o yt-dlp é mockado, isole a
regra numa função pura e teste ela direto.

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest                      # suíte completa
pytest -k playlist          # um recorte
```

Depois de verde, **exercite de verdade** — baixar um vídeo é o que a suíte não cobre.

---

### Convenção de commits

Conventional Commits: `feat: adiciona escolha de qualidade`, `fix: trata playlist privada`,
`test: cobre contagem de itens com entradas nulas`, `refactor: extrai construção de opts`.

---

## Armadilhas ativas

1. **FFmpeg é obrigatório e a falha é confusa.** MP3 usa o postprocessor `FFmpegExtractAudio`; MP4 usa
   `merge_output_format` (o yt-dlp baixa vídeo e áudio separados e junta). Sem FFmpeg no PATH, o download
   parece progredir e falha na conversão, com mensagem que não diz "instale o ffmpeg".

2. **yt-dlp quebra sozinho.** O YouTube muda, e a versão instalada para de funcionar sem nada ter mudado
   no código. Erro de extração é **primeiro** suspeito de versão velha: `pip install -U yt-dlp`.

3. **`"remote_components": ["ejs:github"]`** em `_build_opts` faz o yt-dlp buscar componentes remotos —
   depende de rede além do YouTube e pode falhar em ambiente restrito.

4. **Template de saída com `%(title)s`** — títulos com `/`, emoji ou nome muito longo geram problema de
   nome de arquivo, variando por sistema de arquivos.

5. **URL aceita não é URL suportada.** `_valid_url` só exige HTTP/HTTPS com host; a confirmação de suporte,
   disponibilidade e acesso pertence ao yt-dlp. Não liste plataformas como garantia: a tela mostra exemplos e
   aponta para a lista oficial atualizada.

6. **`BASE_DOWNLOADS_DIR` é relativo ao arquivo** (`Path(__file__).resolve().parent.parent / "Downloads"`),
   não ao diretório de trabalho. Mover `app.py` de lugar muda onde os downloads caem.

7. **A busca do MusicBrainz devolve bootleg antes do álbum.** Para "Like a Stone" as primeiras dezenas de
   resultados são gravações de show — e bootleg quase nunca tem capa no Cover Art Archive, então a prévia
   ficava sempre vazia. Por isso a consulta pede `CATALOG_SEARCH_LIMIT` (25) e exibe as
   `CATALOG_RESULTS_SHOWN` (5) melhores por `_release_quality`. Não reduza o limite da consulta ao número
   exibido.

8. **`wraplength` maior que a coluna corta a frase.** O Tk não encolhe a linha para caber: o texto é
   clipado no meio, sem reticências. O `minsize` do diálogo de revisão acompanha o `wraplength` da linha
   de motivos — mexer em um exige mexer no outro.

---

## Regras gerais

- **O código é a fonte da verdade.** Se algo aqui parecer inconsistente com o código, o código vence —
  e atualize este arquivo.
- Decisão técnica não-óbvia deve ser documentada (no commit e/ou aqui).
- **Não commite nem faça push sem ordem explícita.**
