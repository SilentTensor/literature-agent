/* ═══════════════════════════════════════════════════════════════
   文献调研智能体 — Scripts
   ═══════════════════════════════════════════════════════════════ */

let currentTaskId = null;
let currentPapers = [];
let pollingTimer = null;
const API_BASE = "";

/* ── LLM Provider ──────────────────────────────────────────── */
function updateModelOptions() {
  var provider = document.getElementById("llm-provider").value;
  var msel = document.getElementById("model-select");
  var models = {
    openai: [
      { value: "gpt-4o", label: "GPT-4o" },
      { value: "gpt-4o-mini", label: "GPT-4o-mini" },
    ],
    deepseek: [
      { value: "deepseek-chat", label: "DeepSeek-Chat (V3)" },
      { value: "deepseek-reasoner", label: "DeepSeek-Reasoner (R1)" },
    ],
  };
  var opts = models[provider] || models.openai;
  msel.innerHTML = opts.map(function(o) { return '<option value="' + o.value + '">' + o.label + '</option>'; }).join("");
  var saved = localStorage.getItem("llm_model");
  if (saved && opts.some(function(o) { return o.value === saved; })) msel.value = saved;
}


/* ── Example topics ──────────────────────────────────────────── */
function fillExample(n) {
  const examples = [
    "基于图神经网络的药物靶点预测",
    "大语言模型在医疗领域可解释性的挑战与解决方案",
    "多模态情感分析综述",
  ];
  document.getElementById("topic-input").value = examples[n - 1];
}

/* ── Config ──────────────────────────────────────────────────── */
function saveConfig() {
  const key = document.getElementById("api-key-input").value;
  if (key) {
    localStorage.setItem("openai_api_key", key);
  }
  const model = document.getElementById("model-select").value;
  localStorage.setItem("openai_model", model);
  const provider = document.getElementById("llm-provider").value;
  localStorage.setItem("llm_provider", provider);
  localStorage.setItem("llm_model", model);
  showToast("配置已保存");
}

function loadConfig() {
  const key = localStorage.getItem("openai_api_key");
  if (key) {
    document.getElementById("api-key-input").value = key;
  }
  const model = localStorage.getItem("openai_model");
  if (model) { document.getElementById("model-select").value = model; }
  const savedProvider = localStorage.getItem("llm_provider");
  if (savedProvider) { document.getElementById("llm-provider").value = savedProvider; } if (typeof updateModelOptions === "function") { updateModelOptions(); }
}

/* ── Start Search ────────────────────────────────────────────── */
async function startSearch() {
  const topic = document.getElementById("topic-input").value.trim();
  if (!topic) {
    showToast("请输入综述主题", "error");
    return;
  }

  const btn = document.getElementById("btn-search");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 搜索中...';

  const apiKey = document.getElementById("api-key-input").value.trim() ||
                 localStorage.getItem("openai_api_key") || "";
  const model = document.getElementById("model-select").value ||
               localStorage.getItem("openai_model") || (document.getElementById("llm-provider")?.value === "deepseek" ? "deepseek-chat" : "gpt-4o-mini");
  const notes = document.getElementById("notes-input").value.trim();
  const seedInput = document.getElementById("seed-input").value.trim();
  const seedIds = seedInput ? seedInput.split(",").map(s => s.trim()).filter(Boolean) : [];
  const iterations = parseInt(document.getElementById("iterations").value) || 2;

  // Build headers
  const headers = { "Content-Type": "application/json" };
  if (apiKey) { headers["X-API-Key"] = apiKey; }
  const llmProvider = document.getElementById("llm-provider").value || "deepseek";
  const llmModel = document.getElementById("model-select").value || "deepseek-chat";
  headers["X-LLM-Provider"] = llmProvider;
  headers["X-LLM-Model"] = llmModel;


  try {
    const resp = await fetch(`${API_BASE}/api/search`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        topic,
        max_iterations: iterations,
        seed_paper_ids: seedIds,
        user_notes: notes,
      }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || "搜索请求失败");
    }

    const data = await resp.json();
    currentTaskId = data.task_id;

    // Show progress panel
    document.getElementById("empty-state").classList.add("hidden");
    document.getElementById("results-panel").classList.add("hidden");
    document.getElementById("progress-panel").classList.remove("hidden");
    document.getElementById("task-id").textContent = `#${data.task_id}`;
    document.getElementById("progress-message").textContent = "任务已提交，开始处理...";

    // Start polling
    startPolling(data.task_id, apiKey, model);
  } catch (err) {
    showToast(err.message || "搜索失败", "error");
    btn.disabled = false;
    btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg> 开始文献调研';
  }
}

