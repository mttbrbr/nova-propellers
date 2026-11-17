"""Sphinx extension for the NOVA documentation.

Markup shared by the HTML site and the PDF manual, so each concept is written once:

- ``{tag}`ours``` and the other origin/status labels (ours, lit, mixed, suspended, experimental, option);
- ``{par}`Title``` run-in paragraph heading;
- ``{num}`2046342```, ``{si}`8.6 s```, ``{ang}`30``` numbers in SI style (siunitx in the PDF);
- ``measure``, ``note``, ``warning``, ``origin``, ``implementation`` boxes (tcolorbox in the PDF);
- ``algorithm``: numbered pseudocode, one line per step, indentation for nesting (``algorithm`` +
  ``algorithmic`` in the PDF, a numbered card on the site; ``{numref}`` works in both).
"""

import html
import re

from docutils import nodes
from docutils.parsers.rst import directives
from sphinx.util.docutils import SphinxDirective, SphinxRole

TAGS = {
    "ours": ("OURS", "Ours", "own construction"),
    "lit": ("LITERATURE", "Lit", "published method, reimplemented from the text"),
    "mixed": ("LIT. + OURS", "Mixed", "published method with our own variations"),
    "suspended": ("SUSPENDED", "Suspended", "outside the pipeline"),
    "experimental": ("EXPERIMENTAL", "Experimental", "prototype or option not yet validated"),
    "option": ("OPTION", "Option", "off by default"),
}
BOX_TITLES = {"measure": "Measure", "warning": "Warning", "origin": "Origin of the method",
              "note": "", "implementation": "Implementation"}
THIN = " "   # narrow no-break space, as siunitx groups digits


# --------------------------------------------------------------------------- nodes

class nova_tag(nodes.Inline, nodes.TextElement):
    pass


class nova_par(nodes.Inline, nodes.TextElement):
    pass


class nova_quantity(nodes.Inline, nodes.TextElement):
    """A number, a quantity with unit or an angle; ``latex`` holds the siunitx call."""


class nova_box(nodes.General, nodes.Element):
    pass


class nova_algorithm(nodes.General, nodes.Element):
    """Numbered pseudocode; children are nova_algoline nodes."""


class nova_algoline(nodes.Part, nodes.TextElement):
    """One step: ``kind`` is ``step``, ``require`` (Dati) or ``ensure`` (Risultato)."""


# --------------------------------------------------------------------------- numbers

def group_digits(s):
    if len(s) < 4:
        return s
    out = []
    while len(s) > 3:
        out.insert(0, s[-3:])
        s = s[:-3]
    out.insert(0, s)
    return THIN.join(out)


def format_number(text):
    """'2046342' -> '2 046 342', '3.33e-4' -> '3.33 × 10⁻⁴' (HTML)."""
    m = re.fullmatch(r"([-+]?)(\d*)(?:\.(\d+))?(?:[eE]([-+]?\d+))?", text.strip())
    if not m:
        return html.escape(text)
    sign, whole, frac, exp = m.groups()
    s = ("−" if sign == "-" else "") + group_digits(whole or "0")
    if frac:
        s += "." + frac
    if exp:
        e = int(exp)
        s += f"{THIN}×{THIN}10<sup>{'−' if e < 0 else ''}{abs(e)}</sup>"
    return s


# --------------------------------------------------------------------------- roles

class TagRole(SphinxRole):
    def run(self):
        kind = self.text.strip()
        if kind not in TAGS:
            msg = self.inliner.reporter.error(f"unknown label: {kind}", line=self.lineno)
            return [], [msg]
        return [nova_tag(kind, TAGS[kind][0], kind=kind)], []


class ParRole(SphinxRole):
    def run(self):
        return [nova_par(self.text, self.text)], []


class NumRole(SphinxRole):
    def run(self):
        t = self.text.strip()
        return [nova_quantity(t, t, html=format_number(t), latex=rf"\num{{{t}}}")], []


class SiRole(SphinxRole):
    def run(self):
        value, unit = self.text.strip().split(None, 1)
        return [nova_quantity(self.text, self.text,
                               html=format_number(value) + " " + html.escape(unit),
                               latex=rf"\SI{{{value}}}{{{unit}}}")], []


class AngRole(SphinxRole):
    def run(self):
        t = self.text.strip()
        return [nova_quantity(t, t, html=format_number(t) + "°", latex=rf"\ang{{{t}}}")], []


# --------------------------------------------------------------------------- boxes

class BoxDirective(SphinxDirective):
    has_content = True
    optional_arguments = 1
    final_argument_whitespace = True

    def run(self):
        title = self.arguments[0] if self.arguments else BOX_TITLES[self.name]
        node = nova_box(kind=self.name, title=title)
        self.set_source_info(node)
        self.state.nested_parse(self.content, self.content_offset, node)
        return [node]


class AlgorithmDirective(SphinxDirective):
    """Pseudocode written once for the site and the PDF.

    The argument is the title. Each content line is a step; two spaces of indentation per
    nesting level; a line starting with ``input:`` or ``output:`` is the input or the output.
    Lines are parsed as inline Markdown, so ``$math$``, `code` and **bold** work.
    """
    has_content = True
    required_arguments = 1
    final_argument_whitespace = True
    option_spec = {"name": directives.unchanged}

    def run(self):
        node = nova_algorithm(title=self.arguments[0])
        self.set_source_info(node)
        title_nodes, messages = self.state.inline_text(self.arguments[0], self.lineno)
        node["title_nodes"] = title_nodes
        for offset, raw in enumerate(self.content):
            if not raw.strip():
                continue
            indent = (len(raw) - len(raw.lstrip(" "))) // 2
            text = raw.strip()
            kind = "step"
            for prefix, k in (("input:", "require"), ("output:", "ensure")):
                if text.lower().startswith(prefix):
                    kind, text = k, text[len(prefix):].strip()
            line = nova_algoline(text, kind=kind, indent=indent)
            children, msgs = self.state.inline_text(text, self.content_offset + offset)
            line.extend(children)
            messages.extend(msgs)
            node += line
        if "name" in self.options:
            self.add_name(node)
        if not node["ids"]:
            self.state.document.set_id(node)
        return [node] + messages


