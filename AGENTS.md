最高です。その要件（**テキストをコピペ → Crossref検索 → 問題のある書誌のみをMarkdownで返す**）にぴったりの、**最小構成だけど拡張しやすいGitHubレポジトリ**の作り方を、ゼロから具体的にまとめました。
以下の手順どおりにファイルを置けば、**CLI でも GitHub Actions でも**同じ処理が回ります。Devin にはこの README を渡せば、そのままセットアップ〜実行が可能です。

---

## 0) この設計の要点（Crossrefの仕様に沿った判定）

* **存在確認**：`/works?query.bibliographic=` で “1行＝1書誌文字列” を照合。Crossref側は**引用テキストまるごと**を受け付け、最も近い候補を返してくれます（「まず当てる」にはこれが最良）。([Crossref community forum][1])
* **撤回確認**：候補の DOI が取れたら、**その DOI を“更新（editorial updates）で参照しているレコード”**を検索します（`filter=updates:{DOI},is-update:true`）。返ってきた更新レコードの `update-to[].type` が **`retraction` / `withdrawal` / `removal` / `partial_retraction`** なら **撤回系**と判定します。2025年1月以降、**Retraction Watch データが Crossref REST に統合**され、`update-to[].source` に `publisher` / `retraction-watch` が入ります。([rOpenSci][2])
* **Crossrefの作法**：**`User-Agent` に連絡先（mailto）**を入れ、**負荷を控えめ**に（ポリテ／パブリック両プールで 50 req/s 制限）。必要項目だけ返す **`select=`** も使うと応答が軽くなります。([www.crossref.org][3])
* **補足**：APIには `filter=update-type:retraction` もあります（どの更新レコードが撤回かの抽出）。ただし「**あるDOIが撤回されたか**」を調べるには **`updates:{DOI}` と組み合わせて**該当更新を拾うのが確実です。([Crossref community forum][4])

---

## 1) レポジトリ構成（Python 3.11+）

```
ref-audit-crossref/
├─ README.md
├─ LICENSE
├─ pyproject.toml              # 依存: requests, python-dotenv
├─ .env.example                # CONTACT_EMAIL=you@example.com
├─ src/
│   └─ refaudit/
│       ├─ __init__.py
│       ├─ crossref.py         # Crossref APIラッパ
│       ├─ parser.py           # 行分割 & DOI抽出
│       ├─ report.py           # Markdown生成
│       └─ main.py             # CLIエントリ
├─ tests/
│   └─ test_smoke.py
├─ input/
│   └─ references.txt          # コピペ用（コミット時にActionsが読む）
├─ outputs/
│   └─ (report.md が出力される)
└─ .github/
    └─ workflows/
        ├─ ci.yml              # Lint/テスト
        └─ run-pipeline.yml    # 手動 or pushで report.md 生成
```

---

## 2) 依存パッケージ（`pyproject.toml`）

```toml
[project]
name = "ref-audit-crossref"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "requests>=2.32.0",
  "python-dotenv>=1.0.1"
]

[tool.ruff]
line-length = 100
```

---

## 3) 環境変数（`.env.example`）

```dotenv
# Crossrefの作法に従い User-Agent に mailto を含めます（推奨）
CONTACT_EMAIL=you@example.com
```

> Crossrefは**適切なUser-Agent（mailtoを含む）**を推奨し、負荷・トラブル時の連絡にも使います。([www.crossref.org][3])

---

## 4) 実装

### `src/refaudit/parser.py`

```python
import re

DOI_REGEX = re.compile(r"(10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)

def split_references(pasted_text: str) -> list[str]:
    # シンプル：改行ごとに1書誌。空行と番号プレフィックスを除去。
    refs = []
    for line in (pasted_text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        # 例: [1] , 1) , 1. などを剥がす
        line = re.sub(r"^\s*(\[\d+\]|\d+[\.\)]\s*)", "", line)
        refs.append(line)
    return refs

def extract_doi(text: str) -> str | None:
    m = DOI_REGEX.search(text)
    if not m:
        return None
    doi = m.group(1).rstrip(").,;")
    return doi
```

### `src/refaudit/crossref.py`