/* ── Polling ────────────────────────────────────────────────── */
function startPolling(taskId, apiKey, model) {
  if (pollingTimer) clearInterval(pollingTimer);

  pollingTimer = setInterval(async () => {
    try {
      const headers = {};
      if (apiKey) headers["X-API-Key"] = apiKey;
    const llmProvider = document.getElementById("llm-provider").value || "deepseek";
    const llmModel = document.getElementById("model-select").value || "deepseek-chat";
    headers["X-LLM-Provider"] = llmProvider;
    headers["X-LLM-Model"] = llmModel;

      const resp = await fetch(`${API_BASE}/api/status/${taskId}`, { headers });
      if (!resp.ok) return;

      const state = await resp.json();

      // Update progress
      updateProgress(state);

      if (state.status === "completed") {
        clearInterval(pollingTimer);
        pollingTimer = null;
        showResults(state, apiKey, model);
        document.getElementById("btn-search").disabled = false;
        document.getElementById("btn-search").innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg> 开始文献调研';
      } else if (state.status === "error") {
        clearInterval(pollingTimer);
        pollingTimer = null;
        showToast(`错误：${state.error || state.message}`, "error");
        document.getElementById("progress-message").textContent = `错误：${state.error || state.message}`;
        document.getElementById("progress-message").style.color = "#dc2626";
        document.getElementById("btn-search").disabled = false;
        document.getElementById("btn-search").innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg> 开始文献调研';
      }
    } catch (err) {
      // Silently retry
    }
  }, 1500);
}

/* ── Update Progress ────────────────────────────────────────── */
function updateProgress(state) {
  const bar = document.getElementById("progress-bar");
  bar.style.width = state.progress_pct + "%";

  const msg = document.getElementById("progress-message");
  msg.textContent = state.message || "";

  // Update phases
  const phases = ["decompose", "search", "expand", "validate", "gap", "final"];
  const phaseMap = {
    decompose: { label: "主题解析", el: "phase-decompose" },
    search: { label: "多策略检索", el: "phase-search" },
    expand: { label: "引文扩展", el: "phase-search" },
    validate: { label: "相关性验证", el: "phase-validate" },
    gap: { label: "缺口分析", el: "phase-gap" },
    final: { label: "完成", el: "phase-final" },
  };

  let currentPhaseIdx = -1;
  if (state.phase && phaseMap[state.phase]) {
    currentPhaseIdx = phases.indexOf(state.phase);
  }

  phases.forEach((p, i) => {
    const el = document.querySelector(`.phase[data-phase="${p}"]`);
    if (!el) return;

    const statusEl = el.querySelector(".phase-status");
    el.classList.remove("active", "done", "error");

    if (state.status === "error") {
      if (i === currentPhaseIdx) {
        el.classList.add("error");
        statusEl.textContent = "出错";
      } else if (i < currentPhaseIdx) {
        el.classList.add("done");
        statusEl.textContent = "已完成";
      }
    } else if (state.status === "completed") {
      el.classList.add("done");
      statusEl.textContent = "已完成";
    } else {
      if (i < currentPhaseIdx) {
        el.classList.add("done");
        statusEl.textContent = "已完成";
      } else if (i === currentPhaseIdx) {
        el.classList.add("active");
        statusEl.textContent = "进行中...";
      } else {
        statusEl.textContent = "等待中";
      }
    }
  });

  // Show validated count during validation
  if (state.phase === "validate" && state.validated_count > 0) {
    msg.textContent = `验证完成，${state.validated_count} 篇论文通过严格相关性筛选`;
  }
}

/* ── Show Results ───────────────────────────────────────────── */
function showResults(state, apiKey, model) {
  document.getElementById("progress-panel").classList.add("hidden");
  document.getElementById("results-panel").classList.remove("hidden");

  // Decomposition
  if (state.decomposition) {
    const card = document.getElementById("decomposition-card");
    card.classList.remove("hidden");
    renderDecomposition(state.decomposition);
  }

  // Gap analysis
  if (state.gap_suggestions && state.gap_suggestions.length > 0) {
    const card = document.getElementById("gap-card");
    card.classList.remove("hidden");
    const list = document.getElementById("gap-list");
    list.innerHTML = state.gap_suggestions.map(s => `<li>${s}</li>`).join("");
  }

  // Papers
  currentPapers = state.results || [];
  renderPapers(currentPapers);
  document.getElementById("result-count").textContent =
    `${currentPapers.length} 篇文献`;

  // Save task ID for refine
  // currentTaskId already set from polling
  localStorage.setItem("last_task_id", currentTaskId);
}

