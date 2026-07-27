---
name: codereview
description: Code review sênior das últimas mudanças do YouTube Downloader, focado na fronteira backend↔UI, concorrência (queue + polling), robustez do yt-dlp e manutenibilidade. Apenas reporta problemas com arquivo/linha e a refatoração sugerida — não aplica correções.
---

# Code Review Sênior — YouTube Downloader

Atue como Engenheiro Sênior e revise criticamente as **últimas mudanças deste repositório**.

## Como identificar o que revisar (nesta ordem)

1. Working tree: `git status` + `git diff` + arquivos novos relevantes.
2. Se limpo, os últimos commits da branch (`git log` + `git show`).
3. **Leia a camada inteira** que o diff toca. O arquivo é único, mas as camadas (dados · `DownloadManager`
   · `YouTubeDownloaderApp`) são independentes — revisar um trecho sem ver a camada é revisar no escuro.

## Pilar 1 — A fronteira backend ↔ UI (a invariante mais importante)

- **`DownloadManager` importa widget, chama `messagebox` ou recebe `root`?** Isso destrói a separação que
  torna a lógica testável sem abrir janela — a melhor característica do projeto. Reporte no topo.
- **Comunicação thread → UI fora da fila?** O projeto tem **um** mecanismo: `_emit` publica na
  `queue.Queue`, `_poll` drena e `_handle` despacha. `root.after(0, ...)` chamado de dentro da thread de
  download é um segundo mecanismo em paralelo — origem de bug de concorrência difícil de reproduzir.
- **Evento novo tratado em `_handle`?** `_emit` de um `type` que ninguém trata é silenciosamente
  descartado — nenhum erro, só a UI que não reage.

## Pilar 2 — Concorrência

- **Widget tocado dentro da thread de download** (`configure`, `set`, `insert`). Verifique linha a linha
  o corpo do que roda em thread.
- **Guard de download único** — `start_download` checa `self._thread.is_alive()`. O diff introduziu
  caminho que dispara download sem passar por esse guard?
- **`daemon=True`** na thread nova? Sem isso o processo não morre ao fechar a janela.
- **`_set_busy(False)` em TODOS os caminhos de saída**, inclusive erro e cancelamento. Botão preso em
  "ocupado" após falha é o bug clássico deste padrão.
- **Estado compartilhado entre thread e UI** sem ser via fila (ex.: a thread escrevendo em `self._algo`
  que a UI lê). `DownloadSummary` é preenchido na thread e lido no resumo — se o diff ampliar esse
  padrão, avalie a corrida.
- **`_poll` continua se reagendando** em todos os caminhos? Um `return` cedo mata o polling e a UI congela
  para sempre, sem erro.

## Pilar 3 — Robustez com yt-dlp e rede

- **`ignoreerrors: True` preservado?** É intencional: um item ruim não aborta a playlist, e é o que
  alimenta `failed_items`. Se o diff o remove, a playlist passa a morrer no primeiro erro.
- **Cadeia de fallback do formato** (`bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b`) — remover um degrau
  faz falhar em vídeos que só têm o formato de trás. Mudança aí precisa de justificativa.
- **Dependência de FFmpeg** — o diff adiciona caminho que precisa dele sem tratar a ausência? A falha é
  confusa (parece erro de download).
- **Exceção de rede tratada?** Timeout, DNS, 403 do YouTube. O `catch` chega ao usuário ou some?
- **`_valid_url` valida só formato**, não existência. Se o diff passa a confiar nele para mais coisa,
  aponte.
- **Título de vídeo vira nome de arquivo** — entrada não confiável. `/`, `\`, emoji, nome muito longo, e
  colisão com download anterior.

## Pilar 4 — Segurança e escopo

- **URL completa em log/arquivo persistente** — pode conter parâmetros de sessão.
- **Opção de yt-dlp que contorne restrição de acesso** (cookies de conta, bypass de idade ou de bloqueio
  regional)? Fora do escopo declarado no `CLAUDE.md`: a ferramenta baixa o que o usuário já pode acessar.
- **Caminho de saída montado com dado externo** sem `pathlib`/sanitização — travessia de diretório via
  título ou nome de playlist.
- **`subprocess`** novo: lista de argumentos (nunca `shell=True` com string montada).
- **Sobrescrita silenciosa** de arquivo já baixado.

## Pilar 5 — TDD (obrigatório neste repo)

- **Código de produção novo sem teste correspondente?** Viola a regra inegociável do `CLAUDE.md`.
  Reporte — é achado de review, não detalhe de estilo.
- **O teste tem cabeçalho SDD** explicando contrato e porquê, ou é um assert solto sem contexto?
- **O nome descreve comportamento** (`test_deve_<resultado>_quando_<condição>`) ou detalhe interno?
- **Mock escondendo o caminho real:** teste que só passa porque o yt-dlp foi mockado de um jeito que
  atalha a lógica sendo testada. Se a regra é pura, teste ela direto em vez de mockar em volta.
- **Teste que não falharia** se a implementação fosse removida — assert trivial, ou que reafirma o mock.
- **Mudança que quebra a testabilidade:** widget/`root` entrando no `DownloadManager`, ou lógica pura
  virando método de instância que depende de estado da UI.

## Pilar 6 — Manutenibilidade

- **Camada certa?** Lógica de download que foi parar na `YouTubeDownloaderApp`, ou construção de widget que foi parar no
  `DownloadManager`. É o deslize mais fácil de cometer aqui.
- **Hex literal** em vez das constantes de cor do topo do arquivo.
- **Helpers estáticos** (`_url_is_playlist`, `_is_playlist_result`, `_count_items`, `_valid_url`)
  continuam puros? São o que dá para testar sem janela — mantê-los sem efeito colateral tem valor real.
- Função nova faz uma coisa só; `download()` já orquestra bastante, não piore.

## Pilar 7 — Experiência de uso

- Erro chega ao usuário com **mensagem acionável**, ou só um código cru do yt-dlp?
- Progresso continua legível (a mudança não deixa a barra pulando ou parada)?
- O resumo final continua listando os itens que falharam?

## Formato da resposta

- Nada de micro-otimização irrelevante.
- Para cada problema: **arquivo e linha**, impacto, e o código refatorado. Ordene por severidade —
  quebra da fronteira backend↔UI e bug de concorrência primeiro.
- **Apenas revise e reporte. Não aplique as correções** sem ordem explícita.