```python
from __future__ import annotations
import os, time, urllib.parse, requests
from dataclasses import dataclass
from dotenv import load_dotenv

API = "https://api.crossref.org/works"
RETRACTION_TYPES = {"retraction", "withdrawal", "removal", "partial_retraction"}  # Crossmarkの種類に基づく代表値
# 参考: update-type:retraction フィルタ, Retraction Watch 統合の案内。 
# https://api.crossref.org/works?filter=update-type:retraction など。 

load_dotenv()
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "you@example.com")
UA = {"User-Agent": f"ref-audit/0.1 (mailto:{CONTACT_EMAIL})"}  # Crossref推奨。50req/s以下を推奨。

@dataclass
class MatchResult:
    input_text: str
    doi: str | None
    title: str | None
    found: bool
    retracted: bool
    retraction_details: list[dict]  # retraction notice DOI, source, date, etc.

class CrossrefClient:
    def __init__(self, pause_sec: float = 0.2):
        self.session = requests.Session()
        self.session.headers.update(UA)
        self.pause_sec = pause_sec

    def _get(self, url: str, params: dict | None = None):
        r = self.session.get(url, params=params, timeout=30)
        r.raise_for_status()
        time.sleep(self.pause_sec)  # 礼儀的スロットリング（ドキュメント上限50req/s）。 
        return r.json()

    def search_bibliographic(self, ref: str) -> dict | None:
        # rowsを絞り、selectで軽量化（scoreはselect非対応のため省略）。
        params = {
            "query.bibliographic": ref,
            "rows": 3,
            "select": "DOI,title,issued,type",
        }
        js = self._get(API, params)
        items = js.get("message", {}).get("items", [])
        return items[0] if items else None

    def get_work(self, doi: str) -> dict | None:
        url = f"{API}/{urllib.parse.quote(doi)}"
        js = self._get(url, params={"select": "DOI,title,issued,type,update-to,relation"})
        return js.get("message", None)

    def find_updates_for(self, doi: str) -> list[dict]:
        # このDOIを“更新対象にしている”レコード（＝撤回通知など）を取得
        # update-typeは後段で絞り込む（Crossrefは複数のupdate種別を持つ）
        params = {
            "filter": f"updates:{doi},is-update:true",
            "rows": 1000
        }
        js = self._get(API, params)
        return js.get("message", {}).get("items", [])

    def is_retracted(self, doi: str) -> tuple[bool, list[dict]]:
        notices = self.find_updates_for(doi)
        hits = []
        for n in notices:
            # retraction系かどうかは、update-to[].type を確認
            for ut in n.get("update-to", []):
                ut_type = (ut.get("type") or "").lower()
                if ut_type in RETRACTION_TYPES:
                    hits.append({
                        "notice_doi": n.get("DOI"),
                        "update_type": ut.get("type"),
                        "source": ut.get("source"),      # 'publisher' or 'retraction-watch'
                        "updated": ut.get("updated", {}),
                        "label": ut.get("label"),
                    })
        return (len(hits) > 0, hits)

    def check_one(self, input_text: str) -> MatchResult:
        # 1) DOI明記なら直でworks/{doi}、なければquery.bibliographic
        from .parser import extract_doi
        doi = extract_doi(input_text)
        work = self.get_work(doi) if doi else self.search_bibliographic(input_text)

        if not work:
            return MatchResult(input_text, None, None, found=False, retracted=False, retraction_details=[])

        doi = work.get("DOI")
        title = (work.get("title") or [None])[0]
        # 2) 撤回チェック（'updates:DOI' で retraction notice を探索）
        retracted, details = self.is_retracted(doi)
        return MatchResult(input_text, doi, title, found=True, retracted=retracted, retraction_details=details)
```

> `query.bibliographic` は**引用文字列まるごと**を入力にとり、最も近いメタデータを返す設計です。まずこれで DOI を当て、**撤回は `updates:{DOI}`** を見るのが堅実です。([Crossref community forum][1])
> `update-to[].source` に `retraction-watch` が混ざるのは **2025/01/29の統合**によるものです。([www.crossref.org][5])

### `src/refaudit/report.py`

```python
from __future__ import annotations
from typing import Iterable
from .crossref import MatchResult

def make_markdown_bad_only(results: Iterable[MatchResult]) -> str:
    bad = [r for r in results if (not r.found) or r.retracted]
    lines = ["# Reference Audit Report",
             "",
             "対象：貼り付けテキストのうち **問題があった書誌**（未発見／撤回系）だけを列挙しています。",
             ""]
    if not bad:
        lines.append("_問題のある書誌は見つかりませんでした。_")
        return "\n".join(lines)

    for r in bad:
        if not r.found:
            lines += [
              "## ❌ 未発見",
              "",
              f"- 入力: `{r.input_text}`",
              "- 理由: Crossref REST `/works?query.bibliographic=` で候補なし",
              ""
            ]
            continue

        # retracted
        lines += [
          "## 🚩 撤回・撤回相当（Crossref 更新通知）",
          "",
          f"- 入力: `{r.input_text}`",
          f"- マッチ: **{r.title or '(no title)'}**",
          f"- DOI: `{r.doi}`",
          "",
          "### 参照された更新（通知）",
          ""
        ]
        for d in r.retraction_details:
            when = d.get("updated", {}).get("date-time") or "N/A"
            src = d.get("source") or "N/A"
            lines.append(f"- 種別: **{d.get('update_type')}**, 通知DOI: `{d.get('notice_doi')}`, "
                         f"source: `{src}`, date: `{when}`")
        lines.append("")
    return "\n".join(lines)
```

