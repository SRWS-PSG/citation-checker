const STORAGE_KEY = "citeguard.contactEmail";

const emailInput = document.getElementById("email");
const rememberEmail = document.getElementById("remember-email");
const rawInput = document.getElementById("raw");
const referencesEditor = document.getElementById("references");
const cleanButton = document.getElementById("clean");
const recleanButton = document.getElementById("reclean");
const runButton = document.getElementById("run");
const downloadButton = document.getElementById("download");
const statusText = document.getElementById("status");
const summaryText = document.getElementById("summary");
const resultsEl = document.getElementById("results");
const template = document.getElementById("result-template");

let latestResults = [];
let latestDiagnostics = [];

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

/* ---------- Reconstruction (server-side, mirrors CLI split_references) ---------- */

async function cleanReferences(text) {
  const response = await fetch("/api/clean", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ text }),
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

  return Array.isArray(payload.refs) ? payload.refs : [];
}

/* ---------- Per-reference editor (one row = one reference) ---------- */

const REF_EMPTY_HTML =
  '<p class="ref-empty">「整形 →」を押すと、再構成された文献リストがここに表示されます。原文と見比べて修正してください。</p>';

function autoGrow(input) {
  input.style.height = "auto";
  input.style.height = `${input.scrollHeight}px`;
}

function createRefRow(value) {
  const row = document.createElement("div");
  row.className = "ref-row";

  const num = document.createElement("span");
  num.className = "ref-num";
  num.setAttribute("aria-hidden", "true");

  const input = document.createElement("textarea");
  input.className = "ref-input";
  input.rows = 1;
  input.value = value;
  input.addEventListener("input", () => autoGrow(input));
  input.addEventListener("keydown", onRefKeydown);

  row.append(num, input);
  return row;
}

function getRefRows() {
  return Array.from(referencesEditor.querySelectorAll(".ref-input"));
}

/* Each row holds one reference; flatten any stray newlines and drop empties. */
function getRefValues() {
  return getRefRows()
    .map((input) => input.value.replace(/\s*\n\s*/g, " ").trim())
    .filter(Boolean);
}

function setRefValues(refs) {
  referencesEditor.innerHTML = "";
  if (!refs.length) {
    referencesEditor.innerHTML = REF_EMPTY_HTML;
    return;
  }
  for (const ref of refs) {
    referencesEditor.appendChild(createRefRow(ref));
  }
  // scrollHeight needs layout, so size the rows after they are attached.
  requestAnimationFrame(() => getRefRows().forEach(autoGrow));
}

function setEditorEnabled(enabled) {
  referencesEditor.classList.toggle("is-disabled", !enabled);
  getRefRows().forEach((input) => {
    input.readOnly = !enabled;
  });
}

