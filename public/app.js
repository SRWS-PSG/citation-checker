const STORAGE_KEY = "citeguard.contactEmail";

const emailInput = document.getElementById("email");
const rememberEmail = document.getElementById("remember-email");
const referencesInput = document.getElementById("references");
const runButton = document.getElementById("run");
const downloadButton = document.getElementById("download");
const statusText = document.getElementById("status");
const summaryText = document.getElementById("summary");
const resultsEl = document.getElementById("results");
const template = document.getElementById("result-template");

let latestResults = [];

const FIELD_LABEL = {
  title: "📄 タイトル",
  authors: "👤 著者",
  year: "📅 出版年",
  venue: "📚 掲載先",
  pages: "📖 巻号・ページ",
};
const FIELD_ORDER = ["title", "authors", "year", "venue", "pages"];
const ATTENTION_STATES = new Set([
  "mismatch",
  "abbrev",
  "near",
  "missing_input",
  "missing_candidate",
]);

function renderFieldDiffs(diffs) {
  if (!diffs) return [];
  const needs = [];
  const oks = [];
  for (const key of FIELD_ORDER) {
    const d = diffs[key];
    if (!d) continue;
    if (d.state === "ok") {
      oks.push(FIELD_LABEL[key]);
    } else if (ATTENTION_STATES.has(d.state)) {
      needs.push([key, d]);
    }
  }
  const lines = [];
  if (needs.length) {
    lines.push(`⚠ 要確認 (${needs.length}件):`);
    for (const [key, d] of needs) {
      const label = FIELD_LABEL[key];
      const iv = d.input_value || "(なし)";
      const cv = d.candidate_value || "(取得不可)";
      if (d.state === "missing_input" || d.state === "missing_candidate") {
        lines.push(`  • ${label}: 入力=${iv} / Crossref=${cv}`);
      } else {
        lines.push(`  • ${label}: "${iv}" → Crossref では "${cv}"`);
      }
      if (d.reason) lines.push(`      （${d.reason}）`);
    }
  }
  if (oks.length) {
    lines.push(`✓ 一致 (${oks.length}件): ${oks.join(", ")}`);
  }
  return lines;
}

function pickFieldDiffs(result) {
  if (result?.field_diffs) return result.field_diffs;
  if (result?.best_candidate?.field_diffs) return result.best_candidate.field_diffs;
  return null;
}

/* ---------- BibTeX detection & parsing ---------- */

