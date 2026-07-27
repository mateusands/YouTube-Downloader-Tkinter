# Media Downloader

Aplicacao desktop com interface grafica (CustomTkinter) para download de video e audio de plataformas compativeis com o yt-dlp.

## Funcionalidades

- Download de videos em MP4 (melhor qualidade disponivel)
- Extracao de audio em MP3 (192 kbps)
- Opcao de adicionar ao MP3 a capa e os dados disponiveis na plataforma
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

## Estrutura do projeto

```
yt/
├── src/
│   └── app.py
├── assets/
│   ├── media-downloader-icon.svg
│   ├── media-downloader-icon.png
│   └── media-downloader-icon.ico
├── Downloads/
│   ├── audios_unicos/
│   ├── videos_unicos/
│   ├── playlist_audio/
│   └── playlist_video/
├── .gitignore
├── README.md
└── requirements.txt
```

A pasta `Downloads/` e suas subpastas sao criadas automaticamente ao realizar o primeiro download.

## Screenshots

<img width="851" height="639" alt="image" src="https://github.com/user-attachments/assets/c0645424-a871-448f-ad57-84f73e9460bd" />

<img width="833" height="646" alt="image" src="https://github.com/user-attachments/assets/81a9c69b-bc59-4c6f-858b-40a77b74819d" />

<img width="862" height="666" alt="image" src="https://github.com/user-attachments/assets/be464037-fea4-466e-ae07-3a7639a8a8fe" />

---

Este projeto e apenas para fins educacionais. O usuario e responsavel por respeitar os termos de uso do YouTube e as leis de direitos autorais.