### `src/refaudit/main.py`（CLI）

```python
import argparse, sys, pathlib
from .parser import split_references
from .crossref import CrossrefClient
from .report import make_markdown_bad_only

def run(text: str, out_path: pathlib.Path):
    client = CrossrefClient()
    refs = split_references(text)
    results = [client.check_one(line) for line in refs]
    md = make_markdown_bad_only(results)
    out_path.write_text(md, encoding="utf-8")
    return 0

def main():
    p = argparse.ArgumentParser(description="Audit references via Crossref and output bad ones as Markdown.")
    p.add_argument("--text", help="Inline pasted references text. If omitted, read from STDIN.", default=None)
    p.add_argument("--out", help="Path to Markdown report", default="outputs/report.md")
    args = p.parse_args()

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    if args.text is not None:
        text = args.text
    else:
        text = sys.stdin.read()

    return sys.exit(run(text, out))

if __name__ == "__main__":
    main()
```

---

## 5) テスト（`tests/test_smoke.py`）

```python
def test_imports():
    import refaudit.crossref as _  # noqa: F401
    import refaudit.parser as _    # noqa: F401
```

---

## 6) README.md（骨子）

**目的**：貼り付けた参考文献テキストを行ごとに処理し、**存在しない引用**や**撤回（Retraction/Withdrawal/Removal/Partial Retraction）**が見つかったものだけを **`outputs/report.md`** にまとめて返す。

**使い方（ローカル）**

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e .
cp .env.example .env   # CONTACT_EMAIL を編集
python -m refaudit.main --text "$(cat input/references.txt)" --out outputs/report.md
```

**入力形式**：**1行＝1書誌**。行頭の `[1]` や `1.` は自動で剥がします。行内に DOI が含まれていればそれを優先。なければ Crossref の **`query.bibliographic`** で候補を引き当てます。([Crossref community forum][1])

**撤回判定**：候補 DOI に対して **`filter=updates:{DOI},is-update:true`** で更新レコード（撤回通知など）を取得し、`update-to[].type` が **`retraction/withdrawal/removal/partial_retraction`** のものを問題扱いにします。**Retraction Watch 統合により** `update-to[].source` に `retraction-watch` 由来が入る場合があります。([rOpenSci][2])

**APIの作法**：

* `User-Agent` に **mailto付き識別子**を入れてください（例：`ref-audit/0.1 (mailto:you@example.com)`）。([www.crossref.org][3])
* レートの目安は **50 req/s**（public/polite）。本ツールは礼儀的に **0.2秒スリープ**を入れています。([www.crossref.org][6])
* 返却項目は **`select`** で絞ると軽量です。([Crossref community forum][7])

**判定の注意**：Crossref は出版社メタデータが基です。古い冊子体や未登録誌は**未発見**になることがあります。撤回は Crossmark/Retraction Watch 経由で記録されますが、**出版社の登録状況**に依存します。([www.crossref.org][8])

---

## 7) GitHub Actions（自動で Markdown を返す）

### `.github/workflows/ci.yml`

```yaml
name: CI
on:
  pull_request:
  push:
    branches: [ main ]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with: { python-version: '3.11' }
    - run: python -m pip install -e . ruff
    - run: ruff check .
```

### `.github/workflows/run-pipeline.yml`

```yaml
name: Run Ref Audit
on:
  workflow_dispatch:
  push:
    paths:
      - "input/references.txt"
jobs:
  run:
    runs-on: ubuntu-latest
    permissions:
      contents: write   # report.md をコミットするため
    steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with: { python-version: '3.11' }
    - run: python -m pip install -e .
    - name: Create .env
      run: |
        echo "CONTACT_EMAIL=${{ secrets.CONTACT_EMAIL }}" > .env
    - name: Run audit
      run: |
        python -m refaudit.main --text "$(cat input/references.txt)" --out outputs/report.md
        echo "=== outputs/report.md ==="
        sed -n '1,120p' outputs/report.md
    - name: Commit report
      uses: stefanzweifel/git-auto-commit-action@v5
      with:
        commit_message: "chore: update report.md"
        file_pattern: outputs/report.md
