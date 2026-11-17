"""Genera il logo di MetiX (scelto il 14/11/2026): simbolo «layer-first» e scritta MetiX.

Simbolo: tre layer che si assottigliano verso l'alto e sopra una cella di Voronoi arancione
(prima i layer, poi il core). Scritta: Geist ExtraBold, «Meti» nel colore del testo e la X
arancione, un po' più alta delle altre lettere e spostata a sinistra fino a coprire appena la i.
Le lettere sono convertite in tracciati, così il logo non dipende dal font installato.

    python tools/logo.py Geist-800.ttf          (font da fonts.google.com, licenza OFL)

Scrive in _static/ (sito) e in _latex/ (PDF, tramite rsvg-convert):
  marchio.svg            simbolo + scritta, testo in currentColor (barra del sito, inline)
  marchio-chiaro.svg     simbolo + scritta per fondi chiari (testo nero)
  marchio-scuro.svg      simbolo + scritta per fondi scuri (testo bianco)
  simbolo.svg            solo simbolo, testo in currentColor
  favicon.svg            simbolo su un quadrato nero arrotondato (icona della scheda)
  _latex/marchio-*.pdf   le stesse versioni per il PDF
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

TRACKING = -0.045      # spaziatura tra le lettere, in em (come il titolo della home)
X_SCALA = 1.12         # la X è più alta delle altre lettere: sporge sopra la linea delle maiuscole
X_RIENTRO = 0.075      # di quanto (in em) la X entra verso la i


def simbolo(colore):
    """Il simbolo in un riquadro 32x32: cella arancione sopra tre layer."""
    return (
        f'<path d="M10 13.5 L13 6.5 L20 5 L25 10 L22.5 15 Z" fill="{ARANCIO}" stroke="{ARANCIO}" '
        f'stroke-width="1.4" stroke-linejoin="round"/>'
        f'<rect x="4" y="17" width="24" height="3.4" rx="1.7" fill="{colore}"/>'
        f'<rect x="4" y="22" width="24" height="2.6" rx="1.3" fill="{colore}" opacity=".75"/>'
        f'<rect x="4" y="26.2" width="24" height="1.8" rx=".9" fill="{colore}" opacity=".5"/>'
    )


def scritta(font):
    """Tracciati di «Meti» e della X, in unità del font con la linea di base a y=0 e y verso l'alto."""
    upm = font["head"].unitsPerEm
    cmap = font.getBestCmap()
    glifi = font.getGlyphSet()
    hmtx = font["hmtx"]
    x = 0.0
    meti = []
    for c in "Meti":
        nome = cmap[ord(c)]
        pen = SVGPathPen(glifi)
        glifi[nome].draw(TransformPen(pen, (1, 0, 0, 1, x, 0)))
        meti.append(pen.getCommands())
        x += hmtx[nome][0] + TRACKING * upm
    nome = cmap[ord("X")]
    x -= X_RIENTRO * upm
    pen = SVGPathPen(glifi)
    glifi[nome].draw(TransformPen(pen, (X_SCALA, 0, 0, X_SCALA, x, 0)))
    larghezza = x + hmtx[nome][0] * X_SCALA
    alto = font["OS/2"].sCapHeight * X_SCALA
    return " ".join(meti), pen.getCommands(), larghezza, alto, upm


def marchio(font, colore):
    meti, xx, larg, alto, upm = scritta(font)
    # il simbolo (disegnato tra y=5 e y=28, x tra 4 e 28) è alto quanto la X e poggia sulla linea
    # di base; la scritta segue a un passo pari a 0,2 della sua altezza
    h = alto
    s = h / 23.0
    gap = 0.2 * h
    w = 24 * s + gap + larg
    tx = 24 * s + gap
    corpo = (
        f'<g transform="translate({-4 * s:.2f},{-5 * s:.2f}) scale({s:.4f})">{simbolo(colore)}</g>'
        f'<g transform="translate({tx:.1f},{alto:.1f}) scale(1,-1)">'
        f'<path d="{meti}" fill="{colore}"/><path d="{xx}" fill="{ARANCIO}"/></g>'
    )
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}" '
            f'role="img" aria-label="MetiX">{corpo}</svg>\n')


def main():
    font = TTFont(sys.argv[1])
    docs = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    static = os.path.join(docs, "_static")
    latex = os.path.join(docs, "_latex")
    file = {
        "marchio.svg": marchio(font, "currentColor"),
        "marchio-chiaro.svg": marchio(font, NERO),
        "marchio-scuro.svg": marchio(font, BIANCO),
        "simbolo.svg": ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
                        f'{simbolo("currentColor")}</svg>\n'),
        "favicon.svg": ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
                        f'<rect width="32" height="32" rx="8" fill="{NERO}"/>'
                        f'<g transform="translate(2.4 1.2) scale(.85)">{simbolo(BIANCO)}</g></svg>\n'),
    }
    for nome, testo in file.items():
        with open(os.path.join(static, nome), "w", encoding="utf-8") as f:
            f.write(testo)
    # PDF: inchiostro del manuale per le testatine, bianco per la copertina
    for nome, colore in (("marchio-inchiostro", "#1F2933"), ("marchio-bianco", "#FFFFFF")):
        svg = os.path.join(latex, nome + ".svg")
        with open(svg, "w", encoding="utf-8") as f:
            f.write(marchio(font, colore))
        subprocess.run(["rsvg-convert", "-f", "pdf", "-o", os.path.join(latex, nome + ".pdf"), svg],
                       check=True)
        os.remove(svg)


if __name__ == "__main__":
    main()
