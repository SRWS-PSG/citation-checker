# ref-audit-crossref

貼り付けた参考文献テキストを行ごとに処理し、存在しない引用や撤回（Retraction/Withdrawal/Removal/Partial Retraction）が見つかったものだけを `outputs/report.md` にまとめて返します。CLI と GitHub Actions の両方で同じ処理が回ります。

## 0) この設計の要点（Crossref + PubMed による判定）
- 存在確認: `/works?query.bibliographic=` に "1行＝1書誌文字列" を投げて最も近い候補を取得。
- 撤回確認: 候補 DOI に対し `filter=updates:{DOI},is-update:true` で"更新レコード"を検索し、`update-to[].type` が `retraction` / `withdrawal` / `removal` / `partial_retraction` の場合に撤回系と判定。
- Crossrefの作法: `User-Agent` に mailto を含める。負荷を控えめに（50 req/s 目安）。`select=` で軽量化。
- **PubMed フォールバック**: Crossref で候補が見つからない場合、タイトル文字列を抽出して PubMed の E-utilities（ESearch + ESummary/EFetch）で完全一致検索を試行。PMID と DOI を取得できた場合は Crossref の撤回判定も実施。

## 1) セットアップ（ローカル）
```bash
python -m venv .venv && . .venv/bin/activate
pip install -e .
cp .env.example .env   # CONTACT_EMAIL を編集
python -m refaudit.main --text "$(cat input/references.txt)" --out outputs/report.md
```

## 2) 入力形式
- 1行＝1書誌。行頭の `[1]` や `1.` は自動で剥がします。
- 行内に DOI が含まれていればそれを優先。なければ Crossref の `query.bibliographic` で候補を引き当てます。
- Crossref で候補が見つからない場合、タイトル文字列を推定して PubMed API で検索（完全一致）します。

## 3) 撤回判定
- 候補 DOI に対して `filter=updates:{DOI},is-update:true` で更新レコード（撤回通知など）を取得。
- `update-to[].type` が `retraction/withdrawal/removal/partial_retraction` のものを問題扱いにします。
- 2025年以降、Retraction Watch 統合により `update-to[].source` に `retraction-watch` が入る場合があります。

## 4) APIの作法
### Crossref REST API
- `User-Agent` に mailto 付き識別子を入れてください（例: `ref-audit/0.1 (mailto:you@example.com)`）。
- レートの目安は 50 req/s（public/polite）。本ツールは礼儀的に 0.2 秒スリープを入れています。
- 返却項目は `select` で絞ると軽量です。

### PubMed E-utilities API
- NCBI の E-utilities API を利用して、タイトル完全一致検索を実行します。
- `tool` パラメータと `email` パラメータを必須で付与（NCBI のエチケット要件）。
- ESearch で PMID を検索 → ESummary/EFetch で DOI とタイトルを取得。
- レート制限は 0.2 秒のポーズで対応（NCBI は 3 req/s を推奨）。
- Crossref で候補がない場合のフォールバックとして機能します。

## 5) GitHub Actions（自動で Markdown を返す）
1. リポジトリの Secrets に `CONTACT_EMAIL` を設定。
2. `input/references.txt` をコミットするとワークフローが走り `outputs/report.md` を生成・コミットします。
3. 手動実行（workflow_dispatch）も可能です。

## 6) 使い方サンプル
`input/references.txt`（例）

```
[1] Smith J., Doe A. 2019. Title of paper... Journal...
[2] Doe A. 2011. Another title... Journal... DOI: 10.1234/abcd.5678
```

実行：

```bash
python -m refaudit.main --text "$(cat input/references.txt)" --out outputs/report.md
```

出力（例／抜粋）：

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

## 7) 発展アイデア（任意）
- タイトル類似度や年差でのスコア閾値を追加して厳密化。
- 出力拡張（Retraction Watch 詳細の突き合わせ）。
- レート管理（`rows`・`select`・カーソル利用）。

---

このリポジトリは AGENTS.md の設計方針に沿って実装されています。必要に応じて `RETRACTION_TYPES` を調整してください。

