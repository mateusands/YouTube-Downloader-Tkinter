"""Ponto de entrada do Media Downloader."""

import customtkinter as ctk

from media_downloader.window import MediaDownloaderApp

def main() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    root = ctk.CTk()
    app = MediaDownloaderApp(root)
    app.url_entry.focus()
    root.mainloop()


if __name__ == "__main__":
    main()