const BIBTEX_ENTRY_RE =
  /@\s*(?:article|book|inproceedings|incollection|conference|phdthesis|mastersthesis|techreport|misc|unpublished|proceedings|inbook|manual|booklet)\s*\{/i;

function detectBibtex(text) {
  return BIBTEX_ENTRY_RE.test(text || "");
}

/**
 * Minimal BibTeX parser — splits text into entry blocks and extracts fields.
 * Handles nested braces in field values.
 */
function parseBibtexEntries(text) {
  const entries = [];
  const entryRe =
    /@\s*(article|book|inproceedings|incollection|conference|phdthesis|mastersthesis|techreport|misc|unpublished|proceedings|inbook|manual|booklet)\s*\{/gi;

  let match;
  while ((match = entryRe.exec(text)) !== null) {
    const startBody = match.index + match[0].length;
    // Walk forward, counting braces to find the matching close
    let depth = 1;
    let pos = startBody;
    while (pos < text.length && depth > 0) {
      if (text[pos] === "{") depth++;
      else if (text[pos] === "}") depth--;
      pos++;
    }
    const body = text.slice(startBody, pos - 1);
    const fields = {};

    // Extract key=value pairs (value delimited by {} or "")
    const fieldRe = /(\w+)\s*=\s*/g;
    let fm;
    while ((fm = fieldRe.exec(body)) !== null) {
      const key = fm[1].toLowerCase();
      let valStart = fm.index + fm[0].length;
      let value = "";

      if (body[valStart] === "{") {
        let d = 1;
        let p = valStart + 1;
        while (p < body.length && d > 0) {
          if (body[p] === "{") d++;
          else if (body[p] === "}") d--;
          p++;
        }
        value = body.slice(valStart + 1, p - 1);
      } else if (body[valStart] === '"') {
        const end = body.indexOf('"', valStart + 1);
        value = end > 0 ? body.slice(valStart + 1, end) : "";
      } else {
        // Bare value (e.g., month = feb)
        const rest = body.slice(valStart);
        const comma = rest.search(/[,}]/);
        value = (comma >= 0 ? rest.slice(0, comma) : rest).trim();
      }
      fields[key] = value.replace(/[{}]/g, "").trim();
    }
    entries.push(fields);
  }
  return entries;
}

function bibtexEntryToText(entry) {
  const parts = [];

  if (entry.author) {
    const names = entry.author.split(/\s+and\s+/i).map((a) => {
      const trimmed = a.trim();
      return trimmed.includes(",") ? trimmed.split(",")[0].trim() : trimmed.split(/\s+/).pop();
    });
    parts.push(names.join(", "));
  }
  if (entry.year) parts.push(entry.year);
  if (entry.title) parts.push(entry.title);
  if (entry.journal) parts.push(entry.journal);
  else if (entry.booktitle) parts.push(entry.booktitle);
  if (entry.doi) parts.push(`DOI: ${entry.doi}`);
  if (entry.eprint && (entry.archiveprefix || "").toLowerCase() === "arxiv") {
    parts.push(`arXiv:${entry.eprint}`);
  }
  return parts.join(". ");
}

function splitBibtexReferences(text) {
  return parseBibtexEntries(text)
    .map(bibtexEntryToText)
    .filter(Boolean);
}

/* ---------- Plain-text splitting ---------- */

function splitPlainReferences(text) {
  const skipLabels = new Set([
    "article",
    "pubmed",
    "pubmed central",
    "google scholar",
    "cas",
    "references",
  ]);

  return (text || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .filter((line) => !skipLabels.has(line.toLowerCase()))
    .map((line) => line.replace(/^\s*(\[\d+\]|\d+[\.)]\s*)/, "").trim());
}

/* ---------- Unified entry point ---------- */

function splitReferences(text) {
  if (detectBibtex(text)) {
    return splitBibtexReferences(text);
  }
  return splitPlainReferences(text);
}

function loadStoredEmail() {
  const saved = window.localStorage.getItem(STORAGE_KEY);
  if (!saved) {
    return;
  }
  emailInput.value = saved;
  rememberEmail.checked = true;
}

function syncStoredEmail() {
  if (rememberEmail.checked) {
    window.localStorage.setItem(STORAGE_KEY, emailInput.value.trim());
    return;
  }
  window.localStorage.removeItem(STORAGE_KEY);
}

function classify(result) {
  if (result.error) {
    return { kind: "error", label: "エラー" };
  }
  if (result.status === "likely_wrong") {
    return { kind: "likely-wrong", label: "誤引用候補" };
  }
  if (result.status === "website") {
    return { kind: "website", label: "ウェブサイト" };
  }
  if (result.status === "not_found") {
    return { kind: "not-found", label: "未発見" };
  }
  if (result.status === "found" && result.note === "year_warning") {
    return { kind: "year-warning", label: "年注意" };
  }
  if (result.is_website) {
    return { kind: "website", label: "ウェブサイト" };
  }
  if (!result.found) {
    return { kind: "not-found", label: "未発見" };
  }
  if (result.retracted) {
    return { kind: "retracted", label: "撤回" };
  }
  if (result.note === "year_warning") {
    return { kind: "year-warning", label: "年注意" };
  }
  return { kind: "ok", label: "正常" };
}

function renderResults(results) {
  resultsEl.innerHTML = "";
  if (!results.length) {
    resultsEl.innerHTML = '<p class="empty">結果はまだありません。</p>';
    return;
  }

  for (const result of results) {
    const node = template.content.cloneNode(true);
    const card = node.querySelector(".result-card");
    const title = node.querySelector(".result-title");
    const badge = node.querySelector(".badge");
    const input = node.querySelector(".result-input");
    const meta = node.querySelector(".result-meta");
    const state = classify(result);

    card.classList.add(state.kind);
    title.textContent = result.title || result.input_text || "Reference";
    badge.textContent = state.label;
    input.textContent = result.input_text || result.ref || "";

    const rows = [];
    if (result.doi) rows.push(`DOI: ${result.doi}`);
    if (result.method) rows.push(`判定経路: ${result.method}`);
    if (result.note && result.note !== "website_reference") rows.push(`注記: ${result.note}`);
    const diffLines = renderFieldDiffs(pickFieldDiffs(result));
    if (diffLines.length) {
      rows.push(...diffLines);
    } else if (result.comparison_summary) {
      rows.push(`比較: ${result.comparison_summary}`);
    }
    if (result.arxiv_id) rows.push(`arXiv ID: ${result.arxiv_id}`);
    if (result.arxiv_doi) rows.push(`出版版DOI: ${result.arxiv_doi}`);
    if (result.journal_ref) rows.push(`Journal ref: ${result.journal_ref}`);
    if (Array.isArray(result.retraction_details)) {
      for (const detail of result.retraction_details) {
        rows.push(`更新通知: ${detail.update_type || "N/A"} / ${detail.notice_doi || "N/A"}`);
      }
    }
    if (Array.isArray(result.suggestions)) {
      for (const item of result.suggestions) {
        rows.push(`提案: ${item}`);
      }
    }
    if (Array.isArray(result.candidates)) {
      for (const candidate of result.candidates) {
        const titleText = candidate.title || "候補";
        const score = typeof candidate.score === "number" ? `score=${candidate.score}` : "";
        const summary = candidate.field_summary ? ` / ${candidate.field_summary}` : "";
        rows.push(`候補: ${titleText}${score ? ` (${score})` : ""}${summary}`);
      }
    }
    if (result.error && result.message) {
      rows.push(`詳細: ${result.message}`);
    }

    if (!rows.length) {
      rows.push("問題は見つかりませんでした。");
    }

    for (const row of rows) {
      const li = document.createElement("li");
      li.textContent = row;
      meta.appendChild(li);
    }

    resultsEl.appendChild(node);
  }
}

function updateSummary(results) {
  const counts = {
    ok: 0,
    "not-found": 0,
    "likely-wrong": 0,
    retracted: 0,
    website: 0,
    "year-warning": 0,
    error: 0,
  };

  for (const result of results) {
    counts[classify(result).kind] += 1;
  }

  summaryText.textContent = `正常 ${counts.ok} / 誤引用候補 ${counts["likely-wrong"]} / 未発見 ${counts["not-found"]} / 撤回 ${counts.retracted} / 年注意 ${counts["year-warning"]} / ウェブサイト ${counts.website} / エラー ${counts.error}`;
}

function escapeInlineCode(value) {
  return String(value || "").replace(/`/g, "\\`");
}

function buildMarkdown(results, inputText) {
  const counts = {
    ok: 0,
    "not-found": 0,
    "likely-wrong": 0,
    retracted: 0,
    website: 0,
    "year-warning": 0,
    error: 0,
  };
  for (const result of results) {
    counts[classify(result).kind] += 1;
  }

  const lines = ["# Reference Audit Report", ""];

  // ## 入力
  lines.push("## 入力", "", "```", String(inputText || "").replace(/```/g, "``\u200b`"), "```", "");

  // ## チェック結果
  lines.push("## チェック結果", "");
  lines.push(
    `- 正常: ${counts.ok}`,
    `- 誤引用候補: ${counts["likely-wrong"]}`,
    `- 未発見: ${counts["not-found"]}`,
    `- 撤回: ${counts.retracted}`,
    `- 年注意: ${counts["year-warning"]}`,
    `- ウェブサイト: ${counts.website}`,
    `- エラー: ${counts.error}`,
    ""
  );
  results.forEach((result, i) => {
    const { label } = classify(result);
    const title = result.title ? ` — ${result.title}` : "";
    const doi = result.doi ? ` (DOI: ${result.doi})` : "";
    lines.push(`${i + 1}. **[${label}]** \`${escapeInlineCode(result.input_text)}\`${title}${doi}`);
  });
  lines.push("");

  // ## 注意すべき候補
  lines.push("## 注意すべき候補", "");
  const bad = results.filter((result) => {
    const state = classify(result).kind;
    return ["likely-wrong", "not-found", "retracted", "year-warning", "error"].includes(state);
  });

  if (!bad.length) {
    lines.push("_問題のある書誌は見つかりませんでした。_");
    return lines.join("\n");
  }

  for (const result of bad) {
    const state = classify(result).kind;
    if (state === "likely-wrong") {
      lines.push("### ⚠️ Likely Wrong Citation", "", `- 入力: \`${escapeInlineCode(result.input_text)}\``);
      if (result.title) lines.push(`- 最有力候補: **${result.title}**`);
      if (result.doi) lines.push(`- DOI: \`${result.doi}\``);
      const mdDiffLines = renderFieldDiffs(pickFieldDiffs(result));
      if (mdDiffLines.length) {
        for (const line of mdDiffLines) lines.push(`- ${line}`);
      } else if (result.comparison_summary) {
        lines.push(`- 比較: ${result.comparison_summary}`);
      }
      if (Array.isArray(result.candidates) && result.candidates.length) {
        lines.push("", "#### 修正候補", "");
        for (const candidate of result.candidates) {
          lines.push(`- **${candidate.title || "候補"}**`);
          if (candidate.doi) lines.push(`- DOI: \`${candidate.doi}\``);
          if (candidate.field_summary) lines.push(`- 比較: ${candidate.field_summary}`);
          lines.push("");
        }
      } else {
        lines.push("");
      }
      continue;
    }

    if (state === "year-warning") {
      lines.push("### △ 出版年注意", "", `- 入力: \`${escapeInlineCode(result.input_text)}\``);
      if (result.title) lines.push(`- マッチ: **${result.title}**`);
      if (result.doi) lines.push(`- DOI: \`${result.doi}\``);
      lines.push("- 注: タイトル・著者は一致していますが、出版年が参照と異なる可能性があります。", "");
      continue;
    }

    if (state === "not-found" || state === "error") {
      lines.push("### ❌ 未発見", "", `- 入力: \`${escapeInlineCode(result.input_text)}\``);
      if (result.error) {
        lines.push(`- 理由: ${result.message || "APIエラー"}`, "");
      } else {
        lines.push(`- 理由: ${result.note || "候補なし"}`, "");
      }
      continue;
    }

    lines.push(
      "### 🚩 撤回・撤回相当（Crossref 更新通知）",
      "",
      `- 入力: \`${escapeInlineCode(result.input_text)}\``,
      `- マッチ: **${result.title || "(no title)"}**`,
      `- DOI: \`${result.doi || "N/A"}\``,
      "",
      "#### 参照された更新（通知）",
      ""
    );

    for (const detail of result.retraction_details || []) {
      const updated = detail.updated?.["date-time"] || "N/A";
      lines.push(`- 種別: **${detail.update_type || "N/A"}**, 通知DOI: \`${detail.notice_doi || "N/A"}\`, source: \`${detail.source || "N/A"}\`, date: \`${updated}\``);
    }
    lines.push("");
  }

  return lines.join("\n");
}

async function checkReference(ref, email) {
  const response = await fetch("/api/check", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref, email }),
  });

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok || !payload?.ok) {
    const message = payload?.error || (response.status === 504 ? "timeout" : "request_failed");
    throw new Error(message);
  }

  return payload.result;
}

