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

function splitReferences(text) {
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
    retracted: 0,
    website: 0,
    "year-warning": 0,
    error: 0,
  };

  for (const result of results) {
    counts[classify(result).kind] += 1;
  }

  summaryText.textContent = `正常 ${counts.ok} / 未発見 ${counts["not-found"]} / 撤回 ${counts.retracted} / 年注意 ${counts["year-warning"]} / ウェブサイト ${counts.website} / エラー ${counts.error}`;
}

function escapeInlineCode(value) {
  return String(value || "").replace(/`/g, "\\`");
}

function buildMarkdown(results) {
  const bad = results.filter((result) => {
    const state = classify(result).kind;
    return ["not-found", "retracted", "year-warning", "error"].includes(state);
  });

  const lines = [
    "# Reference Audit Report",
    "",
    "対象：貼り付けテキストのうち **問題があった書誌**（未発見／撤回系）だけを列挙しています。",
    "",
  ];

  if (!bad.length) {
    lines.push("_問題のある書誌は見つかりませんでした。_");
    return lines.join("\n");
  }

  for (const result of bad) {
    const state = classify(result).kind;
    if (state === "year-warning") {
      lines.push("## △ 出版年注意", "", `- 入力: \`${escapeInlineCode(result.input_text)}\``);
      if (result.title) lines.push(`- マッチ: **${result.title}**`);
      if (result.doi) lines.push(`- DOI: \`${result.doi}\``);
      lines.push("- 注: タイトル・著者は一致していますが、出版年が参照と異なる可能性があります。", "");
      continue;
    }

    if (state === "not-found" || state === "error") {
      lines.push("## ❌ 未発見", "", `- 入力: \`${escapeInlineCode(result.input_text)}\``);
      if (result.error) {
        lines.push(`- 理由: ${result.message || "APIエラー"}`, "");
      } else {
        lines.push(`- 理由: ${result.note || "候補なし"}`, "");
      }
      continue;
    }

    lines.push(
      "## 🚩 撤回・撤回相当（Crossref 更新通知）",
      "",
      `- 入力: \`${escapeInlineCode(result.input_text)}\``,
      `- マッチ: **${result.title || "(no title)"}**`,
      `- DOI: \`${result.doi || "N/A"}\``,
      "",
      "### 参照された更新（通知）",
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
  const markdown = buildMarkdown(latestResults);
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
