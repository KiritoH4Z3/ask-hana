// Ask Hana front end. All text from the API or the model is written with textContent;
// citation chips are built as elements. Nothing here parses markup.
(function () {
  "use strict";

  var MAX = 500;
  var log = document.getElementById("log");
  var intro = document.getElementById("intro");
  var form = document.getElementById("ask");
  var box = document.getElementById("question");
  var send = document.getElementById("send");
  var count = document.getElementById("count");
  var badge = document.getElementById("mode-badge");
  var docsList = document.getElementById("docs");
  var knows = document.getElementById("knows");
  var toggle = document.getElementById("theme-toggle");
  var busy = false;
  var knownThreshold = 0.33;
  var seq = 0;
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  var coarse = window.matchMedia("(pointer: coarse)");

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  /* ---------- theme ---------- */
  function effectiveDark() {
    var t = document.documentElement.getAttribute("data-theme");
    if (t) return t === "dark";
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  }
  function syncToggle() {
    var dark = effectiveDark();
    toggle.setAttribute("aria-pressed", dark ? "true" : "false");
    toggle.textContent = dark ? "Night chart on" : "Night chart";
  }
  toggle.addEventListener("click", function () {
    var next = effectiveDark() ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("ask-hana-theme", next); } catch (e) { /* storage unavailable */ }
    syncToggle();
  });
  syncToggle();

  /* ---------- health and documents ---------- */
  function setBadge(h) {
    var text;
    if (!h) text = "Server not reachable";
    else if (h.mode === "claude") text = "Answers by " + (h.model || "Claude");
    else if (h.mode === "ollama") text = "Answers by local " + (h.model || "model");
    else text = "Quote mode: no model configured, answers are quoted from the documents";
    badge.textContent = text;
  }

  function getJSON(url) {
    return fetch(url, { headers: { Accept: "application/json" } }).then(function (r) {
      if (!r.ok) throw new Error("status " + r.status);
      return r.json();
    });
  }

  getJSON("api/health").then(function (h) { if (h && typeof h.threshold === "number") knownThreshold = h.threshold; setBadge(h); }).catch(function () { setBadge(null); });

  function renderDocs(data) {
    docsList.replaceChildren();
    var docs = (data && data.documents) || [];
    if (!docs.length) {
      docsList.appendChild(el("li", "msg", "No documents are indexed yet."));
      return;
    }
    docs.forEach(function (d) {
      var li = el("li");
      li.appendChild(el("strong", "", d.title || d.doc));
      if (d.sections && d.sections.length) li.appendChild(el("span", "sec", d.sections.join(", ")));
      li.appendChild(el("span", "count", d.chunks + " passages, " + d.words + " words"));
      docsList.appendChild(li);
    });
  }
  getJSON("api/documents").then(renderDocs).catch(function () {
    docsList.replaceChildren(el("li", "msg", "The document list could not be loaded."));
  });

  // Desktop shows the panel always open; phones keep it closed until asked.
  var wide = window.matchMedia("(min-width: 900px)");
  function syncKnows() { if (wide.matches) knows.setAttribute("open", ""); else knows.removeAttribute("open"); }
  syncKnows();
  if (wide.addEventListener) wide.addEventListener("change", syncKnows);

  /* ---------- rendering an answer ---------- */
  function jumpTo(target) {
    target.setAttribute("open", "");
    var summary = target.querySelector("summary");
    target.scrollIntoView({ block: "center", behavior: reduceMotion.matches ? "auto" : "smooth" });
    if (summary) summary.focus({ preventScroll: true });
    target.classList.add("flash");
    window.setTimeout(function () { target.classList.remove("flash"); }, 1600);
  }

  function chip(n, targetId) {
    var b = el("button", "cite", String(n));
    b.type = "button";
    b.setAttribute("aria-label", "Go to source " + n);
    b.addEventListener("click", function () {
      var t = document.getElementById(targetId);
      if (t) jumpTo(t);
    });
    return b;
  }

  function renderAnswerText(container, text, ids) {
    var re = /\[(\d+(?:\s*,\s*\d+)*)\]/g;
    var last = 0, m;
    while ((m = re.exec(text)) !== null) {
      var nums = m[1].split(",").map(function (s) { return parseInt(s.trim(), 10); });
      var ok = nums.every(function (n) { return ids[n]; });
      if (!ok) continue;
      if (m.index > last) container.appendChild(document.createTextNode(text.slice(last, m.index)));
      nums.forEach(function (n) { container.appendChild(chip(n, ids[n])); });
      last = m.index + m[0].length;
    }
    if (last < text.length) container.appendChild(document.createTextNode(text.slice(last)));
  }

  function fmt(score) { return Number(score).toFixed(3); }

  function renderSources(sources, threshold, grounded, xid, failed) {
    var wrap = el("section", "soundings");
    wrap.setAttribute("aria-label", "Sources for answer " + xid);
    wrap.appendChild(el("h2", "", failed ? "Passages it found" : grounded ? "Where this came from" : "Closest passages"));
    var cap = el("p", "caption");
    var th = Number(threshold);
    if (failed) {
      cap.appendChild(document.createTextNode("The search worked, but no answer was written. These are the passages ranked by similarity; the confidence line is at "));
      cap.appendChild(el("span", "num", th.toFixed(2)));
      cap.appendChild(document.createTextNode("."));
    } else if (grounded) {
      cap.appendChild(document.createTextNode("Passages ranked by similarity. Sources that reach the confidence line at "));
      cap.appendChild(el("span", "num", th.toFixed(2)));
      cap.appendChild(document.createTextNode(" were used. The rest sit below it."));
    } else {
      cap.appendChild(document.createTextNode("Nothing reached the confidence line at "));
      cap.appendChild(el("span", "num", th.toFixed(2)));
      cap.appendChild(document.createTextNode(", so no answer was written. These are the nearest passages."));
    }
    wrap.appendChild(cap);

    var ol = el("ol", "sources");
    var ids = {};
    sources.forEach(function (s) {
      var id = "src-" + xid + "-" + s.n;
      ids[s.n] = id;
      var li = el("li");
      var det = el("details", "src" + (s.used ? " used" : ""));
      det.id = id;
      var sum = el("summary");
      sum.appendChild(el("span", "n", String(s.n)));
      sum.appendChild(el("span", "where", s.doc + " > " + s.section));
      sum.appendChild(el("span", "score", fmt(s.score)));
      sum.appendChild(el("span", "state", s.used ? "Used" : "Below the line"));
      var g = el("span", "gauge");
      g.style.setProperty("--score", String(Math.max(0, Math.min(1, Number(s.score)))));
      g.style.setProperty("--threshold", String(Math.max(0, Math.min(1, th))));
      g.appendChild(el("span", "bar"));
      g.appendChild(el("span", "line"));
      sum.appendChild(g);
      det.appendChild(sum);
      det.appendChild(el("p", "passage", s.text));
      li.appendChild(det);
      ol.appendChild(li);
    });
    wrap.appendChild(ol);
    return { node: wrap, ids: ids };
  }

  function addExchange(question) {
    seq += 1;
    var ex = el("article", "exchange");
    var asked = el("p", "asked", "You asked");
    asked.appendChild(el("span", "q", question));
    ex.appendChild(asked);
    var slot = el("div", "slot");
    var wait = el("div", "waiting");
    var ping = el("span", "ping");
    ping.setAttribute("aria-hidden", "true");
    ping.appendChild(el("i"));
    wait.appendChild(ping);
    wait.appendChild(el("span", "", "Searching the documents"));
    slot.appendChild(wait);
    ex.appendChild(slot);
    log.appendChild(ex);
    intro.hidden = true;
    ex.scrollIntoView({ block: "start", behavior: reduceMotion.matches ? "auto" : "smooth" });
    return { ex: ex, slot: slot, id: seq };
  }

  function showAnswer(h, data) {
    var sources = data.sources || [];
    var rendered = renderSources(sources, data.threshold, data.grounded, h.id);
    var ans = el("div", "answer" + (data.grounded ? "" : " notfound"));
    renderAnswerText(ans, String(data.answer || ""), rendered.ids);
    h.slot.replaceChildren(ans);
    if (sources.length) h.slot.appendChild(rendered.node);
  }

  function showError(h, status, body, retryAfter) {
    var err = (body && body.error) || {};
    var msg = err.message || "Something went wrong on the server. Try again in a moment.";
    var n = el("div", "notice");
    n.appendChild(el("span", "tag", "Problem"));
    var t = el("p", "", msg);
    n.appendChild(t);
    h.slot.replaceChildren(n);
    var sources = body && body.sources;
    if (sources && sources.length) {
      var r = renderSources(sources, (body && body.threshold) || knownThreshold, false, h.id, true);
      h.slot.appendChild(r.node);
    }
    return err;
  }

  function showUnreachable(h) {
    var n = el("div", "notice");
    n.appendChild(el("span", "tag", "Problem"));
    var p = el("p", "", "Can't reach the server.");
    p.appendChild(el("span", "hint", "Check that ask-hana is running, then reload this page. Your question is back in the box."));
    n.appendChild(p);
    h.slot.replaceChildren(n);
    setBadge(null);
  }

  /* ---------- asking ---------- */
  function setBusy(b) {
    busy = b;
    send.disabled = b;
    send.textContent = b ? "Searching" : "Ask";
    log.setAttribute("aria-busy", b ? "true" : "false");
  }

  function ask(question) {
    question = question.trim();
    if (busy || !question) return;
    if (question.length > MAX) {
      box.setCustomValidity("Keep the question under " + MAX + " characters.");
      box.reportValidity();
      return;
    }
    setBusy(true);
    var h = addExchange(question);
    box.value = "";
    updateCount();
    var failed = false;
    fetch("api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ question: question })
    }).then(function (r) {
      return r.json().catch(function () { return null; }).then(function (body) { return { r: r, body: body }; });
    }).then(function (x) {
      /* A render exception is not a network failure: it gets the generic server message. */
      try {
        if (x.r.ok && x.body && typeof x.body.answer === "string") {
          showAnswer(h, x.body);
          if (x.body.mode) setBadge({ mode: x.body.mode, model: x.body.model });
        } else {
          failed = true;
          showError(h, x.r.status, x.body, x.r.headers.get("Retry-After"));
        }
      } catch (e) {
        failed = true;
        showError(h, 500, null, null);
      }
    }, function () {
      failed = true;
      showUnreachable(h);
    }).then(function () {
      /* Put the question back only if the visitor has not started typing something else. */
      if (failed && box.value.trim() === "") { box.value = question; updateCount(); }
      setBusy(false);
      if (!failed && !coarse.matches) box.focus({ preventScroll: true });
    });
  }

  function updateCount() {
    box.setCustomValidity("");
    var left = MAX - box.value.length;
    count.textContent = box.value.length >= 400 ? left + " characters left" : "";
  }

  form.addEventListener("submit", function (e) { e.preventDefault(); ask(box.value); });
  box.addEventListener("input", updateCount);
  box.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask(box.value); }
  });
  document.getElementById("suggest").addEventListener("click", function (e) {
    var b = e.target.closest("button[data-q]");
    if (b) ask(b.getAttribute("data-q"));
  });
})();
