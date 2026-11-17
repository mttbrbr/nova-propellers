"""Generates the NOVA logo: symbol and the word «NOVA».

Symbol: the three rounded ring segments of NOVA's mark (docs/media/brand/nova-mark.svg), in orange.
Wordmark: Geist ExtraBold (800) in the text colour. Letters are converted to outlines, so the logo
does not depend on the installed font.

    python tools/logo.py tools/Geist-800.ttf     (font from the official vercel/geist-font repository, OFL)

Writes to _static/ (site) and _latex/ (PDF, through rsvg-convert):
  marchio.svg            symbol + wordmark, text in currentColor (inline)
  marchio-chiaro.svg     symbol + wordmark for light backgrounds (black text)
  marchio-scuro.svg      symbol + wordmark for dark backgrounds (white text)
  simbolo.svg            symbol only
  favicon.svg            symbol on a rounded black square (tab icon)
  _latex/marchio-*.pdf   PDF versions (white for the cover, ink for the running heads)
"""
import os
import subprocess
import sys

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ARANCIO = "#F76B15"
NERO = "#09090B"
BIANCO = "#FAFAFA"

TRACKING = -0.01       # spaziatura tra le lettere, in em
NOME = "NOVA"

# three ring segments (64x64 box, drawing between x 5..59 and y 5..57)
SIMBOLO_D = (
    "M18.71 8.5A27 27 0 0 1 45.29 8.5Q48.44 10.58 46.14 13.58L44.16 16.15Q41.86 19.15 38.62 17.22"
    "A16.2 16.2 0 0 0 25.38 17.22Q22.14 19.15 19.84 16.15L17.86 13.58Q15.56 10.58 18.71 8.5Z"
    "M59 32.25A27 27 0 0 1 45.71 55.26Q42.33 56.94 40.89 53.45L39.65 50.46Q38.2 46.97 41.49 45.13"
    "A16.2 16.2 0 0 0 48.12 33.66Q48.06 29.89 51.81 29.39L55.02 28.97Q58.77 28.48 59 32.25Z"
    "M18.29 55.26A27 27 0 0 1 5 32.25Q5.23 28.48 8.98 28.97L12.19 29.39Q15.94 29.89 15.88 33.66"
    "A16.2 16.2 0 0 0 22.51 45.13Q25.8 46.97 24.35 50.46L23.11 53.45Q21.67 56.94 18.29 55.26Z"
)
SIMBOLO_X0, SIMBOLO_Y0, SIMBOLO_LATO = 5.0, 5.0, 54.0


def simbolo():
    """The symbol in the 64x64 box."""
    return f'<path d="{SIMBOLO_D}" fill="{ARANCIO}"/>'


def scritta(font):
    """Outline of «NOVA» in font units, baseline at y=0, y pointing up."""
    upm = font["head"].unitsPerEm
    cmap = font.getBestCmap()
    glifi = font.getGlyphSet()
    hmtx = font["hmtx"]
    x = 0.0
    parti = []
    for c in NOME:
        nome = cmap[ord(c)]
        pen = SVGPathPen(glifi)
        glifi[nome].draw(TransformPen(pen, (1, 0, 0, 1, x, 0)))
        parti.append(pen.getCommands())
        x += hmtx[nome][0] + TRACKING * upm
    larghezza = x - TRACKING * upm
    alto = font["OS/2"].sCapHeight
    return " ".join(parti), larghezza, alto


def marchio(font, colore):
    testo, larg, alto = scritta(font)
    # the symbol is as tall as the capitals and sits on the baseline; the wordmark follows at a
    # gap of 0.28 of its height
    h = alto
    s = h / SIMBOLO_LATO
    gap = 0.28 * h
    w = SIMBOLO_LATO * s + gap + larg
    tx = SIMBOLO_LATO * s + gap
    corpo = (
        f'<g transform="translate({-SIMBOLO_X0 * s:.2f},{-SIMBOLO_Y0 * s:.2f}) scale({s:.4f})">'
        f'{simbolo()}</g>'
        f'<g transform="translate({tx:.1f},{alto:.1f}) scale(1,-1)">'
        f'<path d="{testo}" fill="{colore}"/></g>'
    )
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}" '
            f'role="img" aria-label="{NOME}">{corpo}</svg>\n')


def main():
    font = TTFont(sys.argv[1])
    docs = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    static = os.path.join(docs, "_static")
    latex = os.path.join(docs, "_latex")
    riquadro = f'viewBox="{SIMBOLO_X0 - 2} {SIMBOLO_Y0 - 2} {SIMBOLO_LATO + 4} {SIMBOLO_LATO + 4}"'
    file = {
        "marchio.svg": marchio(font, "currentColor"),
        "marchio-chiaro.svg": marchio(font, NERO),
        "marchio-scuro.svg": marchio(font, BIANCO),
        "simbolo.svg": f'<svg xmlns="http://www.w3.org/2000/svg" {riquadro}>{simbolo()}</svg>\n',
        "favicon.svg": ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
                        f'<rect width="64" height="64" rx="14" fill="{NERO}"/>'
                        f'<g transform="translate(9.6 9.6) scale(.7)">{simbolo()}</g></svg>\n'),
    }
    for nome, testo in file.items():
        with open(os.path.join(static, nome), "w", encoding="utf-8") as f:
            f.write(testo)
    # PDF: ink for the running heads, white for the cover
    for nome, colore in (("marchio-inchiostro", "#1F2933"), ("marchio-bianco", "#FFFFFF")):
        svg = os.path.join(latex, nome + ".svg")
        with open(svg, "w", encoding="utf-8") as f:
            f.write(marchio(font, colore))
        subprocess.run(["rsvg-convert", "-f", "pdf", "-o", os.path.join(latex, nome + ".pdf"), svg],
                       check=True)
        os.remove(svg)


if __name__ == "__main__":
    main()
