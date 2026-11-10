"""トレぴ ヘルプセンターを1つのHTML（index.html）に組み立てる。

使い方（リポジトリのルートで）:
    python3 tools/build.py

  src/template.html   … 画面のデザインと動き（記事データは /*ARTICLES*/ に入る）
  data/articles.json  … 全記事。画像は {{img:ファイル名}} で assets/img/ を参照
  assets/logo.jpg     … ヘッダーのロゴ
出力の index.html は画像も含めて1ファイルで動く。
"""
import base64, json, mimetypes, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or 'image/jpeg'
    return f'data:{mime};base64,' + base64.b64encode(path.read_bytes()).decode()


def main(out='index.html'):
    tmpl = (ROOT / 'src/template.html').read_text(encoding='utf-8')
    articles = json.loads((ROOT / 'data/articles.json').read_text(encoding='utf-8'))

    missing = []
    def img(m):
        p = ROOT / 'assets/img' / m.group(1)
        if not p.exists():
            missing.append(m.group(1)); return ''
        return data_uri(p)
    for a in articles:
        a['html'] = re.sub(r'\{\{img:([^}]+)\}\}', img, a['html'])
    used = set(re.findall(r'\{\{img:([^}]+)\}\}', (ROOT / 'data/articles.json').read_text(encoding='utf-8')))
    unused = sorted(p.name for p in (ROOT / 'assets/img').iterdir() if p.name not in used)
    if unused:
        print(f'※ どの記事にも使われていない画像: {unused}')
    if missing:
        sys.exit(f'画像が見つかりません: {missing}')

    ids = [a['id'] for a in articles]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        sys.exit(f'記事IDが重複しています: {dup}')

    js = json.dumps(articles, ensure_ascii=False).replace('</script', '<\\/script')
    html = tmpl.replace('/*ARTICLES*/', js, 1).replace('{{LOGO}}', data_uri(ROOT / 'assets/logo.jpg'))
    (ROOT / out).write_text(html, encoding='utf-8')
    print(f'{out}: {len(articles)}記事, {len(html) / 1e6:.2f}MB')


if __name__ == '__main__':
    main(*sys.argv[1:])