// Enter splits a row at the caret; Backspace at the line start merges into the
// previous row. Composition guards keep Japanese IME confirmation from splitting.
function onRefKeydown(event) {
  const input = event.target;
  const row = input.closest(".ref-row");

  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault();
    const before = input.value.slice(0, input.selectionStart);
    const after = input.value.slice(input.selectionEnd);
    input.value = before;
    autoGrow(input);

    const newRow = createRefRow(after);
    row.after(newRow);
    const newInput = newRow.querySelector(".ref-input");
    autoGrow(newInput);
    newInput.focus();
    newInput.setSelectionRange(0, 0);
    return;
  }

  if (event.key === "Backspace" && input.selectionStart === 0 && input.selectionEnd === 0) {
    const prevRow = row.previousElementSibling;
    if (!prevRow || !prevRow.classList.contains("ref-row")) return;
    event.preventDefault();
    const prevInput = prevRow.querySelector(".ref-input");
    const joinAt = prevInput.value.length;
    prevInput.value += input.value;
    row.remove();
    autoGrow(prevInput);
    prevInput.focus();
    prevInput.setSelectionRange(joinAt, joinAt);
  }
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
  if (result.retracted) {
    return { kind: "retracted", label: "🚩 撤回" };
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
  if (result.verification_status === "partial") {
    return { kind: "partial", label: "未検証あり" };
  }
  if (result.is_website) {
    return { kind: "website", label: "ウェブサイト" };
  }
  if (!result.found) {
    return { kind: "not-found", label: "未発見" };
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
    if (result.verification_status === "partial") {
      rows.push("検証状態: 一部ソースを検証できませんでした。");
    }
    if (Array.isArray(result.unchecked_sources) && result.unchecked_sources.length) {
      rows.push(`未検証ソース: ${result.unchecked_sources.join(", ")}`);
    }
    if (result.source_errors && typeof result.source_errors === "object") {
      for (const [source, message] of Object.entries(result.source_errors)) {
        rows.push(`ソースエラー: ${source} / ${message}`);
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
    partial: 0,
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

  summaryText.textContent = `正常 ${counts.ok} / 未検証あり ${counts.partial} / 誤引用候補 ${counts["likely-wrong"]} / 未発見 ${counts["not-found"]} / 撤回 ${counts.retracted} / 年注意 ${counts["year-warning"]} / ウェブサイト ${counts.website} / エラー ${counts.error}`;
}

function escapeInlineCode(value) {
  return String(value || "").replace(/`/g, "\\`");
}

function buildMarkdown(results, inputText, diagnosticsList) {
  const counts = {
    ok: 0,
    partial: 0,
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
    `- 未検証あり: ${counts.partial}`,
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
    return ["partial", "likely-wrong", "not-found", "retracted", "year-warning", "error"].includes(state);
  });

  if (!bad.length) {
    lines.push("_問題のある書誌は見つかりませんでした。_");
    return lines.join("\n");
  }

  for (const result of bad) {
    const state = classify(result).kind;
    if (state === "partial") {
      lines.push("### ⏱ 検証未完了", "", `- 入力: \`${escapeInlineCode(result.input_text)}\``);
      if (result.title) lines.push(`- 現時点のマッチ: **${result.title}**`);
      if (result.doi) lines.push(`- DOI: \`${result.doi}\``);
      if (result.comparison_summary) lines.push(`- 比較: ${result.comparison_summary}`);
      if (Array.isArray(result.unchecked_sources) && result.unchecked_sources.length) {
        lines.push(`- 未検証ソース: ${result.unchecked_sources.join(", ")}`);
      }
      if (result.source_errors && typeof result.source_errors === "object") {
        for (const [source, message] of Object.entries(result.source_errors)) {
          lines.push(`- ソースエラー: ${source} / ${message}`);
        }
      }
      lines.push("");
      continue;
    }

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

  // --- Diagnostics section ---
  if (Array.isArray(diagnosticsList) && diagnosticsList.length > 0) {
    const hasErrors = results.some((r) => r.error);
    lines.push("---", "", "## Diagnostics", "");
    if (hasErrors) {
      lines.push(
        "> **エラーが発生しています。** 問題が解消しない場合、このレポートファイルを開発者にお送りください。",
        ""
      );
    }
    lines.push("| # | elapsed (s) | budget (s) | skipped | error |");
    lines.push("|---|---|---|---|---|");
    for (let i = 0; i < diagnosticsList.length; i += 1) {
      const d = diagnosticsList[i];
      if (!d) {
        lines.push(`| ${i + 1} | - | - | - | - |`);
      } else if (d.error) {
        lines.push(`| ${i + 1} | - | - | - | ${d.error} |`);
      } else {
        const skipped = (d.skipped && d.skipped.length > 0) ? d.skipped.join(", ") : "-";
        const error = d.source_errors && Object.keys(d.source_errors).length > 0
          ? Object.entries(d.source_errors).map(([source, message]) => `${source}:${message}`).join(", ")
          : "-";
        lines.push(`| ${i + 1} | ${d.elapsed_sec ?? "-"} | ${d.budget_sec ?? "-"} | ${skipped} | ${error} |`);
      }
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

  return { result: payload.result, diagnostics: payload.diagnostics || null };
}

function setStageReady(ready) {
  setEditorEnabled(ready);
  recleanButton.disabled = !ready;
  runButton.disabled = !ready;
}

async function runClean({ reclean = false } = {}) {
  const text = rawInput.value;
  if (!text.trim()) {
    statusText.textContent = "整形する参考文献テキストを入力してください。";
    rawInput.focus();
    return;
  }
  if (reclean && getRefValues().length) {
    const ok = window.confirm("整形結果を原文から作り直します。右側の編集内容は破棄されます。よろしいですか？");
    if (!ok) return;
  }

  cleanButton.disabled = true;
  recleanButton.disabled = true;
  runButton.disabled = true;
  statusText.textContent = "整形中...";

  try {
    const refs = await cleanReferences(text);
    setRefValues(refs);
    if (refs.length) {
      setStageReady(true);
      statusText.textContent = `整形しました（${refs.length}件）。原文と見比べて確認・修正してから「チェック開始」を押してください。`;
      const firstRow = getRefRows()[0];
      if (firstRow) firstRow.focus();
    } else {
      runButton.disabled = true;
      recleanButton.disabled = false;
      statusText.textContent = "整形できる文献が見つかりませんでした。原文をご確認ください。";
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : "request_failed";
    statusText.textContent = `整形に失敗しました: ${message}`;
  } finally {
    cleanButton.disabled = false;
  }
}

async function runAudit() {
  const refs = getRefValues();
  const email = emailInput.value.trim();

  if (!email) {
    statusText.textContent = "メールアドレスを入力してください。";
    emailInput.focus();
    return;
  }

  if (!refs.length) {
    statusText.textContent = "整形結果が空です。先に「整形 →」を押すか、文献を入力してください。";
    const firstRow = getRefRows()[0];
    if (firstRow) firstRow.focus();
    return;
  }

  syncStoredEmail();
  runButton.disabled = true;
  recleanButton.disabled = true;
  cleanButton.disabled = true;
  downloadButton.disabled = true;
  setEditorEnabled(false);
  latestResults = [];
  latestDiagnostics = [];
  renderResults(latestResults);
  updateSummary(latestResults);

  try {
    for (let index = 0; index < refs.length; index += 1) {
      const ref = refs[index];
      statusText.textContent = `${index + 1}/${refs.length} チェック中...`;
      try {
        const { result, diagnostics } = await checkReference(ref, email);
        latestResults.push(result);
        latestDiagnostics.push(diagnostics);
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
        latestDiagnostics.push({ error: error instanceof Error ? error.message : "request_failed" });
      }
      renderResults(latestResults);
      updateSummary(latestResults);
    }

    statusText.textContent = `${refs.length}件のチェックが完了しました。`;
    downloadButton.disabled = false;
  } finally {
    runButton.disabled = false;
    recleanButton.disabled = false;
    cleanButton.disabled = false;
    setEditorEnabled(true);
  }
}

function downloadMarkdown() {
  const markdown = buildMarkdown(latestResults, getRefValues().join("\n"), latestDiagnostics);
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
cleanButton.addEventListener("click", () => runClean());
recleanButton.addEventListener("click", () => runClean({ reclean: true }));
runButton.addEventListener("click", runAudit);
downloadButton.addEventListener("click", downloadMarkdown);

loadStoredEmail();
renderResults([]);
