// Composer HTML components. The content remains ordinary editable Typst.
#let blog-button(dest, body, style: "filled") = {
  assert(type(dest) == str and not dest.contains("\\"), message: "Button destination must be a URL")
  let address = lower(dest)
  assert(not address.starts-with("//") and (not address.contains(":") or ("https:", "http:", "mailto:", "tel:").any(prefix => address.starts-with(prefix))), message: "Unsupported button URL")
  assert(("filled", "outline", "plain").contains(style), message: "Unknown button style")
  html.a(href: dest, class: "blog-button blog-button-" + style, body)
}

#let blog-image(path, alt: "", width: 100, height: none, fit: "contain", placement: "body", caption: none) = {
  assert(type(path) == str and not path.contains("\\"), message: "Image path must be a local website path")
  assert(not path.contains(":") and not path.starts-with("//"), message: "Import the image into this website first")
  assert(width > 0 and width <= 100, message: "Image width must be between 1 and 100 percent")
  assert(height == none or (height > 0 and height <= 3000), message: "Image height must be between 1 and 3000 pixels")
  assert(("contain", "cover", "fill").contains(fit), message: "Unknown image fit")
  assert(("body", "full", "margin").contains(placement), message: "Unknown image placement")
  let source = if path.starts-with("/content/") { path.slice(8) } else { path }
  let image-style = "display:block;width:100%;height:" + (if height == none { "auto" } else { str(height) + "px" }) + ";object-fit:" + fit
  html.elem("figure", attrs: (class: "blog-image blog-image-" + placement, style: "--blog-image-scale:" + str(width / 100)), {
    html.elem("img", attrs: (src: source, alt: alt, loading: "lazy", decoding: "async", style: image-style))
    if caption != none { html.figcaption(caption) }
  })
}

#let margin-note(body) = html.span(class: "marginnote", body)
#let full-width(body) = html.div(class: "fullwidth", body)
