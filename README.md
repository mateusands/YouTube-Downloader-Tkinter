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

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/) — necessario para conversao de audio/video
- [Deno](https://deno.com/) — runtime JavaScript usado por alguns extratores do yt-dlp, incluindo o YouTube

Para a opcao de capa e metadata, o aplicativo usa `mutagen`, instalado automaticamente por
`requirements.txt`. Quando a origem nao oferecer artista ou capa, o app permite pesquisar no catalogo e
escolher o resultado correto. A sugestao baseada no titulo do video nunca e gravada automaticamente como
metadata.

### Instalacao dos requisitos (Windows)

```bash
winget install "FFmpeg (Essentials Build)"
winget install DenoLand.Deno
```

### Instalacao das dependencias Python

```bash
pip install -r requirements.txt
```

## Como executar

```bash
python src/app.py
```

## Testes

A logica de download, o diagnostico de metadata e a busca no catalogo ficam fora da camada grafica, entao a
suite roda sem abrir janela e sem acessar a rede:

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

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

Este projeto e apenas para fins educacionais. O usuario e responsavel por respeitar os termos de uso das plataformas e as leis de direitos autorais.
