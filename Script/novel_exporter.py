import os
import zipfile
import subprocess
import shutil
import json
import mimetypes
import re
import io
from pathlib import Path


def _ebook_convert_env():
    """Prefer distro Python packages for Calibre.

    Some Termux/PRoot installs have pip lxml in /usr/local shadowing the
    distro lxml used by html5-parser. Calibre imports both in ebook-convert,
    so put /usr/lib/python3/dist-packages first for this subprocess only.
    """
    env = os.environ.copy()
    dist = "/usr/lib/python3/dist-packages"
    current = env.get("PYTHONPATH", "")
    parts = [part for part in current.split(os.pathsep) if part]
    if dist not in parts:
        parts.insert(0, dist)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
    return env


def _run_ebook_convert(src_path: Path, out_path: Path):
    if not shutil.which("ebook-convert"):
        raise FileNotFoundError("ebook-convert")
    subprocess.run(
        ["ebook-convert", str(src_path), str(out_path)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=_ebook_convert_env(),
        text=True,
    )


RICH_MARKDOWN_EXTENSIONS = [
    "extra",
    "sane_lists",
    "toc",
    "pymdownx.superfences",
    "pymdownx.arithmatex",
]

RICH_MARKDOWN_CONFIG = {
    "pymdownx.arithmatex": {
        "generic": True,
    },
}

EPUB_STYLE = """
body {
  color: #111;
  font-family: "Noto Serif CJK SC", "Noto Serif CJK TC", "Noto Serif", "Liberation Serif", serif;
  line-height: 1.75;
  padding: 5%;
}
h1, h2, h3 {
  font-family: "Noto Sans CJK SC", "Noto Sans", sans-serif;
  line-height: 1.35;
}
img {
  display: block;
  max-width: 100%;
  height: auto;
  margin: 1em auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  margin: 1em 0;
  font-size: 0.95em;
}
th, td {
  border: 1px solid #777;
  padding: 0.35em 0.5em;
  vertical-align: top;
}
th {
  font-family: "Noto Sans CJK SC", "Noto Sans", sans-serif;
  font-weight: 700;
  background: #f2f2f2;
}
pre, code {
  font-family: "Noto Sans Mono", "Liberation Mono", monospace;
}
pre {
  white-space: pre-wrap;
  word-break: break-word;
}
.arithmatex, math {
  font-family: "Noto Serif Math", "Cambria Math", "STIX Two Math", serif;
}
div.arithmatex {
  display: block;
  overflow-x: auto;
  text-align: center;
  margin: 1em 0;
}
""".strip()

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}


def _markdown_to_html(md_text: str) -> str:
    import markdown

    try:
        return markdown.markdown(
            md_text,
            extensions=RICH_MARKDOWN_EXTENSIONS,
            extension_configs=RICH_MARKDOWN_CONFIG,
            output_format="xhtml",
        )
    except Exception:
        return markdown.markdown(md_text, extensions=["extra", "sane_lists"], output_format="xhtml")


def _safe_asset_name(path: Path, used_names: set[str], suffix: str | None = None) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem).strip("._") or "image"
    suffix = suffix or path.suffix.lower() or ".bin"
    name = f"{stem}{suffix}"
    counter = 1
    while name in used_names:
        name = f"{stem}_{counter}{suffix}"
        counter += 1
    used_names.add(name)
    return name


def _guess_media_type(path: Path) -> str:
    if path.suffix.lower() == ".svg":
        return "image/svg+xml"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _prepare_image_for_epub(path: Path) -> tuple[str, str, bytes] | None:
    if path.suffix.lower() == ".svg":
        return ".svg", "image/svg+xml", path.read_bytes()
    try:
        from PIL import Image, ImageOps

        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source)
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            out = io.BytesIO()
            image.save(out, format="PNG")
            return ".png", "image/png", out.getvalue()
    except Exception:
        return None


