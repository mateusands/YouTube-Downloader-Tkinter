---
name: finalizar-sessao
description: Encerra a sessão de trabalho no YouTube Downloader — gera o relatório da sessão em .claude/sessions/ e atualiza o CLAUDE.md se algo que ele afirma mudou. Use ao final de cada sessão.
---

# Encerramento de Sessão — YouTube Downloader

O objetivo agora **não é codar**, e sim consolidar o que a sessão mudou.

## 1. Relatório da sessão

- Crie `.claude/sessions/YYYY-MM-DD.md` (data de hoje). Se já existir arquivo com a data de hoje,
  **acrescente** uma seção em vez de sobrescrever.
- Conteúdo exigido:
  - **O que foi feito** — em qual camada (dados / `DownloadManager` / `YouTubeDownloaderApp`).
  - **Decisões técnicas não-óbvias** — e o porquê.
  - **Validação manual** — o que você **de fato baixou**: vídeo único ou playlist? MP3 ou MP4? Testar só
    um MP4 de vídeo único não valida o caminho do FFmpeg de áudio nem o de playlist.
  - **Versão do yt-dlp** usada no teste. Ela envelhece rápido e explica bug futuro.
  - **Pendências** — explícitas o bastante para retomar sem contexto.
  - **Estado do git** — branch, se ficou coisa não commitada.

> `.claude/sessions/` é **gitignorado** — caderno de bordo local, não documentação do repo.

## 2. Atualização do CLAUDE.md

Avalie se a sessão mudou algo que o `CLAUDE.md` afirma. Gatilhos:

- **Estrutura de pastas de download** — a tabela de destinos (`audios_unicos`, `videos_unicos`,
  `playlist_audio`, `playlist_video`) está documentada.
- **Opções do yt-dlp** — `ignoreerrors`, seletor de formato, `remote_components` estão descritos com o
  porquê de cada um.
- **Mudança na fronteira das camadas** ou no mecanismo de comunicação (fila + polling).
- **Dependência nova** — especialmente se for binário de sistema, como o FFmpeg (a seção de stack separa
  pip de sistema de propósito).
- **Armadilha resolvida** — ex.: se você adicionou checagem de FFmpeg no boot, o item 1 de "Armadilhas
  ativas" muda de natureza. Atualize em vez de deixar descrevendo um problema já tratado.
- **Armadilha nova descoberta** — acrescente; é o conteúdo mais valioso do documento.

## 3. Validação final

**Primeiro a suíte** — e relate o resultado real, sem maquiar:

```bash
pytest
```

Se você escreveu código de produção nesta sessão, houve teste vermelho antes? Se não, a regra do
`CLAUDE.md` foi quebrada — registre isso no relatório em vez de esconder.

**Depois o app**, porque verde não cobre download:

```bash
.venv/bin/python src/app.py
```

Use o roteiro de `/rodar-local`. Para qualquer mudança no caminho de download, confirme no mínimo:

1. **Um MP4** — o arquivo abre **e tem áudio** (prova que o merge do FFmpeg rodou)
2. **Um MP3** — o arquivo toca (prova o postprocessor)
3. **Uma playlist curta** — cai na subpasta certa, com todos os itens
4. **Um erro** (URL inválida ou vídeo removido) — tratado, e os controles **voltam a ficar habilitados**

**Relate o que de fato testou.** Se só baixou um MP4, diga isso — não afirme que o caminho de áudio está
validado.

## O que responder ao usuário

1. Caminho do relatório gerado.
2. Se o `CLAUDE.md` foi atualizado, e o que mudou (ou que nada foi necessário).
3. O que foi baixado no teste e o que ficou de fora.
4. **Não commite nem faça push** — só quando o dono mandar.