def algorithm_title(node):
    return node["title"]


# --------------------------------------------------------------------------- HTML

def html_tag(self, node):
    kind = node["kind"]
    label, _, hint = TAGS[kind]
    self.body.append(f'<span class="nova-tag nova-tag-{kind}" title="{hint}">{label}</span>')
    raise nodes.SkipNode


def html_par(self, node):
    self.body.append(f'<strong class="nova-par">{html.escape(node.astext())}.</strong>')
    raise nodes.SkipNode


def html_quantity(self, node):
    self.body.append(f'<span class="nova-num">{node["html"]}</span>')
    raise nodes.SkipNode


def html_box_visit(self, node):
    self.body.append(f'<div class="nova-box nova-box-{node["kind"]}">')
    if node["title"]:
        self.body.append(f'<p class="nova-box-title">{html.escape(node["title"])}</p>')


def html_box_depart(self, node):
    self.body.append("</div>\n")


def _render_inline(self, inline_nodes):
    for child in inline_nodes:
        child.walkabout(self)


def html_algorithm_visit(self, node):
    ident = node["ids"][0]
    self.body.append(f'<div class="nova-algorithm" id="{ident}"><p class="nova-algorithm-title">')
    self.add_fignumber(node)
    for child in node["title_nodes"]:
        child.walkabout(self)
    self.body.append("</p>")
    lines = [c for c in node.children if isinstance(c, nova_algoline)]
    for line in (l for l in lines if l["kind"] == "require"):
        self.body.append('<p class="nova-algorithm-io"><strong>Input:</strong> ')
        _render_inline(self, line.children)
        self.body.append("</p>")
    self.body.append('<ol class="nova-algorithm-steps">')
    for line in (l for l in lines if l["kind"] == "step"):
        self.body.append(f'<li style="--level:{line["indent"]}">')
        _render_inline(self, line.children)
        self.body.append("</li>")
    self.body.append("</ol>")
    for line in (l for l in lines if l["kind"] == "ensure"):
        self.body.append('<p class="nova-algorithm-io"><strong>Output:</strong> ')
        _render_inline(self, line.children)
        self.body.append("</p>")
    self.body.append("</div>\n")
    raise nodes.SkipNode


# --------------------------------------------------------------------------- LaTeX

def latex_tag(self, node):
    self.body.append("\\%s{}" % TAGS[node["kind"]][1])
    raise nodes.SkipNode


def latex_par(self, node):
    self.body.append(r"\novapar{%s}" % self.encode(node.astext()))
    raise nodes.SkipNode


def latex_quantity(self, node):
    self.body.append(node["latex"])
    raise nodes.SkipNode


def latex_box_visit(self, node):
    opt = ""
    if node["title"] != BOX_TITLES[node["kind"]]:
        opt = "[title={\\MakeUppercase{%s}}]" % self.encode(node["title"])
    self.body.append("\n\\begin{%s}%s\n" % (node["kind"], opt))


def latex_box_depart(self, node):
    self.body.append("\n\\end{%s}\n" % node["kind"])


def latex_algorithm_visit(self, node):
    self.body.append("\n\\begin{algorithm}[htbp]\n\\caption{")
    for child in node["title_nodes"]:
        child.walkabout(self)
    self.body.append("}")
    self.body.append(self.hypertarget_to(node))
    self.body.append("\n\\begin{algorithmic}[1]\n")
    for line in node.children:
        if not isinstance(line, nova_algoline):
            continue
        command = {"require": "\\REQUIRE", "ensure": "\\ENSURE", "step": "\\STATE"}[line["kind"]]
        indent = "\\hspace*{%.1fem}" % (1.4 * line["indent"]) if line["indent"] else ""
        self.body.append(f"{command} {indent}")
        _render_inline(self, line.children)
        self.body.append("\n")
    self.body.append("\\end{algorithmic}\n\\end{algorithm}\n")
    raise nodes.SkipNode


def _skip(self, node):
    raise nodes.SkipNode


def setup(app):
    app.add_node(nova_tag, html=(html_tag, None), latex=(latex_tag, None))
    app.add_node(nova_par, html=(html_par, None), latex=(latex_par, None))
    app.add_node(nova_quantity, html=(html_quantity, None), latex=(latex_quantity, None))
    app.add_node(nova_box, html=(html_box_visit, html_box_depart),
                 latex=(latex_box_visit, latex_box_depart))
    app.add_role("tag", TagRole())
    app.add_role("par", ParRole())
    app.add_role("num", NumRole())
    app.add_role("si", SiRole())
    app.add_role("ang", AngRole())
    for name in BOX_TITLES:
        app.add_directive(name, BoxDirective, override=True)
    app.add_enumerable_node(nova_algorithm, "algorithm", algorithm_title,
                            html=(html_algorithm_visit, None), latex=(latex_algorithm_visit, None),
                            text=(_skip, None), man=(_skip, None), texinfo=(_skip, None))
    app.add_node(nova_algoline, html=(_skip, None), latex=(_skip, None))
    app.add_directive("algorithm", AlgorithmDirective)
    return {"version": "1.0", "parallel_read_safe": True, "parallel_write_safe": True}
