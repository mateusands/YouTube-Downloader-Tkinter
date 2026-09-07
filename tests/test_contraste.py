"""
SDD — Especificação: contraste mínimo da paleta

CONTRATO
  Todo par (texto, superfície) que a interface realmente usa alcança a razão de
  contraste 4.5:1 da WCAG AA para texto normal.

POR QUE EXISTE
  A paleta foi crescendo por acréscimo, e contraste se julga com número, não com
  olho. Medidos, três pares reprovavam: `CLR_MUTED` sobre `BG_HOVER` (4,05:1,
  os chips de plataforma), `CLR_MUTED` sobre `BG_INPUT` (4,27:1, a linha de
  álbum e a de motivos da revisão) e `CLR_ERROR` sobre `BG_INPUT` (4,02:1) — o
  aviso de arquivo não localizado, justamente o texto que mais precisa ser lido.

REGRA DE NEGÓCIO
  - O piso é 4.5:1 para texto normal; o par é medido contra a superfície MAIS
    ESCURA em que aquele texto aparece.
  - Borda decorativa não é texto e não entra nesta conta: `CLR_BORDER` separa
    superfícies por luminância, de propósito.
  - Escurecer o fundo conta tanto quanto clarear o texto; o que não vale é
    clarear só um dos dois e piorar o par.
"""

from media_downloader import theme

PISO_TEXTO_NORMAL = 4.5


def _luminancia(cor: str) -> float:
    canais = [int(cor[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    canais = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canais]
    return 0.2126 * canais[0] + 0.7152 * canais[1] + 0.0722 * canais[2]


def contraste(frente: str, fundo: str) -> float:
    clara, escura = sorted((_luminancia(frente), _luminancia(fundo)), reverse=True)
    return (clara + 0.05) / (escura + 0.05)


PARES_EM_USO = [
    ("titulo e rotulo", theme.CLR_TEXT, theme.BG_CARD),
    ("texto do botao primario", theme.CLR_TEXT, theme.CLR_ACCENT),
    ("dica e legenda", theme.CLR_MUTED, theme.BG_CARD),
    ("linha de album do candidato", theme.CLR_MUTED, theme.BG_INPUT),
    ("chip de plataforma", theme.CLR_MUTED, theme.BG_HOVER),
    ("link da lista do yt-dlp", theme.CLR_ACCENT_LIGHT, theme.BG_CARD),
    ("aviso de arquivo nao localizado", theme.CLR_ERROR, theme.BG_INPUT),
    ("progresso concluido", theme.CLR_GREEN, theme.BG_CARD),
]


class TestContrasteDaPaleta:
    def test_deve_alcancar_o_piso_aa_em_todo_par_que_a_interface_usa(self):
        reprovados = {
            nome: round(contraste(frente, fundo), 2)
            for nome, frente, fundo in PARES_EM_USO
            if contraste(frente, fundo) < PISO_TEXTO_NORMAL
        }

        assert reprovados == {}, f"pares abaixo de {PISO_TEXTO_NORMAL}:1 — {reprovados}"

    def test_deve_manter_a_escada_de_luminancia_das_superficies(self):
        # No escuro a profundidade vem da luminância, não de sombra: cada
        # superfície empilhada precisa ser mais clara que a de baixo.
        escada = [theme.BG_DARK, theme.BG_CARD, theme.BG_INPUT, theme.BG_HOVER]

        assert [_luminancia(c) for c in escada] == sorted(_luminancia(c) for c in escada)
