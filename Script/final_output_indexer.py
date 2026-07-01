import html
import json
from pathlib import Path


def _chapter_index(path: Path) -> int:
    import re
    match = re.search(r'(?:chapter|chuong)[_\s-]*0*([0-9]+)|Chương\s*0*([0-9]+)', path.name, re.IGNORECASE)
    if not match:
        return 10**9
    return int(match.group(1) or match.group(2))


def _chapter_title(path: Path) -> str:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                text = line.strip()
                if text.startswith('# '):
                    return text[2:].strip()
                if text:
                    break
    except Exception:
        pass
    return path.stem


def refresh(final_root: Path) -> bool:
    final_root = Path(final_root)
    if not final_root.exists():
        return False

    novels = []
    for novel_dir in sorted(p for p in final_root.iterdir() if p.is_dir()):
        chapters = []
        for idx, chapter in enumerate(sorted(novel_dir.glob('*.md'), key=_chapter_index), 1):
            if chapter.name.upper() == 'README.MD':
                continue
            title = _chapter_title(chapter)
            chapters.append({
                'index': idx,
                'file': chapter.name,
                'title': title,
                'path': chapter.name,
            })

        toc = {'novel': novel_dir.name, 'chapters': chapters}
        (novel_dir / 'toc.json').write_text(json.dumps(toc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

        lines = [
            f'# {novel_dir.name}',
            '',
            '- [Final Output Home](../HOME.md)',
            '- [Root README](../README.md)',
            '- [Root TOC](../toc.json)',
            '- [This TOC](toc.json)',
            '',
            f'Chapters: {len(chapters)}',
            '',
            '## Chapters',
        ]
        for chapter in chapters:
            lines.append(f"- {chapter['index']}. [{chapter['title']}]({chapter['file']})")
        (novel_dir / 'README.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')

        novels.append({
            'novel': novel_dir.name,
            'readme': f'{novel_dir.name}/README.md',
            'toc': f'{novel_dir.name}/toc.json',
            'chapter_count': len(chapters),
            'chapters': [{**chapter, 'path': f"{novel_dir.name}/{chapter['file']}"} for chapter in chapters],
        })

    root_toc = {'novels': novels}
    (final_root / 'toc.json').write_text(json.dumps(root_toc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (final_root / 'README.md').write_text(
        '# Final Output\n\nASCII-safe mirror for GitHub/mobile browsing.\n\n'
        '- [HOME.md](HOME.md)\n- [toc.json](toc.json)\n- [index.html](index.html)\n\n## Novels\n'
        + ''.join(f"- [{n['novel']}]({n['readme']}) — [toc.json]({n['toc']}) — {n['chapter_count']} chapters\n" for n in novels),
        encoding='utf-8',
    )
    (final_root / 'HOME.md').write_text(
        '# Final Output Home\n\nASCII-safe browsing root for GitHub app/mobile.\n\n'
        '- [README.md](README.md)\n- [toc.json](toc.json)\n- [index.html](index.html)\n\n## Novels\n'
        + ''.join(f"- **{n['novel']}** — [README]({n['readme']}) · [TOC]({n['toc']}) · {n['chapter_count']} chapters\n" for n in novels),
        encoding='utf-8',
    )

    cards = []
    for novel in novels:
        first = ''
        if novel['chapters']:
            first_path = html.escape(novel['chapters'][0]['path'], quote=True)
            first = f'<a href="{first_path}">chapter 1</a>'
        cards.append(
            f'<li><strong>{html.escape(novel["novel"])}</strong><span>{novel["chapter_count"]} chapters</span>'
            f'<a href="{html.escape(novel["readme"], quote=True)}">README</a>'
            f'<a href="{html.escape(novel["toc"], quote=True)}">TOC</a>{first}</li>'
        )
    (final_root / 'index.html').write_text('''<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Final Output ASCII</title>
  <style>
    :root{color-scheme:light dark;font-family:system-ui,-apple-system,Segoe UI,sans-serif;line-height:1.5}
    body{max-width:1100px;margin:auto;padding:24px}
    header{margin-bottom:20px}
    nav a,li a{margin-right:12px}
    ul{padding:0;list-style:none}
    li{padding:12px 0;border-bottom:1px solid #8884;display:flex;gap:12px;flex-wrap:wrap;align-items:baseline}
    li span{opacity:.75}
    input{width:100%;padding:12px;margin:12px 0 20px;border:1px solid #8888;border-radius:8px;font:inherit}
  </style>
</head>
<body>
<header>
  <h1>Final Output ASCII</h1>
  <p>GitHub/mobile-safe mirror. TOC titles use Vietnamese translated chapter headings.</p>
  <nav><a href="README.md">README.md</a><a href="HOME.md">HOME.md</a><a href="toc.json">toc.json</a></nav>
</header>
<input id="q" placeholder="Filter novels..." autocomplete="off">
<ul id="list">
''' + '\n'.join(cards) + '''
</ul>
<script>
const q=document.getElementById('q');
const items=[...document.querySelectorAll('#list li')];
q.addEventListener('input',()=>{const s=q.value.toLowerCase();items.forEach(i=>i.style.display=i.textContent.toLowerCase().includes(s)?'':'none')});
</script>
</body>
</html>
''', encoding='utf-8')
    return True


if __name__ == '__main__':
    import sys
    refresh(Path(sys.argv[1]) if len(sys.argv) > 1 else Path('Final_Output_ASCII'))