def _resolve_local_asset(src: str, md_file: Path, novel_dir: Path) -> Path | None:
    if not src or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", src) or src.startswith("//"):
        return None
    clean_src = src.split("#", 1)[0].split("?", 1)[0]
    candidates = [md_file.parent / clean_src, novel_dir / clean_src]
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


def _embed_local_images(book, html: str, md_file: Path, novel_dir: Path, used_names: set[str]) -> str:
    from bs4 import BeautifulSoup
    from ebooklib import epub

    soup = BeautifulSoup(html, "html.parser")
    for img in soup.find_all("img"):
        src = img.get("src", "")
        asset_path = _resolve_local_asset(src, md_file, novel_dir)
        if not asset_path or asset_path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        prepared = _prepare_image_for_epub(asset_path)
        if not prepared:
            img.decompose()
            continue
        suffix, media_type, content = prepared
        asset_name = _safe_asset_name(asset_path, used_names, suffix=suffix)
        epub_name = f"images/{asset_name}"
        book.add_item(
            epub.EpubItem(
                uid=f"img_{len(used_names)}",
                file_name=epub_name,
                media_type=media_type,
                content=content,
            )
        )
        img["src"] = epub_name
    return str(soup)


def _load_metadata(novel_dir: Path) -> dict:
    metadata_file = novel_dir / "metadata.json"
    if not metadata_file.exists():
        return {}
    try:
        return json.loads(metadata_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _find_cover_path(novel_dir: Path, metadata: dict) -> Path | None:
    cover_file = metadata.get("cover_file")
    if cover_file:
        cover_path = novel_dir / cover_file
        if cover_path.exists():
            return cover_path
    for name in ("cover.jpg", "cover.jpeg", "cover.png", "cover.webp"):
        cover_path = novel_dir / name
        if cover_path.exists():
            return cover_path
    return None


def _extract_readme_metadata(novel_dir: Path) -> tuple[str | None, str | None]:
    title = None
    author = None
    readme_file = novel_dir / "README.md"
    if not readme_file.exists():
        return title, author
    with open(readme_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith('# '):
                title = line.replace('# ', '').strip()
            if line.startswith('**Tác giả:**'):
                author = line.replace('**Tác giả:**', '').strip()
    return title, author


def create_epub(novel_id, title, author, cover_path, md_files, out_path):
    """Sử dụng EbookLib để sinh file EPUB chuẩn"""
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier(novel_id)
    book.set_title(title)
    book.set_language('vi')
    if author:
        book.add_author(author)

    novel_dir = Path(md_files[0]).parent if md_files else Path(out_path).parent
    nav_css = epub.EpubItem(uid="style_nav", file_name="style/nav.css", media_type="text/css", content=EPUB_STYLE)
    book.add_item(nav_css)

    # Thêm ảnh bìa nếu có
    if cover_path and os.path.exists(cover_path):
        prepared_cover = _prepare_image_for_epub(Path(cover_path))
        if prepared_cover:
            suffix, _, content = prepared_cover
            book.set_cover(f"cover{suffix}", content)

    chapters = []
    used_image_names = set()
    for idx, md_file in enumerate(md_files):
        md_file = Path(md_file)
        with open(md_file, 'r', encoding='utf-8') as f:
            md_text = f.read()
        html = _markdown_to_html(md_text)
        html = _embed_local_images(book, html, md_file, novel_dir, used_image_names)

        # Lấy title từ H1 đầu tiên
        chap_title = f"Chương {idx+1}"
        for line in md_text.split('\n'):
            if line.startswith('# '):
                chap_title = line.replace('# ', '').strip()
                break

        c = epub.EpubHtml(title=chap_title, file_name=f'chap_{idx:04d}.xhtml', lang='vi')
        c.content = f'<h1>{chap_title}</h1>\n{html}'
        c.add_item(nav_css)
        book.add_item(c)
        chapters.append(c)

    # Khai báo mục lục (TOC)
    book.toc = tuple(chapters)

    # Thêm default NCX và Nav
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # Thiết lập mạch đọc
    book.spine = ['nav'] + chapters
    epub.write_epub(str(out_path), book, {})
    return out_path


def create_cbz(novel_id, md_files, out_path):
    """Đóng gói CBZ (ZIP)"""
    novel_dir = Path(md_files[0]).parent if md_files else Path(out_path).parent
    image_paths = []
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for md_file in md_files:
            md_file = Path(md_file)
            zf.write(md_file, Path(md_file).name)
            text = md_file.read_text(encoding="utf-8")
            for src in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text):
                asset_path = _resolve_local_asset(src.strip().strip('"\''), md_file, novel_dir)
                if asset_path and asset_path.suffix.lower() in IMAGE_EXTENSIONS and asset_path not in image_paths:
                    image_paths.append(asset_path)
        for idx, image_path in enumerate(image_paths, 1):
            zf.write(image_path, f"images/{idx:04d}_{image_path.name}")
    return out_path


def export_novel(novel_out_dir: str):
    """Hàm đóng gói tổng hợp, gọi ở cuối pipeline hoặc gọi thủ công"""
    novel_dir = Path(novel_out_dir)
    if not novel_dir.exists():
        raise FileNotFoundError(f"Không tìm thấy thư mục truyện: {novel_dir}")

    novel_id = novel_dir.name
    print(f"\n[Exporter] Bắt đầu đóng gói truyện: {novel_id}")

    # Đọc Metadata
    metadata = _load_metadata(novel_dir)
    title = novel_id
    author = "Unknown"
    readme_title, readme_author = _extract_readme_metadata(novel_dir)
    title = metadata.get("title") or readme_title or title
    author = metadata.get("author") or readme_author or author
    cover_path = _find_cover_path(novel_dir, metadata)

    # Gom file dịch
    md_files = sorted(list(novel_dir.glob("*_vi.md")))
    if not md_files:
        raise ValueError(f"Không có chương nào đã dịch (*_vi.md) trong thư mục này.")

    export_dir = novel_dir / "Export"
    export_dir.mkdir(exist_ok=True)

    output_files = []

    # 1. Tạo EPUB
    epub_path = export_dir / f"{title}.epub"
    try:
        create_epub(novel_id, title, author, cover_path, md_files, epub_path)
        print(f"✅ Đã đóng gói: {epub_path.name}")
        output_files.append(epub_path)
    except Exception as e:
        print(f"❌ Lỗi tạo EPUB (Cần chạy 'pip install EbookLib markdown'): {e}")

    # 2. Tạo AZW3 và PDF thông qua Calibre (Nhanh và chuẩn nhất)
    azw3_path = export_dir / f"{title}.azw3"
    pdf_path = export_dir / f"{title}.pdf"

    try:
        # Require ebook-convert command from Calibre
        _run_ebook_convert(epub_path, azw3_path)
        print(f"✅ Đã đóng gói: {azw3_path.name}")
        output_files.append(azw3_path)

        _run_ebook_convert(epub_path, pdf_path)
        print(f"✅ Đã đóng gói: {pdf_path.name}")
        output_files.append(pdf_path)
    except FileNotFoundError:
        print("⚠️ Cảnh báo: Hệ thống không có phần mềm Calibre ('ebook-convert'). Bỏ qua xuất AZW3 và PDF.")
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or "").strip().splitlines()[-1:] or [str(e)]
        print(f"❌ Lỗi convert AZW3/PDF: {detail[0]}")
    except Exception as e:
        print(f"❌ Lỗi convert AZW3/PDF: {e}")

    # 3. Tạo CBZ
    cbz_path = export_dir / f"{title}.cbz"
    try:
        create_cbz(novel_id, md_files, cbz_path)
        print(f"✅ Đã đóng gói: {cbz_path.name}")
        output_files.append(cbz_path)
    except Exception as e:
        print(f"❌ Lỗi tạo CBZ: {e}")

    print(f"🎉 Hoàn tất quá trình Export cho truyện {novel_id}.")
    return output_files
