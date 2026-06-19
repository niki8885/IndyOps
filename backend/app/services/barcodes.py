"""
QR + Code128 rendering shared by the PDF reports and the /share-image endpoint.

Pure over reportlab.graphics (already a dependency): ``*_drawing`` returns a platypus
Drawing for the PDFs, ``*_svg`` returns an SVG string for the on-screen <img>. QR uses
the low ('L') error-correction level so a long reopen-URL stays as scannable as possible.
"""
from __future__ import annotations

from reportlab.graphics import renderSVG
from reportlab.graphics.barcode import createBarcodeDrawing, qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm


def qr_drawing(data: str, size: float = 26 * mm) -> Drawing:
    widget = qr.QrCodeWidget(data or " ", barLevel="L")
    b = widget.getBounds()
    w, h = (b[2] - b[0]) or 1, (b[3] - b[1]) or 1
    d = Drawing(size, size, transform=[size / w, 0, 0, size / h, 0, 0])
    d.add(widget)
    return d


def code128_drawing(value: str, bar_height: float = 14 * mm, bar_width=None) -> Drawing:
    kw = {"barHeight": bar_height, "humanReadable": True, "fontSize": 9}
    if bar_width:
        kw["barWidth"] = bar_width
    return createBarcodeDrawing("Code128", value=value or " ", **kw)


def qr_svg(data: str) -> str:
    widget = qr.QrCodeWidget(data or " ", barLevel="L")
    b = widget.getBounds()
    w, h = (b[2] - b[0]) or 1, (b[3] - b[1]) or 1
    d = Drawing(w, h)
    d.add(widget)
    return renderSVG.drawToString(d)


def code128_svg(value: str) -> str:
    return renderSVG.drawToString(code128_drawing(value))