/* ── Render Papers ──────────────────────────────────────────── */
function renderPapers(papers) {
  const container = document.getElementById("paper-list");
  if (!papers.length) {
    container.innerHTML = `<div class="card" style="text-align:center;padding:40px;color:var(--text-secondary)">
      <p>未找到符合条件的高质量文献。建议修改主题或扩大搜索范围。</p>
    </div>`;
    return;
  }

  container.innerHTML = papers.map((p, i) => `
    <div class="paper-item" data-idx="${i}">
      <div class="paper-header">
        <div>
          <a class="paper-title" href="${p.url || '#'}" target="_blank" rel="noopener">
            ${p.title || "Untitled"}
          </a>
          <div class="paper-meta">
            ${p.authors && p.authors.length
              ? `<span class="paper-authors" title="${p.authors.join(', ')}">${p.authors.slice(0, 4).join(', ')}${p.authors.length > 4 ? ' et al.' : ''}</span>`
              : '<span class="paper-authors" style="color:#9ca3af">No authors</span>'}
            <span class="badge-yr">${p.year || 'n.d.'}</span>
            <span class="badge-cites">${p.citationCount || 0} 引用</span>
            <span class="type-tag ${p.paper_type}">${p.paper_type || 'other'}</span>
          </div>
        </div>
        <span class="score-badge score-${p.score}">${p.score}</span>
      </div>
      ${p.reason ? `<div class="paper-reason">${p.reason}</div>` : ''}
      <button class="expand-btn" onclick="toggleAbstract(${i})">查看摘要</button>
      <div class="paper-abstract">${p.abstract || '暂无摘要'}</div>
    </div>
  `).join("");
}

/* ── Toggle Abstract ────────────────────────────────────────── */
function toggleAbstract(idx) {
  const item = document.querySelector(`.paper-item[data-idx="${idx}"]`);
  if (item) {
    item.classList.toggle("expanded");
    const btn = item.querySelector(".expand-btn");
    btn.textContent = item.classList.contains("expanded") ? "收起摘要" : "查看摘要";
  }
}

/* ── Render Decomposition ───────────────────────────────────── */
function renderDecomposition(dec) {
  const container = document.getElementById("decomposition-content");
  let html = `<p><strong>核心问题：</strong>${dec.core_question || ''}</p>`;

  if (dec.sub_topics && dec.sub_topics.length) {
    html += '<div class="decomp-grid">';
    dec.sub_topics.forEach(st => {
      html += '<div class="decomp-item">';
      html += `<h4>${st.aspect || ''}</h4>`;
      const items = st.methods || st.settings || [];
      if (items.length) {
        html += '<ul>';
        items.forEach(item => { html += `<li>${item}</li>`; });
        html += '</ul>';
      }
      html += '</div>';
    });
    html += '</div>';
  }

  if (dec.keyword_groups && dec.keyword_groups.length) {
    html += '<p style="margin-top:8px"><strong>关键词分组：</strong></p>';
    html += '<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px">';
    dec.keyword_groups.forEach(g => {
      html += `<span class="chip">${g.join(', ')}</span>`;
    });
    html += '</div>';
  }

  if (dec.seed_suggestions) {
    html += `<p style="margin-top:8px;font-size:12px;color:var(--text-secondary)"><strong>建议：</strong>${dec.seed_suggestions}</p>`;
  }

  container.innerHTML = html;
}

/* ── Filter Results ─────────────────────────────────────────── */
function filterResults(type) {
  document.querySelectorAll(".filter-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.type === type);
  });

  const filtered = type === "all"
    ? currentPapers
    : currentPapers.filter(p => p.paper_type === type);

  renderPapers(filtered);
  document.getElementById("result-count").textContent =
    `${filtered.length} / ${currentPapers.length} 篇`;
}

/* ── Refine ─────────────────────────────────────────────────── */
function showRefinePanel() {
  document.getElementById("refine-panel").classList.remove("hidden");
}

function hideRefinePanel() {
  document.getElementById("refine-panel").classList.add("hidden");
}