```

> `secrets.CONTACT_EMAIL` にメールアドレスを設定してください。Crossrefの**User-Agent作法**に対応します。([www.crossref.org][3])

---

## 8) Devin に渡す最短タスクリスト

1. 新規レポジトリ `ref-audit-crossref` を作成し、上記ツリーとファイルを配置。
2. `pyproject.toml` で依存をインストール、`input/references.txt` を用意。
3. `.env` を作って `CONTACT_EMAIL` を設定。
4. `python -m refaudit.main --text "$(cat input/references.txt)" --out outputs/report.md` を実行。
5. 出力された `outputs/report.md` を確認し、必要なら `RETRACTION_TYPES` を調整。
6. GitHub Actions の `secrets.CONTACT_EMAIL` を設定し、`run-pipeline.yml` を手動起動または `input/references.txt` を更新して自動実行。

---

## 9) 使い方のサンプル

`input/references.txt`（例）

```
[1] Smith J., Doe A. 2019. Title of paper... Journal...
[2] Doe A. 2011. Another title... Journal... DOI: 10.1234/abcd.5678
```

実行：

```bash
python -m refaudit.main --text "$(cat input/references.txt)" --out outputs/report.md
```

`outputs/report.md`（例／抜粋）

```md
# Reference Audit Report

対象：貼り付けテキストのうち **問題があった書誌**（未発見／撤回系）だけを列挙しています。

## ❌ 未発見
- 入力: `Smith J., Doe A. 2019. Title of paper... Journal...`
- 理由: Crossref REST `/works?query.bibliographic=` で候補なし

## 🚩 撤回・撤回相当（Crossref 更新通知）
- 入力: `Doe A. 2011. Another title... Journal... DOI: 10.1234/abcd.5678`
- マッチ: **Another title...**
- DOI: `10.1234/abcd.5678`

### 参照された更新（通知）
- 種別: **retraction**, 通知DOI: `10.9999/notice.2020.1`, source: `retraction-watch`, date: `2020-05-01T00:00:00Z`
```

---

## 10) 発展アイデア（任意）

* **スコア基準**：`query.bibliographic` は “ゆるく当てる”のに強いですが、より厳密にしたければ**タイトル類似度**や年差での閾値を追加（ただし Crossref 自身も「細かいフィールド別検索より bibliographic 一発が速くて精度良い」旨を案内しています）。([www.crossref.org][9])
* **出力拡張**：撤回理由や詳細が必要なら `update-to[].record-id` を使って Retraction Watch CSV 側のレコードと突き合わせ（Crossref Blog/Docsに記載）。([www.crossref.org][5])
* **レート管理**：大量処理時は Cursor や `rows` の工夫、選択フィールドの最適化で軽量化。ポリテ/パブリックは 50 req/s 目安。([www.crossref.org][6])

---

## 参考（仕様リンク）

* Crossref REST 概要／Tips（**User-Agent推奨・効率化**、レートの目安）([www.crossref.org][3])
* `query.bibliographic` の役割（**引用文字列の突合**）([Crossref community forum][1])
* **Retraction Watch のREST統合（2025-01-29）**・`update-to[].source` などの仕様説明と例([www.crossref.org][5])
* `filter=update-type:retraction`（更新レコードの抽出）([Crossref community forum][4])
* `filter=updates:{DOI}`（**特定DOIを更新する通知の列挙**）([rOpenSci][2])
* Crossmark/更新の扱い（ベストプラクティス・スキーマ周辺）([www.crossref.org][10])

---

このままコピペでレポジトリを作れます。もし「Actions じゃなくて**CLI のみ**で良い」「**Docker 化**したい」「**撤回以外（Expression of Concern など）も警告**したい」など要望があれば、上記をベースにすぐ対応できる形で追記します。

[1]: https://community.crossref.org/t/rest-api-works-query-bibliographic/3203 "REST API - works?query.bibliographic - Interfaces for Machines - Crossref community forum"
[2]: https://docs.ropensci.org/rcrossref/articles/crossref_filters.html "Crossref filters • rcrossref"
[3]: https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/?utm_source=chatgpt.com "Tips for using the Crossref REST API"
[4]: https://community.crossref.org/t/help-how-can-i-collect-retractions-marked-by-crossmark/4166?utm_source=chatgpt.com "Help: How can I collect Retractions marked by Crossmark?"
[5]: https://www.crossref.org/blog/retraction-watch-retractions-now-in-the-crossref-api/ "Retraction Watch retractions now in the Crossref API - Crossref"
[6]: https://www.crossref.org/blog/rebalancing-our-rest-api-traffic/?utm_source=chatgpt.com "Blog - Rebalancing our REST API traffic"
[7]: https://community.crossref.org/t/how-can-i-only-return-a-few-metadata-fields-instead-of-all-of-them-when-i-look-up-a-doi/4798?utm_source=chatgpt.com "How can I only return a few metadata fields instead of all of them ..."
[8]: https://www.crossref.org/documentation/register-maintain-records/maintaining-your-metadata/registering-updates/?utm_source=chatgpt.com "Registering updates"
[9]: https://www-crossref-org.pluma.sjfc.edu/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/?utm_source=chatgpt.com "Tips for using the Crossref REST API"
[10]: https://www.crossref.org/documentation/schema-library/markup-guide-metadata-segments/relationships/?utm_source=chatgpt.com "Relationships"
