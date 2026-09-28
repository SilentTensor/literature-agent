/* ═══════════════════════════════════════════════════════════════
   文献调研智能体 — 前端脚本
   与 static/index.html 的 DOM id 严格对应，勿单独改动其中一方
   ═══════════════════════════════════════════════════════════════ */
(function () {
  "use strict";

  var API_BASE = "";
  var PHASES = ["decompose", "search", "expand", "validate", "gap"];
  var POLL_INTERVAL = 1200;
  var POLL_TIMEOUT_MS = 10 * 60 * 1000;   // 超过 10 分钟认为任务卡死

  var state = {
    taskId: null,
    papers: [],
    filter: "all",
    timer: null,
    startedAt: 0,
    provider: "deepseek",
    model: "deepseek-chat",
    exportFmt: "json",
  };
  // 服务器端状态（来自 /api/config），用于计算徽章文案
  var serverHasKey = false;
  var serverKeyForAnon = false;

  /* ── 小工具 ───────────────────────────────────────────────── */
  function $(id) { return document.getElementById(id); }

  function esc(s) {
    return String(s === null || s === undefined ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function safeUrl(u) {
    var s = String(u || "").trim();
    return /^https?:\/\//i.test(s) ? s : "";
  }

  function show(el) { if (el) el.classList.remove("hidden"); }
  function hide(el) { if (el) el.classList.add("hidden"); }

  function toast(msg, type) {
    var old = document.querySelector(".toast");
    if (old) old.remove();
    var d = document.createElement("div");
    d.className = "toast";
    d.textContent = msg;
    d.style.cssText =
      "position:fixed;bottom:24px;left:50%;transform:translateX(-50%);padding:10px 20px;" +
      "border-radius:8px;font-size:13px;font-weight:500;z-index:300;box-shadow:0 4px 12px rgba(0,0,0,.15);" +
      "background:" + (type === "error" ? "#fef2f2" : "#f0fdf4") + ";color:" +
      (type === "error" ? "#dc2626" : "#059669") + ";border:1px solid " +
      (type === "error" ? "#fecaca" : "#bbf7d0") + ";";
    document.body.appendChild(d);
    setTimeout(function () { d.remove(); }, 2800);
  }

  /* ── 配置：提供商 / 模型 / Key 持久化 ─────────────────────── */
  // 顺序即优先级，第一项为默认值。
  // deepseek-reasoner 不支持 JSON 输出模式，本程序需要结构化结果，
  // 因此放在最后并加注说明（选中时后端会自动兜底，但会明显变慢、变贵）。
  var MODELS = {
    openai: ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"],
    deepseek: ["deepseek-chat", "deepseek-reasoner"],
  };

  var MODEL_LABELS = {
    "deepseek-chat": "deepseek-chat（推荐）",
    "deepseek-reasoner": "deepseek-reasoner（慢，且不支持 JSON 模式）",
    "gpt-4o-mini": "gpt-4o-mini（推荐）",
    "gpt-4o": "gpt-4o",
    "gpt-4-turbo": "gpt-4-turbo",
  };

  // API Key 只放在 sessionStorage：关掉标签页即失效。
  // 放在 localStorage 会让 Key 长期留在磁盘上，而它还会被发到部署方的服务器。
  function getStoredKey() {
    try { return sessionStorage.getItem("llm_api_key") || ""; } catch (e) { return ""; }
  }

  function setStoredKey(key) {
    try {
      if (key) sessionStorage.setItem("llm_api_key", key);
      else sessionStorage.removeItem("llm_api_key");
    } catch (e) { /* 隐私模式，忽略 */ }
  }

  function renderModels(keepValue) {
    var sel = $("model-select");
    var list = MODELS[state.provider] || MODELS.openai;
    sel.innerHTML = list.map(function (m) {
      return '<option value="' + esc(m) + '">' + esc(MODEL_LABELS[m] || m) + "</option>";
    }).join("");
    if (keepValue && list.indexOf(keepValue) >= 0) sel.value = keepValue;
    state.model = sel.value;
  }

  function loadConfig() {
    try {
      var savedProvider = localStorage.getItem("llm_provider");
      if (savedProvider && MODELS[savedProvider]) state.provider = savedProvider;
      var savedKey = getStoredKey();
      if (savedKey) $("api-key-input").value = savedKey;
      var savedModel = localStorage.getItem("llm_model");
      $("llm-provider").value = state.provider;
      renderModels(savedModel);
      var it = localStorage.getItem("iterations");
      if (it) $("iterations").value = it;
    } catch (e) {
      renderModels(null);
    }
  }

  function saveConfig() {
    state.provider = $("llm-provider").value;
    state.model = $("model-select").value;
    setStoredKey($("api-key-input").value.trim());
    try {
      localStorage.setItem("llm_provider", state.provider);
      localStorage.setItem("llm_model", state.model);
      localStorage.setItem("iterations", $("iterations").value);
    } catch (e) { /* 隐私模式下 localStorage 可能不可用，忽略 */ }
  }

  function headers(json) {
    var h = {};
    if (json) h["Content-Type"] = "application/json";
    var key = $("api-key-input").value.trim();
    if (key) h["X-API-Key"] = key;
    h["X-LLM-Provider"] = state.provider;
    h["X-LLM-Model"] = state.model;
    updateKeyBadge();
    return h;
  }

  /**
   * 徽章要反映"这一次请求会不会真的用上 LLM"。
   * 旧版只看服务器有没有配 Key，用户自己填了 Key 也一直显示"未配置"，属于误导。
   */
  function updateKeyBadge() {
    var badge = $("llm-badge");
    if (!badge) return;
    var hasOwn = !!$("api-key-input").value.trim();
    if (hasOwn) {
      badge.textContent = "LLM：已启用你自己的 Key（" + state.model + "）";
      badge.title = "你的 Key 只保存在本标签页（sessionStorage），关闭标签页即失效，" +
                    "仅随请求发送给你正在使用的这个服务器。";
      badge.style.color = "#059669";
    } else if (serverHasKey && serverKeyForAnon) {
      badge.textContent = "LLM：服务器已配置（全部访客可用）";
      badge.style.color = "";
    } else if (serverHasKey) {
      badge.textContent = "LLM：需自带 API Key";
      badge.title = "服务器配了 Key，但只对自带 Key 的请求生效。在左侧填入你自己的 Key 即可启用语义筛选。";
      badge.style.color = "";
    } else {
      badge.textContent = "LLM：未配置 Key（启发式筛选）";
      badge.title = "在左侧填入 DeepSeek / OpenAI Key 可启用逐篇语义评分。留空也能正常检索。";
      badge.style.color = "";
    }
  }

  function setSearching(on) {
    var btn = $("btn-search");
    btn.disabled = on;
    btn.innerHTML = on
      ? '<span class="spinner"></span> 调研中…'
      : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg> 开始文献调研';
  }

  /* ── 启动搜索 ─────────────────────────────────────────────── */
  function startSearch() {
    var topic = $("topic-input").value.trim();
    if (!topic) { toast("请输入综述主题", "error"); $("topic-input").focus(); return; }

    saveConfig();
    setSearching(true);
    hide($("empty-state"));
    hide($("results-panel"));
    show($("progress-panel"));
    resetPhases();
    $("progress-bar").style.width = "3%";
    $("progress-message").style.color = "";
    $("progress-message").textContent = "正在提交任务…";
    $("task-id").textContent = "";
    state.papers = [];
    state.startedAt = Date.now();

    var seedRaw = $("seed-input").value.trim();
    var body = {
      topic: topic,
      max_iterations: parseInt($("iterations").value, 10) || 1,
      user_notes: $("notes-input").value.trim(),
      seed_paper_ids: seedRaw ? seedRaw.split(",").map(function (s) { return s.trim(); }).filter(Boolean) : [],
    };

    fetch(API_BASE + "/api/search", { method: "POST", headers: headers(true), body: JSON.stringify(body) })
      .then(function (r) {
        if (!r.ok) return r.json().catch(function () { return {}; }).then(function (e) {
          throw new Error(e.detail || ("请求失败 " + r.status));
        });
        return r.json();
      })
      .then(function (d) {
        state.taskId = d.task_id;
        $("task-id").textContent = "#" + d.task_id;
        if (d.llm_enabled === false) {
          $("progress-message").textContent = "未启用 LLM，将使用主题相关度 + 引用影响力排序；检索仍然完全可用。";
        }
        startPolling();
      })
      .catch(function (err) {
        setSearching(false);
        toast(err.message || "搜索失败", "error");
        $("progress-message").textContent = "提交失败：" + (err.message || err);
        $("progress-message").style.color = "#dc2626";
      });
  }

  function resetPhases() {
    PHASES.forEach(function (p) {
      var el = document.querySelector('.phase[data-phase="' + p + '"]');
      if (!el) return;
      el.classList.remove("active", "done", "error");
      var st = el.querySelector(".phase-status");
      if (st) st.textContent = "等待中";
    });
  }

  function updateProgress(s) {
    $("progress-bar").style.width = (s.progress_pct || 0) + "%";
    var msg = $("progress-message");
    msg.textContent = s.message || "";
    if (s.status !== "error") msg.style.color = "";

    var idx = PHASES.indexOf(s.phase);
    PHASES.forEach(function (p, i) {
      var el = document.querySelector('.phase[data-phase="' + p + '"]');
      if (!el) return;
      var st = el.querySelector(".phase-status");
      el.classList.remove("active", "done", "error");
      if (s.status === "completed") {
        el.classList.add("done");
        if (st) st.textContent = "已完成";
      } else if (s.status === "error") {
        if (i === idx) { el.classList.add("error"); if (st) st.textContent = "出错"; }
        else if (idx >= 0 && i < idx) { el.classList.add("done"); if (st) st.textContent = "已完成"; }
        else if (st) st.textContent = "未执行";
      } else if (idx >= 0 && i < idx) {
        el.classList.add("done"); if (st) st.textContent = "已完成";
      } else if (i === idx) {
        el.classList.add("active"); if (st) st.textContent = "进行中…";
      } else if (st) {
        st.textContent = "等待中";
      }
    });

    var sec = Math.floor((Date.now() - state.startedAt) / 1000);
    $("elapsed").textContent = "已用时 " + sec + " 秒" + (s.candidate_count ? "　候选 " + s.candidate_count + " 篇" : "");
  }

  /* ── 轮询 ─────────────────────────────────────────────────── */
  function startPolling() {
    stopPolling();
    state.timer = setInterval(pollOnce, POLL_INTERVAL);
    pollOnce();
  }

  function stopPolling() {
    if (state.timer) { clearInterval(state.timer); state.timer = null; }
  }

  function pollOnce() {
    if (!state.taskId) return;
    if (Date.now() - state.startedAt > POLL_TIMEOUT_MS) {
      stopPolling();
      setSearching(false);
      $("progress-message").textContent = "任务超时（超过 10 分钟），请检查服务器日志后重试。";
      $("progress-message").style.color = "#dc2626";
      return;
    }
    fetch(API_BASE + "/api/status/" + state.taskId, { headers: headers(false) })
      .then(function (r) { if (!r.ok) throw new Error("状态查询失败 " + r.status); return r.json(); })
      .then(function (s) {
        updateProgress(s);
        if (s.status === "completed") {
          stopPolling();
          setSearching(false);
          showResults(s);
        } else if (s.status === "error") {
          stopPolling();
          setSearching(false);
          $("progress-message").textContent = "出错：" + (s.error || s.message || "未知错误");
          $("progress-message").style.color = "#dc2626";
          toast("调研失败：" + (s.error || s.message || ""), "error");
        }
      })
      .catch(function () { /* 网络抖动，下一轮继续 */ });
  }

  /* ── 渲染结果 ─────────────────────────────────────────────── */
  function showResults(s) {
    hide($("progress-panel"));
    show($("results-panel"));

    if (s.decomposition) {
      renderDecomposition(s.decomposition);
      show($("decomposition-card"));
    }

    var gaps = s.gap_suggestions || [];
    if (gaps.length) {
      $("gap-list").innerHTML = gaps.map(function (g) {
        return "<li>" + esc(typeof g === "object" ? JSON.stringify(g) : g) + "</li>";
      }).join("");
      show($("gap-card"));
    } else {
      hide($("gap-card"));
    }

    state.papers = s.results || [];
    state.filter = "all";
    document.querySelectorAll(".filter-btn").forEach(function (b) {
      b.classList.toggle("active", b.dataset.type === "all");
    });
    renderPapers(state.papers);
    $("result-count").textContent = state.papers.length + " 篇文献";
    toast("调研完成，共 " + state.papers.length + " 篇文献");
  }

  function renderDecomposition(dec) {
    var h = "<p><strong>核心问题：</strong>" + esc(dec.core_question || "") + "</p>";

    var subs = dec.sub_topics || [];
    if (subs.length) {
      h += '<div class="decomp-grid">';
      subs.forEach(function (st) {
        h += '<div class="decomp-item"><h4>' + esc(st.aspect || st.name || "") + "</h4>";
        var items = st.methods || st.settings || [];
        if (items.length) {
          h += "<ul>" + items.map(function (it) { return "<li>" + esc(it) + "</li>"; }).join("") + "</ul>";
        }
        h += "</div>";
      });
      h += "</div>";
    }

    var groups = dec.keyword_groups || [];
    if (groups.length) {
      h += '<p style="margin-top:12px"><strong>关键词分组：</strong></p><div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:6px">';
      groups.forEach(function (g) {
        h += '<span class="type-tag" style="font-size:11px;padding:3px 8px">' + esc([].concat(g).join(" + ")) + "</span>";
      });
      h += "</div>";
    }

    if (dec.seed_suggestions) {
      h += '<p style="margin-top:12px;font-size:12px;color:var(--text-secondary)"><strong>建议：</strong>' +
           esc(dec.seed_suggestions) + "</p>";
    }
    $("decomposition-content").innerHTML = h;
  }

  function renderPapers(papers) {
    var box = $("paper-list");
    if (!papers.length) {
      box.innerHTML = '<div class="card" style="text-align:center;color:var(--text-secondary)">' +
        "没有符合条件的高质量文献。可以放宽主题、降低要求，或点击「补充检索」换个角度再试。</div>";
      return;
    }

    box.innerHTML = papers.map(function (p, i) {
      var url = safeUrl(p.url);
      var title = url
        ? '<a class="paper-title" href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' + esc(p.title || "Untitled") + "</a>"
        : '<span class="paper-title">' + esc(p.title || "Untitled") + "</span>";

      var authors = (p.authors && p.authors.length)
        ? esc(p.authors.slice(0, 4).join(", ")) + (p.authors.length > 4 ? " et al." : "")
        : "作者未知";

      return '<div class="paper-item" data-idx="' + i + '">' +
        '<div class="paper-header"><div style="flex:1;min-width:0">' + title +
          '<div class="paper-meta">' +
            '<span class="paper-authors" title="' + esc((p.authors || []).join(", ")) + '">' + authors + "</span>" +
            '<span class="badge-yr">' + esc(p.year || "n.d.") + "</span>" +
            '<span class="badge-cites">' + (p.citationCount || 0) + " 引用</span>" +
            '<span class="type-tag ' + esc(p.paper_type || "other") + '">' + esc(p.paper_type || "other") + "</span>" +
            '<span class="type-tag">' + esc(p.source || "") + "</span>" +
            (p.venue ? '<span class="type-tag">' + esc(p.venue) + "</span>" : "") +
          "</div>" +
        "</div>" +
        '<span class="score-badge score-' + (p.score || 3) + '">' + (p.score || 3) + "</span></div>" +
        (p.reason ? '<div class="paper-reason">' + esc(p.reason) + "</div>" : "") +
        '<button class="expand-btn" type="button" data-toggle="' + i + '">查看摘要</button>' +
        '<div class="paper-abstract">' + esc(p.abstract || "该来源未提供摘要。") + "</div>" +
      "</div>";
    }).join("");
  }

  function applyFilter(type) {
    state.filter = type;
    document.querySelectorAll(".filter-btn").forEach(function (b) {
      b.classList.toggle("active", b.dataset.type === type);
    });
    var list = type === "all" ? state.papers : state.papers.filter(function (p) { return p.paper_type === type; });
    renderPapers(list);
    $("result-count").textContent = type === "all"
      ? state.papers.length + " 篇文献"
      : list.length + " / " + state.papers.length + " 篇";
  }

  /* ── 补充检索 ─────────────────────────────────────────────── */
  function submitRefine() {
    var feedback = $("refine-feedback").value.trim();
    if (!feedback) { toast("请描述需要补充的方向", "error"); return; }
    if (!state.taskId) { toast("请先完成一次调研", "error"); return; }

    saveConfig();
    var kwRaw = $("refine-keywords").value.trim();
    var body = {
      task_id: state.taskId,
      feedback: feedback,
      new_keywords: kwRaw ? kwRaw.split(",").map(function (s) { return s.trim(); }).filter(Boolean) : [],
    };

    fetch(API_BASE + "/api/refine", { method: "POST", headers: headers(true), body: JSON.stringify(body) })
      .then(function (r) {
        if (!r.ok) return r.json().catch(function () { return {}; }).then(function (e) {
          throw new Error(e.detail || ("补充检索失败 " + r.status));
        });
        return r.json();
      })
      .then(function (d) {
        hide($("refine-panel"));
        hide($("results-panel"));
        show($("progress-panel"));
        resetPhases();
        $("progress-bar").style.width = "3%";
        $("progress-message").textContent = "补充检索已启动…";
        $("task-id").textContent = "#" + d.task_id;
        state.taskId = d.task_id;
        state.startedAt = Date.now();
        setSearching(true);
        startPolling();
      })
      .catch(function (err) { toast(err.message || "补充检索失败", "error"); });
  }

  /* ── 导出 ─────────────────────────────────────────────────── */
  function doExport(fmt) {
    if (!state.taskId) { toast("还没有可导出的结果", "error"); return; }
    fetch(API_BASE + "/api/export/" + state.taskId + "?fmt=" + encodeURIComponent(fmt), { headers: headers(false) })
      .then(function (r) {
        if (!r.ok) return r.json().catch(function () { return {}; }).then(function (e) {
          throw new Error(e.detail || ("导出失败 " + r.status));
        });
        return r.json();
      })
      .then(function (d) {
        var content = (fmt === "json") ? JSON.stringify(d, null, 2) : (d.content || "");
        state.exportFmt = fmt;
        $("export-content").value = content;
        $("export-title").textContent = "导出 " + fmt.toUpperCase() + " — " + (d.total_count || 0) + " 篇文献";
        show($("export-modal"));
      })
      .catch(function (err) { toast(err.message || "导出失败", "error"); });
  }

  function downloadExport() {
    var content = $("export-content").value;
    var ext = { json: "json", bibtex: "bib", markdown: "md", csv: "csv" }[state.exportFmt] || "txt";
    var blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "literature-survey-" + (state.taskId || "result") + "." + ext;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
  }

  function copyExport() {
    var ta = $("export-content");
    ta.removeAttribute("readonly");
    ta.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    ta.setAttribute("readonly", "readonly");
    if (!ok && navigator.clipboard) {
      navigator.clipboard.writeText(ta.value).then(function () { toast("已复制到剪贴板"); },
        function () { toast("复制失败，请手动选择复制", "error"); });
      return;
    }
    toast(ok ? "已复制到剪贴板" : "复制失败，请手动选择复制", ok ? "info" : "error");
  }

  /* ── 初始化 ───────────────────────────────────────────────── */
  function bindEvents() {
    $("btn-search").addEventListener("click", startSearch);

    $("llm-provider").addEventListener("change", function () {
      state.provider = this.value;
      renderModels(null);
      saveConfig();
      updateKeyBadge();
    });
    $("model-select").addEventListener("change", function () { state.model = this.value; saveConfig(); updateKeyBadge(); });
    $("api-key-input").addEventListener("change", function () { saveConfig(); updateKeyBadge(); });
    $("api-key-input").addEventListener("input", updateKeyBadge);
    $("api-key-input").addEventListener("blur", function () { saveConfig(); updateKeyBadge(); });
    $("iterations").addEventListener("change", saveConfig);

    document.querySelectorAll("[data-example]").forEach(function (el) {
      el.addEventListener("click", function () {
        $("topic-input").value = el.dataset.example;
        $("topic-input").focus();
      });
    });

    // 论文列表用事件委托：展开摘要
    $("paper-list").addEventListener("click", function (ev) {
      var btn = ev.target.closest(".expand-btn");
      if (!btn) return;
      var item = btn.closest(".paper-item");
      if (!item) return;
      item.classList.toggle("expanded");
      btn.textContent = item.classList.contains("expanded") ? "收起摘要" : "查看摘要";
    });

    document.querySelectorAll(".filter-btn").forEach(function (b) {
      b.addEventListener("click", function () { applyFilter(b.dataset.type); });
    });

    $("btn-refine").addEventListener("click", function () { show($("refine-panel")); });
    $("btn-refine-submit").addEventListener("click", submitRefine);
    $("btn-refine-cancel").addEventListener("click", function () { hide($("refine-panel")); });

    $("btn-export-json").addEventListener("click", function () { doExport("json"); });
    $("btn-export-bibtex").addEventListener("click", function () { doExport("bibtex"); });
    $("btn-export-md").addEventListener("click", function () { doExport("markdown"); });
    $("btn-export-csv").addEventListener("click", function () { doExport("csv"); });

    $("btn-close-export").addEventListener("click", function () { hide($("export-modal")); });
    $("btn-copy-export").addEventListener("click", copyExport);
    $("btn-download-export").addEventListener("click", downloadExport);
    $("export-modal").addEventListener("click", function (ev) {
      if (ev.target === $("export-modal")) hide($("export-modal"));
    });

    $("btn-copy-url").addEventListener("click", function () {
      var url = $("lan-url").textContent;
      if (!url || url.indexOf("http") !== 0) { toast("尚未检测到局域网地址", "error"); return; }
      if (navigator.clipboard) {
        navigator.clipboard.writeText(url).then(function () { toast("已复制：" + url); },
          function () { toast("复制失败，请手动复制", "error"); });
      } else {
        toast(url);
      }
    });

    // Ctrl/Cmd + Enter 快速提交
    $("topic-input").addEventListener("keydown", function (ev) {
      if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter") startSearch();
    });
  }

  function loadServerInfo() {
    fetch(API_BASE + "/api/config")
      .then(function (r) { return r.json(); })
      .then(function (cfg) {
        serverHasKey = !!cfg.server_key_configured;
        serverKeyForAnon = !!cfg.server_key_for_anonymous;
        updateKeyBadge();
        if (cfg.sources && cfg.sources.length) {
          $("src-badge").textContent = "数据源：" + cfg.sources.map(function (s) { return s.label; }).join(" · ");
        }
        if (cfg.recent_source_warnings && cfg.recent_source_warnings.length) {
          $("src-badge").title = cfg.recent_source_warnings.join("\n");
        }
      })
      .catch(function () { $("llm-badge").textContent = "LLM：状态未知"; });

    fetch(API_BASE + "/api/lanip")
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && d.ip && d.ip !== "unknown") {
          // 端口要按当前实际访问的端口来拼，不能写死 8765，
          // 否则换端口运行时这里会显示一个打不开的地址。
          $("lan-url").textContent = location.protocol + "//" + d.ip + ":" + (location.port || "80") + "/";
        } else {
          $("lan-url").textContent = location.origin + "/";
        }
      })
      .catch(function () { $("lan-url").textContent = location.origin + "/"; });
  }

  function init() {
    loadConfig();
    bindEvents();
    loadServerInfo();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
