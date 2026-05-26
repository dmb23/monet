"""Shared paths for test fixtures."""

from pathlib import Path

PDF_DIR = Path(__file__).parent / "pdfs"

TRIODOS_GIRO_PDF = PDF_DIR / "triodos_kontoauszug_giro.pdf"
TRIODOS_SPARKONTO_PDF = PDF_DIR / "triodos_kontoauszug_sparkonto.pdf"
TRIODOS_KREDITKARTE_PDF = PDF_DIR / "triodos_kreditkarte.pdf"