async function submitRefine() {
  const feedback = document.getElementById("refine-feedback").value.trim();
  if (!feedback) {
    showToast("请描述需要补充的文献", "error");
    return;
  }

  const kwStr = document.getElementById("refine-keywords").value.trim();
  const newKeywords = kwStr ? kwStr.split(",").map(s => s.trim()).filter(Boolean) : [];

  const apiKey = document.getElementById("api-key-input").value.trim() ||
                 localStorage.getItem("openai_api_key") || "";

  try {
    const headers = { "Content-Type": "application/json" };
    if (apiKey) headers["X-API-Key"] = apiKey;
    const llmProvider = document.getElementById("llm-provider").value || "deepseek";
    const llmModel = document.getElementById("model-select").value || "deepseek-chat";
    headers["X-LLM-Provider"] = llmProvider;
    headers["X-LLM-Model"] = llmModel;

    const resp = await fetch(`${API_BASE}/api/refine`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        task_id: currentTaskId,
        feedback,
        new_keywords: newKeywords,
      }),
    });

    if (!resp.ok) throw new Error("补充搜索请求失败");

    const data = await resp.json();
    currentTaskId = data.task_id;
    hideRefinePanel();

    // Show progress
    document.getElementById("results-panel").classList.add("hidden");
    document.getElementById("progress-panel").classList.remove("hidden");
    document.getElementById("task-id").textContent = `#${data.task_id}`;
    document.getElementById("progress-message").textContent = "补充搜索已启动...";

    // Reset phases
    document.querySelectorAll(".phase").forEach(el => {
      el.classList.remove("active", "done", "error");
      el.querySelector(".phase-status").textContent = "等待中";
    });

    startPolling(data.task_id, apiKey, null);
  } catch (err) {
    showToast(err.message || "补充搜索失败", "error");
  }
}

/* ── Export ──────────────────────────────────────────────────── */
async function exportResults(fmt) {
  if (!currentTaskId) return;

  const apiKey = document.getElementById("api-key-input").value.trim() ||
                 localStorage.getItem("openai_api_key") || "";

  try {
    const headers = {};
    if (apiKey) headers["X-API-Key"] = apiKey;
    const llmProvider = document.getElementById("llm-provider").value || "deepseek";
    const llmModel = document.getElementById("model-select").value || "deepseek-chat";
    headers["X-LLM-Provider"] = llmProvider;
    headers["X-LLM-Model"] = llmModel;

    const resp = await fetch(`${API_BASE}/api/export/${currentTaskId}?fmt=${fmt}`, { headers });
    if (!resp.ok) throw new Error("导出失败");

    const data = await resp.json();
    const content = fmt === "bibtex" ? data.content : JSON.stringify(data, null, 2);

    const modal = document.getElementById("export-modal");
    modal.classList.remove("hidden");
    document.getElementById("export-content").value = content;
    document.querySelector(".modal h3").textContent =
      `导出 (${fmt.toUpperCase()}) — ${data.total_count || data.papers?.length || 0} 篇文献`;
  } catch (err) {
    showToast(err.message || "导出失败", "error");
  }
}

function closeExportModal(e) {
  if (e && e.target !== document.getElementById("export-modal")) return;
  if (!e || e.target === document.getElementById("export-modal")) {
    document.getElementById("export-modal").classList.add("hidden");
  }
}

function copyExport() {
  const content = document.getElementById("export-content");
  content.select();
  document.execCommand("copy");
  showToast("已复制到剪贴板");
}

/* ── Toast ──────────────────────────────────────────────────── */
function showToast(msg, type = "info") {
  const existing = document.querySelector(".toast");
  if (existing) existing.remove();

  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = msg;
  toast.style.cssText = `
    position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
    padding: 10px 20px; border-radius: 8px; font-size: 13px; font-weight: 500;
    background: ${type === "error" ? "#fef2f2" : "#f0fdf4"};
    color: ${type === "error" ? "#dc2626" : "#059669"};
    border: 1px solid ${type === "error" ? "#fecaca" : "#bbf7d0"};
    box-shadow: 0 4px 12px rgba(0,0,0,0.1); z-index: 200;
    animation: fadeIn 0.2s ease;
  `;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transition = "opacity 0.3s";
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

/* ── Init ────────────────────────────────────────────────────── */
try { loadConfig(); } catch(e) { console.warn("Init error:", e); if (typeof updateModelOptions === "function") { updateModelOptions(); } }

/* Add fadeIn animation */
const style = document.createElement("style");
style.textContent = `@keyframes fadeIn { from { opacity: 0; transform: translateX(-50%) translateY(8px); } to { opacity: 1; transform: translateX(-50%) translateY(0); } }`;
document.head.appendChild(style);







