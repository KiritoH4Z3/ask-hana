// Runs web/app.js against a small fake DOM and a scripted fetch. Prints one JSON line per scenario.
// No dependencies: Node 18+ only.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

class FakeEl {
  constructor(tag) {
    this.tag = tag; this.children = []; this.attrs = {}; this.handlers = {};
    this.value = ""; this.textContent = ""; this.className = ""; this.hidden = false;
    this.disabled = false; this.id = "";
    this.style = { setProperty() {} };
    const self = this;
    this.classList = { add(c) { self.className += " " + c; }, remove() {}, toggle() {}, contains() { return false; } };
    this.dataset = {};
  }
  appendChild(c) { this.children.push(c); return c; }
  replaceChildren(...c) { this.children = c; }
  remove() {}
  setAttribute(k, v) { this.attrs[k] = v; }
  getAttribute(k) { return this.attrs[k] === undefined ? null : this.attrs[k]; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(t, f) { (this.handlers[t] = this.handlers[t] || []).push(f); }
  scrollIntoView() {} focus() {} setCustomValidity() {} reportValidity() {}
  querySelector() { return new FakeEl("x"); }
  closest() { return null; }
  get text() { return this.textContent + this.children.map((c) => (c.text !== undefined ? c.text : String(c))).join(""); }
}

function run(scenario) {
  const els = {};
  const document = {
    getElementById(id) { return (els[id] = els[id] || Object.assign(new FakeEl("div"), { id })); },
    createElement(t) { return new FakeEl(t); },
    createTextNode(s) { return String(s); },
    documentElement: new FakeEl("html"),
    addEventListener() {},
  };
  const mq = () => ({ matches: false, addEventListener() {} });
  const sent = [];
  const fetch = (url, init) => {
    if (url !== "api/chat") return Promise.resolve({ ok: true, json: () => Promise.resolve(url === "api/health" ? { threshold: 0.33, mode: "extractive" } : { documents: [] }) });
    sent.push(init.body);
    return new Promise((r) => setTimeout(r, 15)).then(() => scenario.chat(els)); // health lands first
  };
  const ctx = { document, window: { matchMedia: mq, setTimeout, getComputedStyle: () => ({}) }, fetch, localStorage: { setItem() {}, getItem() { return null; } }, console, setTimeout, Promise };
  ctx.window.document = document;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8"), ctx);
  const box = els["question"];
  box.value = "What is her cat called?";
  els["ask"].handlers.submit[0]({ preventDefault() {} });
  return new Promise((resolve) => {
    scenario.during(els);
    setTimeout(() => resolve({ name: scenario.name, box: box.value, badge: els["mode-badge"].textContent, log: els["log"].children.map((c) => c.text).join(" | "), sent: sent.length }), 80);
  });
}

const reply = (ok, status, body) => () => Promise.resolve({ ok, status, headers: { get: () => null }, json: () => Promise.resolve(body) });
const scenarios = [
  { name: "server_error_keeps_new_draft", chat: reply(false, 503, { error: { message: "Busy." }, sources: [] }), during: (e) => { e["question"].value = "a follow up I am typing"; } },
  { name: "server_error_restores_empty_box", chat: reply(false, 503, { error: { message: "Busy." }, sources: [] }), during: () => {} },
  { name: "render_error_is_not_unreachable", chat: reply(true, 200, { answer: "x", grounded: true, threshold: 0.3, mode: "extractive", sources: [null] }), during: () => {} },
  { name: "network_failure_is_unreachable", chat: () => Promise.reject(new Error("down")), during: () => {} },
];
(async () => { for (const s of scenarios) console.log(JSON.stringify(await run(s))); })();
