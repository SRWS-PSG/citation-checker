# citeguard

学術参考文献を Crossref・PubMed・arXiv・JaLC で照合し、**未発見**・**撤回**だけでなく、**誤引用の可能性が高い書誌**も拾い上げる reference checker です。CLI に加えて、Vercel に配置できる Web UI / API を含みます。DOI が Crossref 以外の登録機関に属する場合も自動でフォールバック解決します。

```bash
pip install citeguard
```

## できること

- 1行1書誌のテキスト、または BibTeX をそのまま入力できる
- DOI、Crossref 書誌検索、PubMed、arXiv、JaLC を横断して候補を集める
- 厳格一致した書誌は `found`、怪しい一致は `likely_wrong`、見つからない書誌は `not_found` として分類する
- Crossref の更新通知から `retraction` / `withdrawal` / `removal` / `partial_retraction` を検出する
- URL主体のウェブサイト参照やソフトウェア参照は `website` として学術DB検索をスキップする
- Markdown レポートを stdout またはファイルに出力できる

## インストール

### PyPI

```bash
pip install citeguard
```

### 開発用セットアップ

```bash
git clone https://github.com/SRWS-PSG/citation-checker.git
cd citation-checker
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

`.env` では `CONTACT_EMAIL` を設定できます。CLI では `--email`、Web API ではリクエストごとの `email` でも指定できます。

## クイックスタート

```bash
# テキストファイルを検証
citeguard --input-file input/references.txt

# レポートを保存
citeguard --input-file input/references.txt --out outputs/report.md

# BibTeX もそのまま渡せる
citeguard --input-file input/test_sample.bib

# インラインテキスト
citeguard --text "Smith J. 2019. Some Title. J Example. DOI: 10.1234/abcd"

# stdin
cat input/references.txt | citeguard

# python -m でも実行可能
python -m refaudit --input-file input/references.txt
```

## 判定ステータス

- `found`: 十分な一致があり、通常の照合結果として採用された
- `likely_wrong`: 近い候補は見つかったが、タイトル・著者・掲載誌・ページなどにズレがあり、誤引用の可能性が高い
- `not_found`: 候補が見つからない、または DOI を解決できない
- `website`: ウェブサイト/ソフトウェア参照と判定され、学術DB検索を行わない

`likely_wrong` はこのブランチで強化した中心機能です。単なる `no_match` ではなく、**最有力候補、DOI、項目ごとの差分、修正候補**を返します。

## CLI

### 主なオプション

| オプション | 説明 |
|---|---|
| `--input-file PATH` | 参考文献ファイル。プレーンテキストまたは BibTeX を自動判別 |
| `--text TEXT` | インライン参考文献テキスト |
| `--out PATH` | Markdown レポート出力先。省略時は stdout |
| `--all` | 正常な書誌も含めた全件レポートを出力 |
| `--debug` | 候補不採用時の候補情報を多めに出す |
| `--email EMAIL` | Crossref / PubMed 向けの連絡先メールアドレス |
| `--version` | バージョン表示 |

入力は `--text` と `--input-file` が排他です。どちらも指定しない場合は stdin を読みます。

## 入力形式

### プレーンテキスト

- 1行 = 1書誌
- 行頭の `[1]`、`1.`、`1)` などは自動で除去
- DOI を含む場合は DOI 解決を優先
- `arXiv:2307.06464` や `2307.06464` のような arXiv ID も抽出
- 日本語文献や `・` 区切り著者にも対応
- URL主体の行やソフトウェア参照は `website` としてスキップ

### BibTeX

- `@article`、`@book`、`@inproceedings` など主要エントリを自動検出
- `author`、`title`、`year`、`doi`、`eprint` を使って照合
- 特別なフラグは不要

```bash
citeguard --input-file references.bib
```

## 検索と判定の流れ

1. DOI があれば Multi-RA で解決する
2. arXiv ID があれば arXiv API を確認する
3. Crossref `query.bibliographic` で候補を集める
4. PubMed で全文引用・タイトル検索を行う
5. 和文タイトルなら JaLC を検索する
6. arXiv タイトル/著者検索も候補源として使う
7. 候補を共通スコアリングで評価する

判定は2段階です。

- `verification`: タイトル・著者・年・掲載先・巻号ページの一致を厳しめに判定し、`found` を決める
- `correction`: `found` に届かなかった候補を再評価し、誤引用らしいものを `likely_wrong` として返す

このため、以前は `no_match` に落ちていたケースでも、近い候補があれば修正候補付きで報告されます。

## 撤回判定

- DOI が得られた場合、Crossref `filter=updates:{DOI},is-update:true` で更新通知を取得します
- `update-to[].type` が `retraction` / `withdrawal` / `removal` / `partial_retraction` なら撤回系として扱います
- `update-to[].source` には `publisher` や `retraction-watch` が入ることがあります

## 出力

通常出力は「問題があった書誌だけ」です。`--all` を付けると正常な書誌も含めたフルレポートになります。

### 出力される主なセクション

- `Likely Wrong Citation`
- `未発見`
- `撤回・撤回相当（Crossref 更新通知）`
- `出版年注意`
- `ウェブサイト/ソフトウェア参照（--all 時）`

### 出力例

```md
# Reference Audit Report

