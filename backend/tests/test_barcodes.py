"""QR / Code128 rendering + the public /share-image endpoint."""
import asyncio

import pytest

from app.api import manufacturing_router as mr
from app.services import barcodes


def test_qr_and_barcode_svg():
    qs = barcodes.qr_svg("IJ1.ABC123")
    assert qs.startswith("<?xml") and "svg" in qs.lower()
    bs = barcodes.code128_svg("C29BF054")
    assert "svg" in bs.lower()


def test_share_image_endpoint_qr_and_barcode():
    r = asyncio.run(mr.share_image(data="IJ1." + "A" * 120, kind="qr"))
    assert r.media_type == "image/svg+xml" and bytes(r.body)[:5] == b"<?xml"
    r2 = asyncio.run(mr.share_image(data="C29BF054", kind="barcode"))
    assert r2.media_type == "image/svg+xml"


def test_share_image_rejects_oversize_or_empty():
    for bad in ("x" * 5000, ""):
        with pytest.raises(Exception):
            asyncio.run(mr.share_image(data=bad, kind="qr"))
