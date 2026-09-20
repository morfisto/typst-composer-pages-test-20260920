// HTML counterparts for the shared text and Grid editors. PDF keeps Typst layout.
#let css-length(value) = if value == auto { "auto" } else if type(value) == fraction {
  "minmax(0px," + repr(value) + ")"
} else { "calc(" + repr(value) + ")" }

#let web-text-enabled = state("composer-web-text-enabled", true)

#let web-text(content) = context {
  // Only explicit departures from the document defaults override the web theme.
  let base = (size: text.size, fill: text.fill, font: text.font, weight: text.weight,
    style: text.style, tracking: text.tracking)
  show text: it => context {
    if not web-text-enabled.get() { return it }
    let styles = ()
    if text.size != base.size { styles.push("font-size:" + css-length(text.size)) }
    if text.fill != base.fill and type(text.fill) == color { styles.push("color:" + text.fill.to-hex()) }
    if text.font != base.font { styles.push("font-family:" + (if type(text.font) == array { text.font } else { (text.font,) }).map(json.encode).join(",")) }
    if text.weight != base.weight { styles.push("font-weight:" + str((thin: 100, extralight: 200, light: 300, regular: 400, medium: 500, semibold: 600, bold: 700, extrabold: 800, black: 900).at(str(text.weight), default: text.weight))) }
    if text.style != base.style { styles.push("font-style:" + str(text.style)) }
    if text.tracking != base.tracking { styles.push("letter-spacing:" + css-length(text.tracking)) }
    if styles.len() == 0 { it } else { html.elem("span", attrs: (style: styles.join(";")), it) }
  }
  content
}

#let template-content(content) = context {
  if target() != "html" { return content }
  show: web-text
  // Native semantic elements own their CSS defaults, including heading size and code font.
  let default-size = text.size
  let default-weight = text.weight
  let default-font = text.font
  show heading: it => { set text(size: default-size, weight: default-weight); it }
  show raw: it => { set text(font: default-font); it }
  show math.equation: it => { web-text-enabled.update(false); it; web-text-enabled.update(true) }
  show table: it => html.div(class: "composer-native-table-scroll", it)
  show grid: it => {
    let tracks(v) = if type(v) == int { (auto,) * v } else if type(v) == array { if v.len() == 0 { (auto,) } else { v } } else { (v,) }
    let fields = it.fields()
    let columns = tracks(it.columns)
    // Advanced drawing and alternating gutters retain the native visual result.
    let unsupported = (it.column-gutter.len() > 1 or it.row-gutter.len() > 1
      or it.children.any(c => (grid.hline, grid.vline, grid.header, grid.footer).contains(c.func()))
      or fields.at("stroke", default: (:)) != (:)
      or ("align", "fill", "inset").any(name => type(fields.at(name, default: none)) == function))
    if unsupported { return html.div(class: "composer-grid-fallback", html.frame(it)) }
    let gap(v) = if v.len() == 0 { "0px" } else { css-length(v.first()) }
    let style = ("grid-template-columns:" + columns.map(css-length).join(" ")
      + ";grid-template-rows:" + tracks(it.rows).map(css-length).join(" ")
      + ";column-gap:" + gap(it.column-gutter) + ";row-gap:" + gap(it.row-gutter))
    html.div(class: "composer-grid-scroll", html.elem("div", attrs: (class: "composer-grid", style: style), {
      for child in it.children {
        let cell = if child.func() == grid.cell { child.fields() } else { (body: child) }
        let x = cell.at("x", default: auto)
        let y = cell.at("y", default: auto)
        let span = cell.at("colspan", default: 1)
        let rowspan = cell.at("rowspan", default: 1)
        let styles = ("grid-column:" + (if x == auto { "auto" } else { str(x + 1) }) + " / span " + str(span),
          "grid-row:" + (if y == auto { "auto" } else { str(y + 1) }) + " / span " + str(rowspan))
        let property(name, fallback) = {
          let value = cell.at(name, default: auto)
          if value == auto { value = fields.at(name, default: fallback) }
          if type(value) == function { value = value(if x == auto { 0 } else { x }, if y == auto { 0 } else { y }) }
          value
        }
        let inset = property("inset", 0pt)
        if inset != auto and inset != none {
          for side in ("top", "right", "bottom", "left") {
            let v = if type(inset) == dictionary { inset.at(side, default: inset.at(if ("left", "right").contains(side) { "x" } else { "y" }, default: inset.at("rest", default: 0pt))) } else { inset }
            styles.push("padding-" + side + ":" + css-length(v))
          }
        }
        let fill = property("fill", none)
        if type(fill) == color { styles.push("background:" + fill.to-hex()) }
        let align = repr(property("align", auto))
        if align.contains("right") { styles.push("text-align:right") }
        else if align.contains("center") { styles.push("text-align:center") }
        else if align.contains("left") { styles.push("text-align:left") }
        if align.contains("horizon") { styles.push("align-content:center") }
        else if align.contains("bottom") { styles.push("align-content:end") }
        html.elem("div", attrs: (class: "composer-grid-cell", style: styles.join(";")), cell.body)
      }
    }))
  }
  content
}
