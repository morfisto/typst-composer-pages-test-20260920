#let template-math(content) = {
  set math.equation(numbering: "(1)")

  let html-math-content(it) = if sys.version >= version(0, 15, 0) {
    it
  } else {
    html.frame(it)
  }

  show math.equation.where(block: false): it => {
    if target() == "html" {
      html.span(class: "math-inline", role: "math", html-math-content(it))
    } else {
      it
    }
  }

  show math.equation.where(block: true): it => context {
    if target() == "html" {
      html.figure(class: "math-block", html-math-content(it) + if it.numbering != none {
        html.div(class: "equation-number", numbering(it.numbering, ..counter(math.equation).at(it.location())))
      })
    } else {
      it
    }
  }

  content
}
