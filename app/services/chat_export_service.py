from __future__ import annotations

from datetime import datetime
import html
import re


SUMMARY_LABELS = ("Batafsil:", "Qisqa qilib aytganda:", "Details:", "In short:")


def _safe_filename_fragment(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    normalized = re.sub(r"\s+", "_", raw)
    normalized = re.sub(r"[^0-9A-Za-z_.\-]+", "", normalized)
    return normalized[:80].strip("._-")


def build_export_filename(question: str, sources: list[dict] | None, export_format: str) -> str:
    source_code = ""
    if isinstance(sources, list) and sources:
        source_code = _safe_filename_fragment(str(sources[0].get("shnq_code") or ""))
    question_part = _safe_filename_fragment(question[:90])
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    prefix = source_code or question_part or "shnq_ai_export"
    suffix = "word" if export_format == "word" else "print"
    return f"{prefix}_{suffix}_{stamp}"


def _extract_table_markup(table_html: str | None) -> str:
    raw = (table_html or "").strip()
    if not raw:
        return ""
    body_match = re.search(r"<body[^>]*>([\s\S]*?)</body>", raw, flags=re.IGNORECASE)
    if body_match:
        return body_match.group(1).strip()
    return raw


def _render_answer_html(answer: str) -> str:
    value = (answer or "").strip()
    if not value:
        return "<p>Javob mavjud emas.</p>"

    paragraphs: list[str] = []
    for block in re.split(r"\n{2,}", value):
        cleaned = block.strip()
        if not cleaned:
            continue
        safe = html.escape(cleaned).replace("\n", "<br />")
        for label in SUMMARY_LABELS:
            safe = safe.replace(
                html.escape(label),
                f'<span class="export-label">{html.escape(label)}</span>',
                1,
            )
        paragraphs.append(f"<p>{safe}</p>")
    return "\n".join(paragraphs) if paragraphs else "<p>Javob mavjud emas.</p>"


def _render_sources_html(sources: list[dict] | None) -> str:
    if not isinstance(sources, list) or not sources:
        return ""

    rows: list[str] = []
    for item in sources[:8]:
        if not isinstance(item, dict):
            continue
        code = html.escape(str(item.get("shnq_code") or "SHNQ"))
        chapter = html.escape(str(item.get("chapter") or item.get("section_title") or "Noma'lum bo'lim"))
        ref = (
            str(item.get("table_number") or "").strip()
            or str(item.get("clause_number") or "").strip()
            or str(item.get("title") or "").strip()
            or "-"
        )
        snippet = html.escape(str(item.get("snippet") or "")[:220])
        rows.append(
            (
                '<div class="source-chip">'
                f'<div class="source-head">{code}</div>'
                f'<div class="source-meta">{chapter} | {html.escape(ref)}</div>'
                f'<div class="source-snippet">{snippet}</div>'
                "</div>"
            )
        )
    return "\n".join(rows)


def _render_images_html(image_urls: list[str] | None) -> str:
    if not isinstance(image_urls, list):
        return ""
    items = [url.strip() for url in image_urls if isinstance(url, str) and url.strip()]
    if not items:
        return ""
    return "\n".join(
        (
            '<div class="image-card">'
            f'<img src="{html.escape(url)}" alt="SHNQ image" />'
            "</div>"
        )
        for url in items[:6]
    )


def build_chat_export_html(
    *,
    question: str,
    answer: str,
    table_html: str | None = None,
    sources: list[dict] | None = None,
    image_urls: list[str] | None = None,
    export_format: str = "word",
) -> str:
    question_html = html.escape((question or "").strip()).replace("\n", "<br />")
    answer_html = _render_answer_html(answer)
    table_markup = _extract_table_markup(table_html)
    sources_html = _render_sources_html(sources)
    images_html = _render_images_html(image_urls)
    generated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    auto_print_script = ""
    if export_format == "pdf":
        auto_print_script = """
<script>
window.addEventListener("load", () => {
  setTimeout(() => {
    try {
      window.focus();
      window.print();
    } catch (error) {
      console.error("print failed", error);
    }
  }, 280);
});
</script>
"""

    return f"""<!DOCTYPE html>
<html xmlns:o="urn:schemas-microsoft-com:office:office"
      xmlns:w="urn:schemas-microsoft-com:office:word"
      xmlns="http://www.w3.org/TR/REC-html40">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>SHNQ AI export</title>
    <style>
      @page {{
        size: A4;
        margin: 14mm;
      }}
      :root {{
        --ink: #0f172a;
        --muted: #475569;
        --line: #cbd5e1;
        --panel: #f8fafc;
        --panel-strong: #e2e8f0;
        --accent: #1d4ed8;
      }}
      * {{
        box-sizing: border-box;
      }}
      html, body {{
        margin: 0;
        padding: 0;
        color: var(--ink);
        background: #ffffff;
        font-family: "Segoe UI", Arial, sans-serif;
        line-height: 1.6;
      }}
      body {{
        padding: 0;
      }}
      .sheet {{
        width: 100%;
      }}
      .hero {{
        border: 1px solid var(--line);
        background: linear-gradient(135deg, #eff6ff 0%, #f8fafc 100%);
        border-radius: 18px;
        padding: 18px 20px;
        margin-bottom: 16px;
      }}
      .eyebrow {{
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--accent);
        margin-bottom: 8px;
      }}
      .title {{
        font-size: 22px;
        font-weight: 800;
        margin: 0 0 8px;
      }}
      .subtitle {{
        font-size: 12px;
        color: var(--muted);
        margin: 0;
      }}
      .grid {{
        display: block;
      }}
      .card {{
        border: 1px solid var(--line);
        border-radius: 16px;
        background: #ffffff;
        padding: 16px 18px;
        margin-bottom: 14px;
      }}
      .card-title {{
        font-size: 12px;
        font-weight: 800;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--muted);
        margin: 0 0 10px;
      }}
      .question-box {{
        background: var(--panel);
        border: 1px solid var(--panel-strong);
        border-radius: 14px;
        padding: 14px 16px;
        font-size: 15px;
        font-weight: 600;
      }}
      .answer-box p {{
        margin: 0 0 12px;
        font-size: 14px;
      }}
      .export-label {{
        display: inline-block;
        font-weight: 800;
        color: var(--accent);
        margin-right: 6px;
      }}
      .sources-grid {{
        display: block;
      }}
      .source-chip {{
        border: 1px solid var(--line);
        background: var(--panel);
        border-radius: 14px;
        padding: 10px 12px;
        margin-bottom: 10px;
      }}
      .source-head {{
        font-size: 13px;
        font-weight: 800;
        color: var(--ink);
        margin-bottom: 2px;
      }}
      .source-meta {{
        font-size: 11px;
        color: var(--muted);
        margin-bottom: 6px;
      }}
      .source-snippet {{
        font-size: 12px;
        color: var(--ink);
      }}
      .table-shell {{
        border: 1px solid var(--line);
        border-radius: 16px;
        overflow: hidden;
        background: #ffffff;
        padding: 12px;
      }}
      .table-shell table {{
        width: 100% !important;
        border-collapse: collapse !important;
        table-layout: auto !important;
        background: #ffffff !important;
      }}
      .table-shell th,
      .table-shell td {{
        border: 1px solid #334155 !important;
        color: #0f172a !important;
        background: #ffffff !important;
        padding: 8px 10px !important;
        white-space: normal !important;
        word-break: break-word !important;
        font-size: 12px !important;
        vertical-align: top !important;
      }}
      .table-shell img {{
        max-width: 100% !important;
        height: auto !important;
      }}
      .image-card {{
        border: 1px solid var(--line);
        border-radius: 16px;
        padding: 10px;
        margin-bottom: 10px;
      }}
      .image-card img {{
        max-width: 100%;
        height: auto;
        display: block;
      }}
      .footer-note {{
        margin-top: 10px;
        font-size: 11px;
        color: var(--muted);
        text-align: right;
      }}
      @media print {{
        .hero,
        .card,
        .table-shell,
        .source-chip,
        .image-card {{
          break-inside: avoid;
        }}
      }}
    </style>
    {auto_print_script}
  </head>
  <body>
    <main class="sheet">
      <section class="hero">
        <div class="eyebrow">SHNQ AI Export</div>
        <h1 class="title">Savol va javob eksporti</h1>
        <p class="subtitle">Yaratilgan vaqt: {generated_at}</p>
      </section>

      <section class="card">
        <h2 class="card-title">Savol</h2>
        <div class="question-box">{question_html}</div>
      </section>

      <section class="card answer-box">
        <h2 class="card-title">Javob</h2>
        {answer_html}
      </section>

      {f'<section class="card"><h2 class="card-title">Manbalar</h2><div class="sources-grid">{sources_html}</div></section>' if sources_html else ''}
      {f'<section class="card"><h2 class="card-title">Jadval</h2><div class="table-shell">{table_markup}</div></section>' if table_markup else ''}
      {f'<section class="card"><h2 class="card-title">Rasm</h2>{images_html}</section>' if images_html else ''}

      <div class="footer-note">SHNQ AI tomonidan tayyorlandi</div>
    </main>
  </body>
</html>"""
