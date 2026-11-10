"""Wordマニュアル（.docx）を記事に変換して data/articles.json に反映する。

使い方（リポジトリのルートで。pandoc と Pillow が必要）:
    python3 tools/import_docx.py oripa            # manuals/manuals.json の oripa を取り込み
    python3 tools/import_docx.py oripa --dry-run  # 変わる記事を表示するだけ
    python3 tools/build.py                        # そのあと index.html を作り直す

- 同じマニュアルの記事は丸ごと入れ替わる（記事の並び順の位置は保つ）。
- 「よく見られるガイド」(featured) と食い違い注意 (notes) の設定は、同じIDなら引き継ぐ。
- サイト上で直接書き足した説明（写真の説明文や他記事への案内など）は消えるので、
  --dry-run で差分を確認してから取り込むこと。
"""
import argparse, datetime, hashlib, io, json, re, subprocess, sys, tempfile
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / 'data/articles.json'
IMG_DIR = ROOT / 'assets/img'
DRY_RUN = False


def save_image(path: Path) -> str:
    im = Image.open(path).convert('RGB')
    im.thumbnail((1000, 1000))
    buf = io.BytesIO(); im.save(buf, 'JPEG', quality=74, optimize=True)
    raw = buf.getvalue()
    name = hashlib.sha1(raw).hexdigest()[:12] + '.jpeg'
    if not DRY_RUN:
        (IMG_DIR / name).write_bytes(raw)
    return name


def to_html(body: str) -> str:
    html = subprocess.run(['pandoc', '-f', 'markdown', '-t', 'html', '--wrap=none'],
                          input=body, capture_output=True, text=True, check=True).stdout
    html = re.sub(r'src="([^"]+/media/[^"]+)"', lambda m: f'src="{{{{img:{save_image(Path(m.group(1)))}}}}}" loading="lazy"', html)
    html = re.sub(r'\s(width|height)="[^"]*"', '', html)
    html = re.sub(r'\sstyle="[^"]*"', '', html)
    html = re.sub(r'<figcaption[^>]*>.*?</figcaption>', '', html, flags=re.S)
    html = re.sub(r'<figure>\s*<img', '<figure class="photo"><img', html)
    html = re.sub(r'<h1([^>]*)>', r'<h2\1>', html).replace('</h1>', '</h2>')
    html = re.sub(r'<p><strong>([①-⑩][^<]*)</strong></p>', r'<h2>\1</h2>', html)
    html = re.sub(r'<h2([^>]*)><strong>(.*?)</strong></h2>', r'<h2\1>\2</h2>', html)

    def chk(m):  # □ で始まる行 → タップできるチェック項目
        out = []
        for it in re.split(r'<br\s*/?>\s*', m.group(1)):
            it = it.strip()
            if it.startswith('□'):
                out.append('<label class="chk"><input type="checkbox"><span>' + it[1:].strip() + '</span></label>')
            elif it:
                out.append('<p>' + it + '</p>')
        return ''.join(out)
    html = re.sub(r'<p>(□.*?)</p>', chk, html, flags=re.S)
    html = re.sub(r'<h[23][^>]*>\s*</h[23]>', '', html)
    html = re.sub(r'<p>(\d{1,2})[\s　]+', r'<p class="step"><span class="num">\1</span>', html)
    html = re.sub(r'<h3[^>]*>手順(\d+)\s*(.*?)</h3>', r'<h3 class="stp"><span class="num">\1</span>\2</h3>', html)
    html = re.sub(r'<p>(実物写真|研修用生成画像|既存の注釈付き実物写真)', r'<p class="cap"><span class="tag">\1</span>', html)
    html = re.sub(r'(<h2[^>]*>)\d{1,2}\s+', r'\1', html)

    def fix_head(m):  # 見出し行が複数ある表 → 2行目以降を本文に
        rows = re.findall(r'<tr[^>]*>.*?</tr>', m.group(1), flags=re.S)
        if len(rows) <= 1:
            return m.group(0)
        rest = ''.join(re.sub(r'<(/?)th', r'<\1td', r) for r in rows[1:])
        return '<thead>' + rows[0] + '</thead><tbody>' + rest
    html = re.sub(r'<thead>(.*?)</thead>\s*<tbody>', fix_head, html, flags=re.S)
    html = re.sub(r'<colgroup>.*?</colgroup>', '', html, flags=re.S)
    html = html.replace('<table>', '<div class="tbl"><table>').replace('</table>', '</table></div>')
    html = re.sub(r'(?<!href=")(?<!">)(https?://[^\s<"）)]+)', r'<a href="\1" target="_blank" rel="noopener">\1</a>', html)
    # Wordの改行が引用記号（>）として残るのを消す
    html = re.sub(r'(<br />\n)&gt; ', r'\1', html).replace(' &gt; ', ' ')
    if '<h2' not in html:  # 見出し2で分けた記事は、見出し3を目次の見出しにする
        html = re.sub(r'<h3(?! class="stp")([^>]*)>', r'<h2\1>', html)
        html = re.sub(r'</h3>', '</h2>', html).replace('<h2 class="stp">', '<h3 class="stp">')
    return html


