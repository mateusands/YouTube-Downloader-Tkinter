---
name: iniciar-sessao
description: Inicializa a sessão de trabalho no YouTube Downloader — lê o CLAUDE.md, o estado do git e as pendências da última sessão, em modo somente leitura, e confirma o alinhamento de escopo antes de qualquer código. Use no começo de cada sessão.
---

# Inicialização de Sessão — YouTube Downloader

App desktop em **Python + CustomTkinter + yt-dlp**, com separação real entre backend e UI.
A fonte da verdade é **o código**.

Antes de qualquer ação, execute os passos de leitura abaixo:

1. **Leia o `CLAUDE.md` da raiz** — arquitetura em 3 camadas, o padrão fila + polling, e a seção
   **"Armadilhas ativas"** (FFmpeg obrigatório, yt-dlp que quebra sozinho, template de nome de arquivo).

2. **Leia a última sessão**, se houver: `.claude/sessions/` (arquivo mais recente).

3. **Levante o estado real do git** (somente leitura):
   ```bash
   git status --short && git branch --show-current && git log --oneline -10
   ```

4. **Leia a camada que a tarefa exige.** `src/app.py` tem ~705 linhas em três camadas bem separadas:

   | Camada | Onde | O que é |
   |---|---|---|
   | Dados | `DownloadSummary` | contadores e itens que falharam |
   | Backend | `DownloadManager`, `ReportingLogger` | download e yt-dlp — **não conhece a UI** |
   | UI | `YouTubeDownloaderApp` e os widgets | consome a fila por polling |

   Mudança de download → leia o backend. Mudança de tela → leia a `YouTubeDownloaderApp`. Raramente precisa das duas.

5. **MODO SOMENTE LEITURA:** é proibido alterar código, criar ou apagar arquivo nesta etapa.

## Gates que valem nesta sessão

Confirme explicitamente que estão ativos:

- **`DownloadManager` não conhece a UI.** Sem import de widget, sem `messagebox`, sem `root`. É o que
  torna a lógica testável sem abrir janela — não quebre por conveniência.
- **Comunicação thread → UI só pela `queue`** (`_emit` → `_poll` → `_handle`). Nada de `root.after(0, ...)`
  chamado de dentro da thread de download.
- **Um download por vez** — o guard de `self._thread.is_alive()` fica.
- **FFmpeg é dependência de sistema**, não do pip. Sem ele, MP3 e MP4 falham na conversão.
- **Escopo:** a ferramenta baixa o que o usuário já pode acessar. Nada de contornar restrição de acesso.
- **SDD + BDD + TDD obrigatório** — spec no topo do teste → `test_deve_<resultado>_quando_<condição>` →
  teste vermelho → código. Sem exceção, mesmo em mudança pequena. A suíte roda com `pytest`.
- **Verde não basta** — a suíte cobre a lógica, não o download. Validação real é baixar, pelo roteiro
  de `/rodar-local`.
- **Sem commit/push sem ordem explícita.**

## Antes de investigar bug de download

Se o sintoma é "parou de funcionar" sem mudança de código, **cheque a versão do yt-dlp primeiro**:

```bash
.venv/bin/pip install -U yt-dlp
```

O YouTube muda e a lib quebra sozinha. É a causa nº 1 neste tipo de app — não gaste a sessão depurando
código que está correto.

## O que responder ao usuário

Retorno **curto**: branch atual, se o working tree está limpo, qual camada vamos tocar, e se havia
pendência da sessão anterior. Confirme numa frase que os gates acima estão ativos.
