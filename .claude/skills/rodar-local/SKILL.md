---
name: rodar-local
description: Rodar o YouTube Downloader localmente (venv, yt-dlp, FFmpeg do sistema) e as pegadinhas do ambiente, mais o roteiro de teste manual. Use ao rodar, testar manualmente ou debugar o ambiente.
---

# Rodar o YouTube Downloader localmente

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python src/app.py
```

O `.venv/` já está no `.gitignore`.

## Pré-requisitos do sistema (não vêm do pip)

| Requisito | Por quê | Como instalar |
|---|---|---|
| **Tk** | `tkinter` é stdlib mas depende da lib Tk do SO | `sudo pacman -S tk` · `sudo apt install python3-tk` |
| **FFmpeg** | **obrigatório** — MP3 e a junção vídeo+áudio do MP4 | `sudo pacman -S ffmpeg` · `sudo apt install ffmpeg` |

Verificar os dois:

```bash
python -c "import tkinter; print('Tk', tkinter.TkVersion)"
ffmpeg -version | head -1
```

## Pegadinhas

- **Download chega a 100% e falha na conversão** → **FFmpeg ausente**. A mensagem do yt-dlp não diz
  "instale o ffmpeg", então esse é sempre o primeiro suspeito. Vale para MP3 (postprocessor) e para MP4
  (merge de vídeo+áudio baixados separados).

- **"Um item falhou — continuando com os demais…"** na status bar → comportamento **intencional**:
  `ignoreerrors: True` faz a playlist seguir. Os itens que falharam aparecem no resumo do fim.

- **Erro de extração em vídeo que funcionava** → yt-dlp desatualizado. O YouTube muda e a lib quebra sem
  o código ter mudado:
  ```bash
  .venv/bin/pip install -U yt-dlp
  ```
  É a causa nº 1 de bug reportado neste tipo de app. Cheque **antes** de investigar o código.

- **Falha só em ambiente com rede restrita** → `"remote_components": ["ejs:github"]` em `_build_opts` faz
  o yt-dlp buscar componentes remotos, além do próprio YouTube.

- **Downloads não aparecem onde esperado** → `BASE_DOWNLOADS_DIR` é relativo ao **arquivo**
  (`src/app.py` → `../Downloads`), não ao diretório de onde você rodou. As subpastas são
  `audios_unicos`, `videos_unicos`, `playlist_audio`, `playlist_video`.

- **Botão "Abrir pasta" não faz nada no Linux** → usa `xdg-open`; sem `xdg-utils` instalado, falha.

- **Progresso trava em um número** → `concurrent_fragment_downloads: 1` deixa o percentual legível, mas
  fragmento grande demora. Não é congelamento da UI: se a janela responde, está baixando.

- **A UI parece diferente do Windows** → `FONT_FAMILY = "Segoe UI"` não existe no Linux; fallback silencioso.

- **Sem servidor gráfico não roda** (SSH, container): `no display name and no $DISPLAY`.

---

## Roteiro de teste manual

A suíte (`pytest`) cobre a **lógica**; ela não baixa nada. **Este roteiro cobre o resto** — e o resto é
onde os bugs de verdade aparecem. Use vídeos curtos e uma playlist de 2–3 itens para não esperar demais.

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest        # antes de abrir o app: a lógica está sã?
```

### Caminho feliz
- **Vídeo único, MP4** → arquivo em `Downloads/videos_unicos/`, abre e tem áudio (prova que o merge rodou)
- **Vídeo único, MP3** → arquivo em `Downloads/audios_unicos/`, toca (prova que o FFmpeg rodou)
- **Playlist, MP4** → subpasta com o nome da playlist em `Downloads/playlist_video/`, todos os itens
- **Playlist, MP3** → idem em `Downloads/playlist_audio/`

### Detecção de modo
- Link com `?list=...` → detecta playlist
- Link de vídeo **dentro** de playlist → confirme qual comportamento acontece (`noplaylist` depende do
  modo detectado); é o caso ambíguo do app
- Playlist com **um item só** → `_is_playlist_result` deve cair para modo único

### Erros
- **URL inválida** (`abc`) → borda vermelha + dica, que some depois de 3 s
- **Vídeo privado/removido** → aparece em `failed_items` no resumo, sem derrubar o app
- **Playlist com um item quebrado** → os outros baixam; o resumo lista o que falhou
- **Sem internet** → erro tratado, não stack trace no terminal

### Interface
- **Dois downloads ao mesmo tempo** → o segundo é bloqueado com aviso
- **Barra e percentual** avançam durante o download
- **Controles voltam a ficar habilitados** ao fim — inclusive **depois de erro** (bug clássico: botão
  preso em "ocupado")
- **"Abrir pasta"** abre o gerenciador de arquivos
- **Colar URL** pelo botão de colar funciona
- **Fechar a janela durante o download** não deixa processo pendurado (a thread é `daemon=True`)

---

## Empacotar (opcional)

```bash
pyinstaller --onefile --windowed src/app.py
```

⚠️ O FFmpeg **não** é embutido por isso — continua sendo dependência do sistema. Distribuir de verdade
exigiria empacotar o binário à parte. Não é parte do projeto hoje.