def plain(html: str) -> str:
    t = re.sub(r'<img[^>]*>', ' ', html)
    t = re.sub(r'<[^>]+>', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def docx_to_md(docx: Path, tmp: Path) -> str:
    md = subprocess.run(['pandoc', str(docx), '-t', 'markdown-grid_tables-multiline_tables-simple_tables',
                         '--columns=10000', f'--extract-media={tmp}'],
                        capture_output=True, text=True, check=True).stdout
    md = re.sub(r'^#{2,3} (!\[)', r'\1', md, flags=re.M)   # 見出しの中に入った画像
    md = re.sub(r'^#{1,3} *$\n?', '', md, flags=re.M)      # 空の見出し
    return md


def convert(key: str, conf: dict, date: str) -> list:
    with tempfile.TemporaryDirectory() as tmp:
        text = docx_to_md(ROOT / 'manuals' / conf['file'], Path(tmp))
        out = []
        if conf['level'] == 0:
            text = re.sub(r'^# .*\n', '', text, count=1) if text.lstrip().startswith('# **') else text
            html = to_html(text)
            return [dict(id=conf['id'], cat=conf['cat'], featured=False, no='✓', title=conf['title'],
                         html=html, text=plain(html), source=conf['source'], chap='全体', updated=date)]
        pat = r'^# (.+)$' if conf['level'] == 1 else r'^## (.+)$'
        parts = re.split(pat, text, flags=re.M)
        k = 0
        for i in range(1, len(parts), 2):
            title, body = parts[i].strip(), parts[i + 1]
            if not title or '目次' in title:
                continue
            if 'map' in conf:
                if title not in conf['map']:
                    print(f'  ※ 対応表にない章を飛ばしました: {title}', file=sys.stderr)
                    continue
                aid, cat = conf['map'][title]
                no = title.split(' ')[0]
                no = '0' if no == 'はじめに' else no
                clean = re.sub(r'^(\d+|付録)\s+', '', title)
                chap = title.split(' ')[0]
            else:
                k += 1
                aid, cat, no, chap = f"{conf['prefix']}-{k}", conf['cat'], str(k), f'第{k}章'
                clean = re.sub(r'^(第\d+章[：:\s]*|\d+\.\s*)', '', title)
            html = to_html(body)
            out.append(dict(id=aid, cat=cat, featured=False, no=no, title=clean, html=html,
                            text=plain(html), source=conf['source'], chap=chap, updated=date))
        return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('key', help='manuals/manuals.json のキー（例: oripa）')
    ap.add_argument('--date', default=datetime.date.today().isoformat(), help='更新日 YYYY-MM-DD')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    global DRY_RUN
    DRY_RUN = args.dry_run

    confs = json.loads((ROOT / 'manuals/manuals.json').read_text(encoding='utf-8'))
    if args.key not in confs:
        sys.exit(f'manuals.json に {args.key} がありません。候補: {[k for k in confs if not k.startswith("_")]}')
    conf = confs[args.key]
    articles = json.loads(ARTICLES.read_text(encoding='utf-8'))
    new = convert(args.key, conf, args.date)

    def mine(a):
        if 'map' in conf: return a['id'] in {v[0] for v in conf['map'].values()}
        if conf['level'] == 0: return a['id'] == conf['id']
        return a['id'].startswith(conf['prefix'] + '-')
    old = {a['id']: a for a in articles if mine(a)}
    for a in new:  # 設定の引き継ぎ
        if a['id'] in old:
            a['featured'] = old[a['id']].get('featured', False)
            if old[a['id']].get('notes'): a['notes'] = old[a['id']]['notes']

    changed = [a['id'] for a in new if a['id'] not in old or old[a['id']]['text'] != a['text'] or old[a['id']]['title'] != a['title']]
    removed = [i for i in old if i not in {a['id'] for a in new}]
    print(f'{conf["source"]}: {len(new)}記事（変更 {len(changed)}・削除 {len(removed)}）')
    for i in changed: print('  変更/追加:', i)
    for i in removed: print('  削除:', i)
    if args.dry_run:
        return

    pos = next((n for n, a in enumerate(articles) if mine(a)), len(articles))
    rest = [a for a in articles if not mine(a)]
    articles = rest[:pos] + new + rest[pos:]
    ARTICLES.write_text(json.dumps(articles, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print('data/articles.json を更新しました。次に python3 tools/build.py を実行してください。')


if __name__ == '__main__':
    main()
