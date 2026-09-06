# Media Downloader

Aplicacao desktop com interface grafica (CustomTkinter) para download de video e audio de plataformas compativeis com o yt-dlp.

## Funcionalidades

- Download de videos em MP4 (melhor qualidade disponivel)
- Extracao de audio em MP3 (192 kbps)
- Opcao de adicionar ao MP3 a capa e os dados disponiveis na plataforma
- Busca guiada de artista, faixa, album, ano e capa quando um MP3 termina sem dados completos
- Aceita links HTTP/HTTPS e delega a compatibilidade de cada plataforma ao yt-dlp
- Deteccao automatica de playlists do YouTube
- Barra de progresso em tempo real
- Downloads organizados automaticamente em pastas separadas
- Interface grafica moderna e responsiva
- Lista de plataformas populares na tela inicial e acesso a lista oficial atualizada

## Plataformas compativeis

O aplicativo funciona com extratores do yt-dlp. A tela inicial mostra YouTube, Vimeo, TikTok,
Instagram, SoundCloud e Dailymotion como exemplos, mas a lista completa muda com frequencia. Consulte
a [lista oficial de plataformas suportadas pelo yt-dlp](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md)
para a referencia atual. A compatibilidade de um link especifico depende do site e da disponibilidade do conteudo.

## Requisitos

Do sistema:

- **Python 3.10+** (desenvolvido e testado no 3.14)
- **[FFmpeg](https://ffmpeg.org/)** — obrigatorio. Converte o audio para MP3 e junta video e audio no MP4;
  sem ele o download parece progredir e falha na conversao.
- **Tk** — o Tkinter acompanha o Python no Windows e no macOS, mas em varias distribuicoes Linux e um
  pacote separado (`tk` no Arch, `python3-tk` no Debian e Ubuntu). Sem ele a janela nao abre.
- **[Deno](https://deno.com/)** — opcional. Alguns extratores do yt-dlp usam um runtime JavaScript; sem ele
  o download normalmente funciona, apenas com um aviso de que certos formatos podem faltar.

Do Python, instaladas por `requirements.txt`:

| Pacote | Para que serve |
|---|---|
| `yt-dlp` | download e extracao dos metadados da origem |
| `customtkinter` | widgets da interface dark mode |
| `mutagen` | leitura e escrita de tags ID3 e capa no MP3 |
| `pillow` | redimensiona as capas mostradas na revisao — **o app nao abre sem ele** |

## Instalacao

Use um ambiente virtual. Em distribuicoes Linux recentes o pip recusa instalar no Python do sistema
(PEP 668, `externally-managed-environment`), e em algumas o pip nem vem junto — o `venv` resolve os dois
casos, porque traz o proprio pip.

**Linux e macOS**

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

**Windows**

```powershell
winget install "FFmpeg (Essentials Build)"
winget install DenoLand.Deno
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

## Como executar

```bash
.venv/bin/python src/app.py
```

## Testes

A logica de download, o diagnostico de metadata e a busca no catalogo ficam fora da camada grafica, entao a
suite roda sem abrir janela e sem acessar a rede:

```bash
.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest
```

## Problemas comuns

- **`HTTP Error 403: Forbidden`, ou erro de extracao que apareceu do nada** — quase sempre e o yt-dlp
  desatualizado. As plataformas mudam com frequencia e a versao instalada para de funcionar sem nada ter
  mudado no codigo: `.venv/bin/python -m pip install -U yt-dlp`.
- **O download chega a 100% e falha na conversao** — FFmpeg ausente do PATH. A mensagem do yt-dlp nao diz
  isso com todas as letras.
- **`error: externally-managed-environment` na instalacao** — o comando foi rodado fora do ambiente
  virtual; veja a secao de instalacao.
- **`ModuleNotFoundError: No module named 'tkinter'`** — falta o pacote de sistema do Tk.

## Estrutura do projeto

```
media-downloader/
├── src/
│   └── app.py
├── tests/
│   ├── test_url.py
│   ├── test_download_manager.py
│   ├── test_music_metadata.py
│   └── test_ui_controls.py
├── assets/
│   ├── media-downloader-icon.svg
│   ├── media-downloader-icon.png
│   └── media-downloader-icon.ico
├── Downloads/
│   ├── audios_unicos/
│   ├── videos_unicos/
│   ├── playlist_audio/
│   └── playlist_video/
├── pytest.ini
├── requirements.txt
├── requirements-dev.txt
├── .gitignore
├── CLAUDE.md
├── LICENSE.md
└── README.md
```

A pasta `Downloads/` e suas subpastas sao criadas automaticamente ao realizar o primeiro download.

## Capa e metadata em MP3

Selecione **Audio MP3** e marque **Adicionar capa e metadados** antes de iniciar. O app incorpora os dados
enviados pela plataforma.

Em video comum do YouTube a plataforma nao publica o campo de artista: o yt-dlp grava no MP3 o nome do
canal (por exemplo `AudioslaveVEVO`) e usa a miniatura do video como capa. Isso e um artista **provisorio**,
nao um arquivo sem artista — e o que a tela de revisao informa, nomeando o canal que virou tag.

Esses itens ficam separados das falhas de download. Para cada um, a tela mostra a previa do que ja esta
gravado no arquivo (capa e artista) e um botao de busca. Os resultados do catalogo aparecem com a capa de
cada release, priorizando album oficial de estudio; escolha um para importar titulo, artista, album, ano e
capa. Nada e gravado sem essa escolha — a leitura do titulo serve apenas para formular a busca. Em
playlists, cada item pendente fica listado individualmente.

## 🤖 AI Usage Disclosure

Transparency and integrity are important to this project. Artificial Intelligence (AI) tools were utilized
as part of the development and maintenance workflow, strictly serving as an assistant to handle repetitive,
time-consuming, and low-level tasks.

## Licenca

Distribuido sob a [Licenca MIT](LICENSE.md). As dependencias de terceiros mantem as licencas
delas — a nota no fim do arquivo lista quais sao.

## Aviso de uso

Este projeto e apenas para fins educacionais. O usuario e responsavel por respeitar os termos de uso das
plataformas e as leis de direitos autorais.
