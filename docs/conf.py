# Sphinx configuration of the NOVA documentation: HTML site (Shibuya theme) and PDF manual
# (XeLaTeX with the NOVA style in _latex/). Build with `make -C docs html` and `make -C docs pdf`.
import os
import sys

sys.path.insert(0, os.path.abspath("_ext"))

project = "NOVA"
author = "NOVA"
copyright = "2026, NOVA"
language = "en"

extensions = [
    "myst_parser",
    "sphinxcontrib.mermaid",
    "nova_docs",
]

# The Markdown files already in docs/ (upper-case project documents, media, verification) are not
# part of this site: Sphinx only reads index.md and the guide/ and technical/ folders.
exclude_patterns = ["_build", "esempio documentazione", "media", "verification", "tools",
                    "_latex", "[A-Z]*.md", "**/.venv*"]
source_suffix = {".md": "markdown"}
templates_path = ["_templates"]

myst_enable_extensions = ["dollarmath", "amsmath", "colon_fence", "deflist", "attrs_inline"]
myst_fence_as_directive = ["mermaid"]
myst_heading_anchors = 3

numfig = True
math_numfig = True
numfig_secnum_depth = 1
numfig_format = {"figure": "Figure %s", "table": "Table %s", "code-block": "Listing %s",
                 "section": "%s", "algorithm": "Algorithm %s"}

# ---------------------------------------------------------------------------- HTML
html_theme = "shibuya"
html_title = "NOVA"
html_static_path = ["_static"]
html_css_files = ["nova.css"]
html_js_files = ["nova.js"]
html_theme_options = {
    "accent_color": "orange",
    "color_mode": "auto",
    # left index: chapters open onto their sections
    "toctree_titles_only": False,
    "toctree_maxdepth": 3,
}
html_favicon = "_static/favicon.svg"
# The manual PDF, if already built (make pdf), can be downloaded from the top bar.
_pdf = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_build", "latex",
                    "nova-technical-manual.pdf")
html_extra_path = [_pdf] if os.path.exists(_pdf) else []
html_context = {"nova_pdf": bool(html_extra_path)}
# Mermaid diagrams: neutral theme on light, dark on the dark theme, site font.
mermaid_light_theme = "neutral"
mermaid_dark_theme = "dark"
mermaid_init_config = {"startOnLoad": False, "fontFamily": "Geist, Inter, sans-serif"}
html_last_updated_fmt = "%Y-%m-%d"
mathjax3_config = {"tex": {"macros": {"vect": [r"\boldsymbol{#1}", 1], "R": r"\mathbb{R}"}}}

# ---------------------------------------------------------------------------- PDF
latex_engine = "xelatex"
latex_documents = [
    ("technical/pdf", "nova-technical-manual.tex", "NOVA — technical manual", author, "manual"),
]
latex_additional_files = [
    "_latex/preambolo.tex",
    "_latex/colori.tex",
    "_latex/copertina.tex",
    "_latex/marchio-bianco.pdf",
    "_latex/marchio-inchiostro.pdf",
]
latex_table_style = ["booktabs"]
latex_show_urls = "no"
latex_domain_indices = False


latex_elements = {
    "papersize": "a4paper",
    "pointsize": "11pt",
    "extraclassoptions": "openany",
    "geometry": r"\usepackage[a4paper,inner=28mm,outer=26mm,top=28mm,bottom=30mm,"
                r"headheight=14pt]{geometry}",
    "fontenc": r"\usepackage{fontspec}",
    "amsmath": r"\usepackage{amsmath}",
    "polyglossia": "",
    "babel": r"\usepackage[english]{babel}",
    "fontpkg": r"""
\usepackage{unicode-math}
\setmainfont{texgyrepagella}[Extension=.otf,UprightFont=*-regular,BoldFont=*-bold,
  ItalicFont=*-italic,BoldItalicFont=*-bolditalic]
\setmathfont{texgyrepagella-math.otf}
\setmonofont{lmmono10-regular.otf}[BoldFont=lmmonolt10-bold.otf,ItalicFont=lmmono10-italic.otf,
  HyphenChar=None]
""",
    "fncychap": "",
    "sphinxsetup": "TitleColor={HTML}{18181B}, InnerLinkColor={HTML}{18181B}, "
                   "OuterLinkColor={HTML}{18181B}, VerbatimColor={HTML}{F7F7F8}, "
                   "VerbatimBorderColor={HTML}{E4E4E7}",
    "preamble": r"\input{preambolo.tex}",
    "maketitle": r"\input{copertina.tex}",
    "printindex": "",
}