対象：貼り付けテキストのうち **問題があった書誌**（未発見／誤引用候補／撤回系）だけを列挙しています。

## ⚠️ Likely Wrong Citation

- 入力: `Barteit S, Kyaw BM, Muller A, et al. The Effectiveness of Digital Game-Based Learning ... JMIR Serious Games 2021; 9(3): e29080.`
- 最有力候補: **Augmented, mixed, and virtual reality-based head-mounted devices for medical education: systematic review**
- DOI: `10.2196/29080`
- ⚠ 要確認 (1件):
  - 📄 タイトル: "The Effectiveness of Digital Game-Based Learning ..." → Crossref では "Augmented, mixed, and virtual reality-based head-mounted devices for medical education: systematic review"
- ✓ 一致 (4件): 👤 著者, 📅 出版年, 📚 掲載先, 📖 巻号・ページ
- 注記: candidate_mismatch

### 修正候補

- **Augmented, mixed, and virtual reality-based head-mounted devices for medical education: systematic review**
- DOI: `10.2196/29080`
- 比較: title ~ / authors ok / year ok / venue ok / pages ok
- 書誌: JMIR Serious Games / 2021
```

## Web UI / API

`public/` に静的フロントエンド、`api/check.py` に Vercel Python Serverless Function を含みます。ブラウザから1件ずつ参考文献を貼り付けて確認できます。

### Web でのメールアドレスの扱い

- チェック実行時にメールアドレス入力が必須です
- 用途は Crossref / PubMed の etiquette 用 `User-Agent` / `email` パラメータのみです
- サーバー側では保存しません
- ブラウザにも既定では保存しません
- `このブラウザにメールアドレスを保存` を有効にした場合のみ `localStorage` に保存します

### API リクエスト仕様

`POST /api/check`

```json
{
  "ref": "reference text",
  "email": "you@example.com"
}
```

- `ref` は必須、2000文字以内
- `email` は必須、形式チェックあり
- 応答は `{"ok": true, "result": ...}` 形式で、`result` は `MatchResult` 相当の JSON を返します

### Vercel デプロイ

公開インスタンス: **https://citation-checker-three.vercel.app**

```bash
npm install -g vercel
vercel
vercel --prod
```

Framework Preset は `Other` を使い、`vercel.json` をそのまま利用します。ローカル確認は `vercel dev` です。

## API 利用時の作法

### Crossref

- `User-Agent` に mailto 付き識別子を設定
- レート目安は 50 req/s。既定では礼儀的に待機を入れる
- `select=` を使って返却項目を絞る

### PubMed

- `tool` / `email` を付与
- タイトル検索と citation matcher を候補源として使う

### arXiv

- `export.arxiv.org/api/query` を使う
- 直接ID照合を優先し、必要に応じてタイトル/著者検索も行う

### Multi-RA DOI 解決

- `doira.org` で Registration Agency を判定
- Crossref / DataCite / JaLC / doi.org content negotiation を切り替える

## GitHub Actions

### `ci.yml`

- `ruff check .`
- テスト実行

### `run-pipeline.yml`

1. Secrets に `CONTACT_EMAIL` を設定
2. `input/references.txt` を更新して push するか、手動実行する
3. `outputs/report.md` を生成してコミットする

### `publish.yml`

- `v*` タグ push で配布フローを実行

## 開発

```bash
pip install -e ".[dev]"
pytest
ruff check .
```

誤引用検出まわりの回帰テストは `tests/test_miscitation_detection.py` にあります。

## 資金源

本プロジェクトは JSPS 科研費 JP25K13585（基盤研究(C)「大規模言語モデルが加速するエビデンスの統合」、研究代表者：片岡 裕貴、2025〜2027年度）の助成を受けています。

---

このリポジトリは AGENTS.md の設計方針に沿って実装されています。
