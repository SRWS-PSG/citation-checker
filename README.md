# citeguard

学術参考文献を Crossref・PubMed・arXiv の 3 つの API で照合し、**存在しない引用**や**撤回（Retraction / Withdrawal / Removal）された論文**を検出するツールです。CLI に加えて、Vercel へ配置できる Web UI も含みます。DOI が Crossref 以外の登録機関（DataCite・JaLC 等）に属する場合も自動でフォールバック解決します。

```bash
pip install citeguard
```

## インストール

### PyPI（推奨）
```bash
pip install citeguard
```

### 開発用セットアップ
```bash
git clone https://github.com/SRWS-PSG/citation-checker.git
cd citation-checker
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # CONTACT_EMAIL を編集
```

## Web UI

`public/` に静的フロントエンド、`api/check.py` に Vercel Python Serverless Function を含みます。ブラウザから参考文献を貼り付けて逐次チェックできます。

### Web でのメールアドレスの扱い

- チェック実行時に、Crossref / PubMed の etiquette 用としてメールアドレス入力が必須です。
- メールアドレスは API リクエストごとに送信され、`User-Agent` / `email` パラメータのためにのみ使用します。
- サーバー側で保存しません。
- 既定ではブラウザにも保存しません。
- `このブラウザにメールアドレスを保存` を ON にした場合のみ、ブラウザの `localStorage` に保存します。

### Vercel デプロイ

公開インスタンス: **https://citation-checker-three.vercel.app**

```bash
npm install -g vercel
vercel
vercel --prod
```

Vercel では Framework Preset を `Other` とし、`vercel.json` をそのまま使います。Hobby（無料）プランで運用可能です（Serverless Function 実行上限 10 秒）。ローカル確認は `vercel dev` です。

## CLI

```bash
# ファイルを指定して実行（結果は stdout）
citeguard --input-file input/references.txt

# レポートをファイルに出力
citeguard --input-file input/references.txt --out outputs/report.md

# インラインテキスト
citeguard --text "Smith J. 2019. Some Title. J Example. DOI: 10.1234/abcd"

# パイプ（stdin）
cat input/references.txt | citeguard

# python -m でも実行可能
python -m refaudit --input-file input/references.txt
```

### CLI オプション一覧

| オプション | 説明 |
|---|---|
| `--input-file PATH` | 参考文献ファイル（1行1書誌） |
| `--text TEXT` | インライン参考文献テキスト |
| `--out PATH` | Markdown レポート出力先（省略時は stdout） |
| `--all` | 問題のない書誌も含めた全件レポート |
| `--debug` | 未マッチ書誌の Crossref 候補を表示 |
| `--email EMAIL` | API 礼儀用メールアドレス（`CONTACT_EMAIL` 環境変数/.env でも可） |
| `--version` | バージョン表示 |

入力は `--text`・`--input-file`・stdin の排他です。いずれも指定しない場合は stdin から読み取ります。

## 入力形式

- 1行＝1書誌。行頭の `[1]` や `1.` は自動で剥がします。
- 行内に DOI が含まれていればそれを優先使用します。
- URL のみ・ソフトウェア名のみなどウェブサイト参照は自動判別し、API 検索をスキップします。

## 検索・判定フロー

書誌ごとに以下のフォールバックチェーンで照合します。

1. **DOI 直接解決** — 行内に DOI があれば Multi-RA 解決（Crossref → DataCite → JaLC → doi.org content negotiation）
2. **arXiv ID 直接ルックアップ** — arXiv ID（`2307.06464` / `hep-th/9901001` 形式）があれば arXiv API
3. **Crossref 書誌検索** — `query.bibliographic` で候補を取得し、タイトル・著者・年で照合
4. **PubMed 検索** — タイトル文字列を推定して ESearch + ESummary で完全一致検索
5. **arXiv タイトル/著者検索** — 上記で未ヒットの場合、arXiv ATOM API で検索

### 撤回判定

- 候補 DOI に対して Crossref `filter=updates:{DOI},is-update:true` で更新レコードを取得。
- `update-to[].type` が `retraction` / `withdrawal` / `removal` / `partial_retraction` のいずれかなら撤回系と判定。
- Retraction Watch 統合により `update-to[].source` に `retraction-watch` が入る場合があります。

## API の作法

### Crossref REST API
- `User-Agent` に mailto 付き識別子を設定（例: `citeguard/0.1 (mailto:you@example.com)`）。
- レートの目安は 50 req/s（public/polite）。本ツールは 0.2 秒スリープを挿入。
- `select=` で返却項目を絞り軽量化。

### PubMed E-utilities API
- `tool` / `email` パラメータを付与（NCBI エチケット要件）。
- ESearch → ESummary/EFetch の 2 段階で PMID・DOI・タイトルを取得。
- 0.2 秒ポーズ（NCBI 推奨: 3 req/s）。

### arXiv ATOM API
- `export.arxiv.org/api/query` を使用。
- ID 直接ルックアップが最も信頼性が高い。タイトル/著者検索もサポート。
- レート制限: 3 秒に 1 リクエスト推奨。

### Multi-RA DOI 解決
- `doira.org` で DOI の登録機関（RA）を判定。
- RA に応じて Crossref API / DataCite API / JaLC API を使い分け。
- いずれでも解決できない場合は `doi.org` の content negotiation（CSL-JSON）でフォールバック。

## GitHub Actions

### 参照チェック（`run-pipeline.yml`）
1. リポジトリの Secrets に `CONTACT_EMAIL` を設定。
2. `input/references.txt` をコミット（または push）するとワークフローが走り、`outputs/report.md` を生成・コミット。
3. 手動実行（workflow_dispatch）も可能（`path` パラメータでファイル指定）。

### PyPI 公開（`publish.yml`）
- `v*` タグの push で起動。
- Build → テストインストール → TestPyPI → PyPI の順に実行（Trusted Publisher）。

## 出力例

```md
# Reference Audit Report

対象：貼り付けテキストのうち **問題があった書誌**（未発見／撤回系）だけを列挙しています。

## 未発見
- 入力: `Smith J., Doe A. 2019. Title of paper... Journal...`
- 理由: Crossref REST `/works?query.bibliographic=` で候補なし

## 撤回・撤回相当（Crossref 更新通知）
- 入力: `Doe A. 2011. Another title... Journal... DOI: 10.1234/abcd.5678`
- マッチ: **Another title...**
- DOI: `10.1234/abcd.5678`

### 参照された更新（通知）
- 種別: **retraction**, 通知DOI: `10.9999/notice.2020.1`, source: `retraction-watch`, date: `2020-05-01T00:00:00Z`
```

## 発展アイデア

- タイトル類似度や年差でのスコア閾値を追加して厳密化。
- 出力拡張（Retraction Watch 詳細の突き合わせ）。
- レート管理（`rows`・`select`・カーソル利用）。

## 資金源

本プロジェクトは JSPS 科研費 JP25K13585（基盤研究(C)「大規模言語モデルが加速するエビデンスの統合」、研究代表者：片岡 裕貴、2025〜2027年度）の助成を受けています。

---

このリポジトリは AGENTS.md の設計方針に沿って実装されています。
