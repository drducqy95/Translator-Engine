import os
import zipfile
import subprocess
from pathlib import Path

def create_epub(novel_id, title, author, cover_path, md_files, out_path):
    """Sử dụng EbookLib để sinh file EPUB chuẩn"""
    from ebooklib import epub
    import markdown
    
    book = epub.EpubBook()
    book.set_identifier(novel_id)
    book.set_title(title)
    book.set_language('vi')
    if author:
        book.add_author(author)
    
    # Thêm ảnh bìa nếu có
    if cover_path and os.path.exists(cover_path):
        book.set_cover("cover.jpg", open(cover_path, 'rb').read())

    chapters = []
    for idx, md_file in enumerate(md_files):
        with open(md_file, 'r', encoding='utf-8') as f:
            md_text = f.read()
        html = markdown.markdown(md_text)
        
        # Lấy title từ H1 đầu tiên
        chap_title = f"Chương {idx+1}"
        for line in md_text.split('\n'):
            if line.startswith('# '):
                chap_title = line.replace('# ', '').strip()
                break
                
        c = epub.EpubHtml(title=chap_title, file_name=f'chap_{idx:04d}.xhtml', lang='vi')
        c.content = f'<h1>{chap_title}</h1>\n{html}'
        book.add_item(c)
        chapters.append(c)

    # Khai báo mục lục (TOC)
    book.toc = tuple(chapters)
    
    # Thêm default NCX và Nav
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    
    # CSS cơ bản
    style = 'BODY {color: black; font-family: "Times New Roman", serif; padding: 5%;}'
    nav_css = epub.EpubItem(uid="style_nav", file_name="style/nav.css", media_type="text/css", content=style)
    book.add_item(nav_css)
    
    # Thiết lập mạch đọc
    book.spine = ['nav'] + chapters
    epub.write_epub(str(out_path), book, {})
    return out_path

def create_cbz(novel_id, md_files, out_path):
    """Đóng gói CBZ (ZIP)"""
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for md_file in md_files:
            zf.write(md_file, Path(md_file).name)
    return out_path

def export_novel(novel_out_dir: str):
    """Hàm đóng gói tổng hợp, gọi ở cuối pipeline hoặc gọi thủ công"""
    novel_dir = Path(novel_out_dir)
    if not novel_dir.exists():
        raise FileNotFoundError(f"Không tìm thấy thư mục truyện: {novel_dir}")
        
    novel_id = novel_dir.name
    print(f"\n[Exporter] Bắt đầu đóng gói truyện: {novel_id}")
    
    # Đọc Metadata
    title = novel_id
    author = "Unknown"
    readme_file = novel_dir / "README.md"
    if readme_file.exists():
        with open(readme_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('# '):
                    title = line.replace('# ', '').strip()
                if line.startswith('**Tác giả:**'):
                    author = line.replace('**Tác giả:**', '').strip()

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
        create_epub(novel_id, title, author, None, md_files, epub_path)
        print(f"✅ Đã đóng gói: {epub_path.name}")
        output_files.append(epub_path)
    except Exception as e:
        print(f"❌ Lỗi tạo EPUB (Cần chạy 'pip install EbookLib markdown'): {e}")

    # 2. Tạo AZW3 và PDF thông qua Calibre (Nhanh và chuẩn nhất)
    azw3_path = export_dir / f"{title}.azw3"
    pdf_path = export_dir / f"{title}.pdf"
    
    try:
        # Require ebook-convert command from Calibre
        subprocess.run(["ebook-convert", str(epub_path), str(azw3_path)], check=True, stdout=subprocess.DEVNULL)
        print(f"✅ Đã đóng gói: {azw3_path.name}")
        output_files.append(azw3_path)
        
        subprocess.run(["ebook-convert", str(epub_path), str(pdf_path)], check=True, stdout=subprocess.DEVNULL)
        print(f"✅ Đã đóng gói: {pdf_path.name}")
        output_files.append(pdf_path)
    except FileNotFoundError:
        print("⚠️ Cảnh báo: Hệ thống không có phần mềm Calibre ('ebook-convert'). Bỏ qua xuất AZW3 và PDF.")
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