async function runAudit() {
  const refs = splitReferences(referencesInput.value);
  const email = emailInput.value.trim();

  if (!email) {
    statusText.textContent = "メールアドレスを入力してください。";
    emailInput.focus();
    return;
  }

  if (!refs.length) {
    statusText.textContent = "参考文献テキストを入力してください。";
    referencesInput.focus();
    return;
  }

  syncStoredEmail();
  runButton.disabled = true;
  downloadButton.disabled = true;
  latestResults = [];
  renderResults(latestResults);
  updateSummary(latestResults);

  try {
    for (let index = 0; index < refs.length; index += 1) {
      const ref = refs[index];
      statusText.textContent = `${index + 1}/${refs.length} チェック中...`;
      try {
        const result = await checkReference(ref, email);
        latestResults.push(result);
      } catch (error) {
        latestResults.push({
          input_text: ref,
          found: false,
          status: "not_found",
          retracted: false,
          is_website: false,
          error: true,
          message: error instanceof Error ? error.message : "request_failed",
          retraction_details: [],
        });
      }
      renderResults(latestResults);
      updateSummary(latestResults);
    }

    statusText.textContent = `${refs.length}件のチェックが完了しました。`;
    downloadButton.disabled = false;
  } finally {
    runButton.disabled = false;
  }
}

function downloadMarkdown() {
  const markdown = buildMarkdown(latestResults, referencesInput.value);
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "report.md";
  link.click();
  URL.revokeObjectURL(url);
}

rememberEmail.addEventListener("change", syncStoredEmail);
emailInput.addEventListener("input", () => {
  if (rememberEmail.checked) {
    syncStoredEmail();
  }
});
runButton.addEventListener("click", runAudit);
downloadButton.addEventListener("click", downloadMarkdown);

loadStoredEmail();
renderResults([]);
