"""Media Downloader — aplicativo de download de video e audio.

O pacote segue as tres camadas do projeto: `models` e `config` sao dados,
`downloader` e `metadata` sao o backend que nao conhece a UI, e `widgets` e
`window` sao a interface. A fronteira entre backend e UI e a fila em
`downloader`; nada da interface e importado do lado de backend.
"""
