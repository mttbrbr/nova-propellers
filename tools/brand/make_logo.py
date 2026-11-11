#!/usr/bin/env python3
"""Generate the NOVA brand assets from their geometric definition.

The mark is a dashed ring: three rounded annular segments (thickness 40 % of
the outer radius, 45° gaps, corner rounding 70 %), the paths traced by three
blade tips. The wordmark is N · mark · VA, with N, V and A outlined from a
typeface so the logo renders identically without any installed font.

Usage (development only; the font file is not part of the repository):

    python tools/brand/make_logo.py --font Outfit[wght].ttf --weight 700

Requires fonttools and uharfbuzz. Outfit is licensed under the SIL Open Font
License 1.1, which permits using its outlines in a logo.
"""
import argparse
import io
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEGMENTS, THICKNESS, GAP_DEG, ROUNDING = 3, 0.40, 45.0, 0.70
INK, TILE = '#F2F4F6', '#12151A'


def _fmt(value):
    text = f'{value:.2f}'.rstrip('0').rstrip('.')
    return '0' if text == '-0' else text


def sector(cx, cy, ro, ri, a1, a2, c):
    """Annular sector between radii ri..ro and angles a1..a2 with corner radius c (SVG y-down)."""
    def point(r, a):
        return f'{_fmt(cx + r * math.cos(a))} {_fmt(cy + r * math.sin(a))}'
    d_out, d_in = c / ro, c / ri
    large_out = 1 if (a2 - a1 - 2 * d_out) > math.pi else 0
    large_in = 1 if (a2 - a1 - 2 * d_in) > math.pi else 0
    return (f'M{point(ro, a1 + d_out)}'
            f'A{_fmt(ro)} {_fmt(ro)} 0 {large_out} 1 {point(ro, a2 - d_out)}'
            f'Q{point(ro, a2)} {point(ro - c, a2)}'
            f'L{point(ri + c, a2)}'
            f'Q{point(ri, a2)} {point(ri, a2 - d_in)}'
            f'A{_fmt(ri)} {_fmt(ri)} 0 {large_in} 0 {point(ri, a1 + d_in)}'
            f'Q{point(ri, a1)} {point(ri + c, a1)}'
            f'L{point(ro - c, a1)}'
            f'Q{point(ro, a1)} {point(ro, a1 + d_out)}Z')


def mark_path(cx, cy, ro, segments=SEGMENTS, thickness=THICKNESS, gap=GAP_DEG, rounding=ROUNDING):
    ri = ro * (1 - thickness)
    step = 360 / segments
    span = step - gap
    parts = []
    for k in range(segments):
        centre = -90 + k * step
        a1, a2 = math.radians(centre - span / 2), math.radians(centre + span / 2)
        cmax = min((ro - ri) / 2, ri * (a2 - a1) / 2 * 0.9)
        parts.append(sector(cx, cy, ro, ri, a1, a2, rounding * cmax))
    return ''.join(parts)


def wordmark(font_path, weight, tracking=0.04):
    import uharfbuzz as hb
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    font = TTFont(font_path)
    if 'fvar' in font:
        font = instancer.instantiateVariableFont(font, {'wght': weight})
    buffer = io.BytesIO()
    font.save(buffer)
    data = buffer.getvalue()
    upem = font['head'].unitsPerEm
    face = hb.Face(hb.Blob(data))
    shaper = hb.Font(face)
    run = hb.Buffer()
    run.add_str('NOVA')
    run.guess_segment_properties()
    hb.shape(shaper, run, {'kern': True, 'liga': False})
    order = font.getGlyphOrder()
    glyph_set = font.getGlyphSet()
    glyf = font['glyf'] if 'glyf' in font else None
    names = [order[info.codepoint] for info in run.glyph_infos]
    # Vertical frame: cap/overshoot top to baseline (font units, y up).
    bounds = {name: glyf[name] for name in names} if glyf else {}
    top = max(b.yMax for b in bounds.values())
    bottom = min(b.yMin for b in bounds.values())
    paths, x, extents = [], 0.0, []
    for index, (name, pos) in enumerate(zip(names, run.glyph_positions)):
        g = bounds[name]
        gx = x + pos.x_offset
        if index == 1:  # the O becomes the dashed ring
            cx = gx + (g.xMin + g.xMax) / 2
            cy = top - (g.yMin + g.yMax) / 2
            radius = (g.yMax - g.yMin) / 2
            paths.append(mark_path(cx, cy, radius))
            extents += [cx - radius, cx + radius]
        else:
            pen = SVGPathPen(glyph_set, ntos=_fmt)
            glyph_set[name].draw(TransformPen(pen, (1, 0, 0, -1, gx, top)))
            paths.append(pen.getCommands())
            extents += [gx + g.xMin, gx + g.xMax]
        x += pos.x_advance + (tracking * upem if index < len(names) - 1 else 0)
    left, right = min(extents), max(extents)
    height = top - bottom
    view = f'{_fmt(left)} 0 {_fmt(right - left)} {_fmt(height)}'
    return {'viewBox': view, 'paths': paths, 'width': right - left, 'height': height}


def svg(view_box, body, title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_box}" role="img" aria-label="{title}">'
            f'<title>{title}</title>{body}</svg>\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--font', required=True, help='TrueType font for the N, V and A letterforms')
    parser.add_argument('--weight', type=float, default=700)
    args = parser.parse_args()

    brand = ROOT / 'docs/media/brand'
    brand.mkdir(parents=True, exist_ok=True)
    mark = mark_path(32, 32, 27)
    word = wordmark(args.font, args.weight)
    word_body = ''.join(f'<path d="{d}"/>' for d in word['paths'])
    tile = 1024
    icon_mark = mark_path(tile / 2, tile / 2, tile * 0.31)
    icon_body = (f'<rect width="{tile}" height="{tile}" rx="{_fmt(tile * 0.23)}" fill="{TILE}"/>'
                 f'<path d="{icon_mark}" fill="{INK}"/>')

    (brand / 'nova-mark.svg').write_text(svg('0 0 64 64', f'<path d="{mark}" fill="{INK}"/>', 'NOVA mark'))
    (brand / 'nova-wordmark.svg').write_text(svg(word['viewBox'], f'<g fill="{INK}">{word_body}</g>', 'NOVA'))
    (brand / 'nova-icon.svg').write_text(svg(f'0 0 {tile} {tile}', icon_body, 'NOVA'))
    (ROOT / 'frontend/public').mkdir(exist_ok=True)
    (ROOT / 'frontend/public/favicon.svg').write_text(svg(f'0 0 {tile} {tile}', icon_body, 'NOVA'))
    module = ('// Generated by tools/brand/make_logo.py — do not edit by hand.\n'
              f'export const markPath = {json.dumps(mark)};\n'
              f'export const wordmark = {json.dumps({"viewBox": word["viewBox"], "paths": word["paths"], "aspect": round(word["width"] / word["height"], 4)})};\n')
    (ROOT / 'frontend/src/shell/brand.js').write_text(module)
    print('Wrote mark, wordmark, icon, favicon and frontend/src/shell/brand.js')


if __name__ == '__main__':
    main()
