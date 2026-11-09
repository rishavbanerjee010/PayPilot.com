/* =========================================================================
   PayPilot — app.js
   Vanilla JS single-page frontend. Talks to the FastAPI backend only.
   - Hash routing: #/home, #/explore, #/assistant, #/cart, #/orders
   - PayPal return routes: /checkout-success, /checkout-cancel (path-based)
   - Cart persists in localStorage; prices shown here are for display only —
     the backend always recomputes totals from its trusted catalogue.
   ========================================================================= */

"use strict";

/* ---------------------------- utilities ---------------------------- */

const INR = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

const fmt = (n) => INR.format(n);
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function stars(rating) {
  const full = Math.round(rating);
  return `<span class="star">${"★".repeat(full)}${"☆".repeat(5 - full)}</span> ${rating.toFixed(1)}`;
}

async function api(path, options = {}) {
  const opts = { headers: { "Content-Type": "application/json" }, ...options };
  if (opts.body && typeof opts.body !== "string") opts.body = JSON.stringify(opts.body);
  let resp;
  try {
    resp = await fetch(path, opts);
  } catch (err) {
    throw new Error("Network error: could not reach the PayPilot server. Is uvicorn running on port 8000?");
  }
  let data = null;
  try { data = await resp.json(); } catch { /* non-JSON */ }
  if (!resp.ok) {
    let msg = `Request failed (HTTP ${resp.status})`;
    if (data) {
      if (typeof data.detail === "string") msg = data.detail;
      else if (Array.isArray(data.detail)) {
        msg = data.detail.map((d) => `${(d.loc || []).slice(-1)[0] || "field"}: ${d.msg}`).join("; ");
      } else if (data.message) msg = data.message;
    }
    const err = new Error(msg);
    err.status = resp.status;
    throw err;
  }
  return data;
}

function toast(message, type = "ok") {
  const stack = $("#toastStack");
  const t = document.createElement("div");
  t.className = `toast ${type}`;
  t.textContent = message;
  stack.appendChild(t);
  setTimeout(() => { t.style.opacity = "0"; t.style.transition = "opacity .3s"; }, 2400);
  setTimeout(() => t.remove(), 2800);
}

/* ------------------------------ state ------------------------------ */

const state = {
  products: [],            // full catalogue from /api/products
  byId: new Map(),
  health: null,
  route: "home",
  explore: { q: "", category: "All", sort: "featured" },
  cart: loadCart(),        // [{id, qty}]
  compare: [],             // product ids, max 3
  chat: [],                // {role:'user'|'assistant', content, products?, tools?, error?}
  chatBusy: false,
  lastChatError: null,
  pendingQuestion: null,
  checkoutHandled: false,
};

function loadCart() {
  try {
    const raw = JSON.parse(localStorage.getItem("paypilot_cart_v1") || "[]");
    if (!Array.isArray(raw)) return [];
    return raw
      .filter((l) => l && typeof l.id === "string" && Number.isInteger(l.qty) && l.qty >= 1 && l.qty <= 99)
      .map((l) => ({ id: l.id, qty: l.qty }));
  } catch { return []; }
}
function saveCart() {
  localStorage.setItem("paypilot_cart_v1", JSON.stringify(state.cart));
  updateCartBadge();
}
function cartCount() { return state.cart.reduce((s, l) => s + l.qty, 0); }
function cartTotal() {
  return state.cart.reduce((s, l) => {
    const p = state.byId.get(l.id);
    return s + (p ? p.price_inr * l.qty : 0);
  }, 0);
}
function addToCart(id, qty = 1) {
  const p = state.byId.get(id);
  if (!p) return;
  if (p.stock < qty + (state.cart.find((l) => l.id === id)?.qty || 0)) {
    toast(`Only ${p.stock} in stock`, "err");
    return;
  }
  const line = state.cart.find((l) => l.id === id);
  if (line) line.qty = Math.min(99, line.qty + qty);
  else state.cart.push({ id, qty });
  saveCart();
  toast(`Added ${p.name} to cart`);
  if (state.route === "cart") render();
}
function setQty(id, qty) {
  const line = state.cart.find((l) => l.id === id);
  if (!line) return;
  if (qty < 1) { state.cart = state.cart.filter((l) => l.id !== id); toast("Item removed from cart", "info"); }
  else {
    const p = state.byId.get(id);
    if (p && qty > p.stock) { toast(`Only ${p.stock} in stock`, "err"); return; }
    line.qty = Math.min(99, qty);
  }
  saveCart();
  if (state.route === "cart") render();
}
function updateCartBadge() {
  const badge = $("#cartBadge");
  const n = cartCount();
  badge.hidden = n === 0;
  badge.textContent = n > 99 ? "99+" : n;
}

/* --------------------------- compare tray --------------------------- */

function toggleCompare(id) {
  const i = state.compare.indexOf(id);
  if (i >= 0) state.compare.splice(i, 1);
  else {
    if (state.compare.length >= 3) { toast("You can compare up to 3 products", "err"); return; }
    state.compare.push(id);
  }
  syncCompareUI();
}
function syncCompareUI() {
  const tray = $("#compareTray");
  const items = $("#compareTrayItems");
  const n = state.compare.length;
  tray.hidden = n === 0;
  $("#compareCount").textContent = n;
  items.innerHTML = state.compare.map((id) => {
    const p = state.byId.get(id);
    return `<div class="tray-item" title="${esc(p?.name || id)}">
      <img src="${p?.image}" alt="${esc(p?.name || "")}"
           onerror="this.onerror=null;this.src='/assets/products/${p?.id}.svg'" />
      <button class="x" data-cmp-x="${id}" aria-label="Remove ${esc(p?.name || id)} from comparison">✕</button>
    </div>`;
  }).join("");
  $$(".pc-compare-check").forEach((b) => {
    const on = state.compare.includes(b.dataset.cmp);
    b.classList.toggle("on", on);
    b.innerHTML = on ? "✓" : "<svg viewBox='0 0 24 24' width='16' height='16' fill='none' stroke='currentColor' stroke-width='2.4' stroke-linecap='round'><path d='M8 3v4M16 3v4M3 9h18M5 5h14a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z'/></svg>";
  });
}

/* ----------------------------- templates ---------------------------- */

function productCard(p, opts = {}) {
  const inCompare = state.compare.includes(p.id);
  const specs = Object.entries(p.specs || p.key_specs || {}).slice(0, 3)
    .map(([k, v]) => `<span class="pc-spec" title="${esc(`${k}: ${v}`)}">${esc(v)}</span>`).join("");
  return `<article class="product-card" data-card="${p.id}">
    <div class="pc-media" data-open="${p.id}" role="button" tabindex="0" aria-label="View ${esc(p.name)} details">
      ${p.featured ? '<span class="pc-flag">★ Featured</span>' : ""}
      <img src="${p.image}" alt="${esc(p.name)}" loading="lazy"
           onerror="this.onerror=null;this.src='/assets/products/${p.id}.svg'" />
      <button class="pc-compare-check ${inCompare ? "on" : ""}" data-cmp="${p.id}" title="Add to comparison"
              aria-label="Compare ${esc(p.name)}">${inCompare ? "✓" : ""}</button>
    </div>
    <div class="pc-body">
      <div class="pc-top">
        <span class="pc-cat">${esc(p.category)}</span>
        <span class="pc-rating">${stars(p.rating)}</span>
      </div>
      <h3 class="pc-name" data-open="${p.id}">${esc(p.name)}</h3>
      <p class="pc-desc">${esc(p.short_description)}</p>
      <div class="pc-specs">${specs}</div>
      <div class="pc-bottom">
        <div class="pc-price">${fmt(p.price_inr)}<small>incl. all taxes</small></div>
        <div class="pc-actions">
          <button class="btn btn-primary btn-sm" data-add="${p.id}">Add to Cart</button>
        </div>
      </div>
    </div>
  </article>`;
}

function productModal(p) {
  const specs = Object.entries(p.specs || {}).map(
    ([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`
  ).join("");
  openModal(`<div class="modal-head">
      <h3>${esc(p.name)}</h3>
      <button class="modal-close" data-close aria-label="Close">✕</button>
    </div>
    <div class="modal-body"><div class="pm-grid">
      <div>
        <img src="${p.image}" alt="${esc(p.name)}"
             onerror="this.onerror=null;this.src='/assets/products/${p.id}.svg'" />
        <div class="pm-price" style="margin-top:12px">${fmt(p.price_inr)}</div>
        <button class="btn btn-primary btn-block" data-add="${p.id}">Add to Cart</button>
        <p style="font-size:12px;color:var(--muted);margin-top:9px">${p.stock > 15 ? "In stock" : `Only ${p.stock} left in stock`} · ${p.num_reviews.toLocaleString("en-IN")} reviews</p>
      </div>
      <div>
        <div class="pc-top" style="margin-bottom:8px">
          <span class="pc-cat">${esc(p.category)}</span>
          <span class="pc-rating">${stars(p.rating)}</span>
        </div>
        <p class="pm-desc">${esc(p.description)}</p>
        <div class="bestfor">${p.best_for.map((b) => `<span>Great for: ${esc(b)}</span>`).join("")}</div>
        <table class="spec-table"><tbody>${specs}</tbody></table>
      </div>
    </div></div>`);
}

function compareModal() {
  const ps = state.compare.map((id) => state.byId.get(id)).filter(Boolean);
  if (ps.length < 2) { toast("Select at least 2 products to compare", "err"); return; }
  const specKeys = [...new Set(ps.flatMap((p) => Object.keys(p.specs || {})))];
  const minPrice = Math.min(...ps.map((p) => p.price_inr));
  const maxRating = Math.max(...ps.map((p) => p.rating));
  const head = ps.map((p) => `<th class="cmp-prod">
      <img src="${p.image}" alt="${esc(p.name)}" data-open="${p.id}" style="cursor:pointer"
           onerror="this.onerror=null;this.src='/assets/products/${p.id}.svg'" />
      <div class="cmp-name" data-open="${p.id}" style="cursor:pointer">${esc(p.name)}</div>
      <div class="cmp-price ${p.price_inr === minPrice ? "cmp-cheap" : ""}">${fmt(p.price_inr)}</div>
    </th>`).join("");
  const row = (label, cells) => `<tr><td class="rowlabel">${label}</td>${cells}</tr>`;
  const body = [
    row("Category", ps.map((p) => `<td>${esc(p.category)}</td>`).join("")),
    row("Rating", ps.map((p) => `<td class="${p.rating === maxRating ? "win" : ""}">${stars(p.rating)} · ${p.num_reviews.toLocaleString("en-IN")} reviews</td>`).join("")),
    row("Best for", ps.map((p) => `<td>${p.best_for.map(esc).join(", ")}</td>`).join("")),
    row("Availability", ps.map((p) => `<td>${p.stock > 15 ? "In stock" : `Only ${p.stock} left`}</td>`).join("")),
    ...specKeys.map((k) => row(esc(k), ps.map((p) => `<td>${esc(p.specs?.[k] ?? "—")}</td>`).join(""))),
    row("", ps.map((p) => `<td><button class="btn btn-primary btn-sm" data-add="${p.id}">Add to Cart</button></td>`).join("")),
  ].join("");
  openModal(`<div class="modal-head">
      <h3>Product comparison</h3>
      <button class="modal-close" data-close aria-label="Close">✕</button>
    </div>
    <div class="modal-body"><div class="cmp-wrap">
      <table class="cmp-table">
        <thead><tr><td class="rowlabel"></td>${head}</tr></thead>
        <tbody>${body}</tbody>
      </table>
      <p style="font-size:12px;color:var(--muted);margin-top:12px">Cheapest price and highest rating are highlighted. All data comes from the PayPilot catalogue.</p>
    </div></div>`);
}

/* ------------------------------- modal ------------------------------ */

function openModal(html) {
  $("#modalContent").innerHTML = html;
  const bd = $("#modalBackdrop");
  bd.hidden = false;
  document.body.style.overflow = "hidden";
}
function closeModal() {
  $("#modalBackdrop").hidden = true;
  document.body.style.overflow = "";
}

/* =============================== VIEWS ============================== */

const view = () => $("#view");

function render() {
  const r = state.route;
  $$(".nav-links a").forEach((a) => a.classList.toggle("active", a.dataset.nav === r));
  $("#navLinks").classList.remove("open");
  $("#navToggle").classList.remove("open");
  if (r === "home") renderHome();
  else if (r === "explore") renderExplore();
  else if (r === "assistant") renderAssistant();
  else if (r === "cart") renderCart();
  else if (r === "orders") renderOrders();
  window.scrollTo({ top: 0 });
  syncCompareUI();
}

/* ------------------------------- HOME ------------------------------- */

function renderHome() {
  const products = state.products;
  const featured = products.filter((p) => p.featured).slice(0, 6);
  const cats = [...new Set(products.map((p) => p.category))].map((c) => ({
    name: c,
    count: products.filter((p) => p.category === c).length,
    emoji: {
      Electronics: "🎧", Smartphones: "📱", Laptops: "💻",
      Accessories: "🖱️", Fashion: "👕", "Home & Lifestyle": "🏠",
      Appliances: "🔌", "Beauty & Personal Care": "💄", "Sports & Fitness": "🏏",
    }[c] || "🛍️",
  }));
  view().innerHTML = `
    <section class="hero">
      <div class="hero-chip chip-1">✈️ AI recommendations<small>grounded in a real catalogue</small></div>
      <div class="hero-chip chip-2">🔒 Server-verified totals<small>you pay what you see</small></div>
      <div class="hero-chip chip-3">💳 PayPal checkout<small>Sandbox demo · INR store</small></div>
      <div class="hero-inner">
        <span class="hero-eyebrow">✦ POWERED BY OPENAI × PAYPAL</span>
        <h1>Shopping Smarter Starts Here.</h1>
        <p class="sub">PayPilot is your AI-powered shopping companion. Describe what you need — in plain English, with your ₹ budget — and get honest recommendations, side-by-side comparisons and a secure checkout.</p>
        <div class="hero-cta">
          <a class="btn btn-white btn-lg" href="#/assistant">💬 Chat with the AI Assistant</a>
          <a class="btn btn-glass btn-lg" href="#/explore">Explore Products →</a>
        </div>
        <div class="hero-search">
          <div class="search-box">
            <svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
            <input id="heroSearch" type="search" placeholder="Search the catalogue — try “laptop”, “headphones”, “watch”…" aria-label="Search products" />
            <button class="btn btn-primary" id="heroSearchBtn">Search</button>
          </div>
        </div>
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <div><h2>Popular categories</h2><p>Everything priced in ₹ with Indian-market pricing.</p></div>
      </div>
      <div class="cat-grid">
        ${cats.map((c) => `<button class="cat-card" data-cat="${esc(c.name)}">
          <span class="cat-emoji">${c.emoji}</span><h3>${esc(c.name)}</h3>
          <span class="count">${c.count} products</span>
        </button>`).join("")}
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <div><h2>Featured products</h2><p>Hand-picked favourites from the catalogue.</p></div>
        <a class="link" href="#/explore">View all ${products.length} products →</a>
      </div>
      <div class="grid">${featured.map((p) => productCard(p)).join("")}</div>
    </section>

    <section class="section">
      <div class="section-head">
        <div><h2>How PayPilot works</h2><p>From question to checkout in four steps.</p></div>
      </div>
      <div class="steps">
        <div class="step"><div class="step-num">1</div><h3>Ask the AI assistant</h3><p>“Find me a laptop under ₹60,000 for programming.” The AI reads your budget and needs — it only recommends what actually exists.</p></div>
        <div class="step"><div class="step-num">2</div><h3>Compare with real data</h3><p>Prices, specs, pros and cons come from function calls against the live catalogue — never invented.</p></div>
        <div class="step"><div class="step-num">3</div><h3>Build your cart</h3><p>Add items, adjust quantities, and your ₹ subtotal updates instantly. It survives page refreshes.</p></div>
        <div class="step"><div class="step-num">4</div><h3>Check out securely</h3><p>The server re-verifies every price, then hands you to PayPal Sandbox. Success shows only after a verified capture.</p></div>
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <div><h2>Trust &amp; security</h2><p>Built-in, not bolted on.</p></div>
      </div>
      <div class="trust-grid">
        <div class="trust"><div class="icon"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg></div>
          <div><h3>Server-verified totals</h3><p>Cart amounts are always recalculated on the backend from the trusted catalogue. The browser never dictates a price.</p></div></div>
        <div class="trust"><div class="icon"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="5" width="20" height="14" rx="3"/><path d="M2 10h20"/></svg></div>
          <div><h3>PayPal Sandbox checkout</h3><p>Payments use the official PayPal Orders v2 flow: create → buyer approval → server-side capture with amount and currency verification.</p></div></div>
        <div class="trust"><div class="icon"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg></div>
          <div><h3>No card data stored</h3><p>Card details never touch PayPilot — they stay with PayPal. Only order IDs, items and verified totals are saved in SQLite.</p></div></div>
        <div class="trust"><div class="icon"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a4 4 0 0 1 4 4c0 1.1-.45 2.1-1.17 2.83L12 12l-2.83-3.17A4 4 0 0 1 12 2z"/><path d="M12 12v10M8 22h8"/></svg></div>
          <div><h3>Catalogue-grounded AI</h3><p>Every recommendation comes from tool calls over the real product database. If it isn’t in the catalogue, the AI says so.</p></div></div>
      </div>
    </section>`;

  const doHeroSearch = () => {
    const q = $("#heroSearch").value.trim();
    state.explore.q = q;
    state.explore.category = "All";
    location.hash = "#/explore";
  };
  $("#heroSearchBtn").addEventListener("click", doHeroSearch);
  $("#heroSearch").addEventListener("keydown", (e) => { if (e.key === "Enter") doHeroSearch(); });
  $$(".cat-card", view()).forEach((c) => c.addEventListener("click", () => {
    state.explore.category = c.dataset.cat;
    state.explore.q = "";
    location.hash = "#/explore";
  }));
}

/* ------------------------------ EXPLORE ----------------------------- */

function renderExplore() {
  const { q, category, sort } = state.explore;
  let list = [...state.products];
  if (category !== "All") list = list.filter((p) => p.category === category);
  if (q.trim()) {
    const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
    list = list.filter((p) => {
      const hay = `${p.name} ${p.category} ${p.short_description} ${p.description || ""} ${p.best_for.join(" ")} ${Object.entries(p.specs || {}).flat().join(" ")}`.toLowerCase();
      return terms.every((t) => hay.includes(t));
    });
  }
  if (sort === "price-asc") list.sort((a, b) => a.price_inr - b.price_inr);
  else if (sort === "price-desc") list.sort((a, b) => b.price_inr - a.price_inr);
  else if (sort === "rating") list.sort((a, b) => b.rating - a.rating);

  const cats = ["All", ...new Set(state.products.map((p) => p.category))];
  view().innerHTML = `
    <div class="page-head"><h1>Explore Products</h1>
      <p>Browse all ${state.products.length} products in the catalogue — every price in ₹, verified by the server.</p></div>
    <div class="toolbar">
      <div class="search-box">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
        <input id="exploreSearch" type="search" placeholder="Search products…" value="${esc(q)}" aria-label="Search products" />
      </div>
      <select id="exploreSort" aria-label="Sort products">
        <option value="featured" ${sort === "featured" ? "selected" : ""}>Sort: Featured</option>
        <option value="price-asc" ${sort === "price-asc" ? "selected" : ""}>Price: Low → High</option>
        <option value="price-desc" ${sort === "price-desc" ? "selected" : ""}>Price: High → Low</option>
        <option value="rating" ${sort === "rating" ? "selected" : ""}>Highest rated</option>
      </select>
    </div>
    <div class="chip-row">
      ${cats.map((c) => `<button class="chip ${c === category ? "active" : ""}" data-filter="${esc(c)}">${esc(c)}</button>`).join("")}
    </div>
    <p class="results-meta">Showing <strong>${list.length}</strong> of ${state.products.length} products${category !== "All" ? ` in <strong>${esc(category)}</strong>` : ""}${q ? ` for “<strong>${esc(q)}</strong>”` : ""}.</p>
    ${list.length ? `<div class="grid">${list.map((p) => productCard(p)).join("")}</div>` : `
      <div class="empty-state"><div class="big">🔍</div><h3>No products match your search</h3>
        <p>Try a different keyword, or ask the AI assistant — it can suggest alternatives.</p>
        <a class="btn btn-primary" href="#/assistant">Ask the AI Assistant</a></div>`}`;

  $("#exploreSearch").addEventListener("input", (e) => {
    state.explore.q = e.target.value;
    const pos = e.target.selectionStart;
    renderExplore();
    const inp = $("#exploreSearch");
    inp.focus(); inp.setSelectionRange(pos, pos);
  });
  $("#exploreSort").addEventListener("change", (e) => { state.explore.sort = e.target.value; renderExplore(); });
  $$("[data-filter]", view()).forEach((b) => b.addEventListener("click", () => {
    state.explore.category = b.dataset.filter; renderExplore();
  }));
}

/* ---------------------------- AI ASSISTANT -------------------------- */

const SUGGESTIONS = [
  "Find the best laptop under ₹60,000",
  "Compare two smartphones under ₹40,000",
  "Recommend wireless headphones",
  "Find products suitable for students",
];

function chatHistoryForApi() {
  return state.chat
    .filter((m) => (m.role === "user" || (m.role === "assistant" && !m.error)) && m.content)
    .slice(-10)
    .map((m) => ({ role: m.role, content: m.content }));
}

function renderAssistant() {
  const aiOk = state.health?.openai_configured;
  view().innerHTML = `
    <div class="page-head"><h1>AI Shopping Assistant</h1>
      <p>Your personal shopping companion — recommendations, comparisons and budget help, grounded in the real catalogue.</p></div>
    ${aiOk === false ? `<div class="alert alert-warning"><strong>AI is not configured on the server.</strong> Add your <code>OPENAI_API_KEY</code> to <code>backend/.env</code> and restart uvicorn — see README.md → OpenAI setup. Everything else (browsing, cart, checkout) still works.</div>` : ""}
    <div class="chat-wrap">
      <div class="chat-panel">
        <div class="chat-head">
          <div class="chat-avatar"><svg viewBox="0 0 64 64" width="24" height="24"><path d="M9 31.5 L54 9 L40.5 55 L29.5 41.5 L9 31.5 Z" fill="#fff"/></svg></div>
          <div class="chat-head-info"><h3>PayPilot Assistant</h3><span><span class="dot"></span>Online · catalogue-grounded · ₹ budgets</span></div>
          <button class="btn btn-ghost btn-sm" id="clearChat">🗑 Clear chat</button>
        </div>
        <div class="chat-log" id="chatLog"></div>
        <div class="chat-inputbar">
          <input id="chatInput" type="text" maxlength="2000" placeholder="Ask anything — “best laptop under ₹60,000?”" aria-label="Message the assistant" />
          <button class="chat-send" id="chatSend" aria-label="Send message">
            <svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/></svg>
          </button>
        </div>
      </div>
      <aside class="chat-side">
        <div class="side-card">
          <h4>💡 Try asking</h4>
          ${SUGGESTIONS.map((s) => `<button class="suggest-btn" data-suggest="${esc(s)}">${esc(s)}</button>`).join("")}
        </div>
        <div class="side-card">
          <h4>🧠 How it works</h4>
          <p class="side-note">The assistant runs on your backend with the <strong>OpenAI Responses API</strong> and three real function tools — <strong>search_catalogue</strong>, <strong>compare_products</strong> and <strong>get_product_details</strong>. It can only recommend products that exist in the catalogue, with real ₹ prices. Tool calls used for an answer are shown under it.</p>
        </div>
        <div class="side-card">
          <h4>🔒 Good to know</h4>
          <p class="side-note">The assistant can help you choose, but it can never place an order or confirm a payment — checkout and capture happen only through the app with server-side verification.</p>
        </div>
      </aside>
    </div>`;

  renderChatLog();
  $("#chatSend").addEventListener("click", sendChat);
  $("#chatInput").addEventListener("keydown", (e) => { if (e.key === "Enter") sendChat(); });
  $("#clearChat").addEventListener("click", () => {
    state.chat = [];
    renderChatLog();
  });
  $$("[data-suggest]", view()).forEach((b) => b.addEventListener("click", () => {
    $("#chatInput").value = b.dataset.suggest;
    sendChat();
  }));
  if (state.pendingQuestion) {
    $("#chatInput").value = state.pendingQuestion;
    state.pendingQuestion = null;
    $("#chatInput").focus();
  }
}

function renderChatLog() {
  const log = $("#chatLog");
  if (!log) return;
  if (state.chat.length === 0) {
    state.chat.push({
      role: "assistant",
      content: "Hi! I'm PayPilot, your personal AI shopping assistant. Tell me what you're looking for, and I'll help you find the right product.",
    });
  }
  log.innerHTML = state.chat.map((m, i) => messageHtml(m, i)).join("") + typingHtml();
  log.scrollTop = log.scrollHeight;
}

function typingHtml() {
  if (!state.chatBusy) return "";
  return `<div class="msg ai"><div class="msg-av">✈</div>
    <div class="msg-body"><div class="msg-bubble typing"><i></i><i></i><i></i></div></div></div>`;
}

function messageHtml(m, i) {
  const av = m.role === "user" ? "You" : "✈";
  let inner = `<div class="msg-bubble">${esc(m.content)}</div>`;
  if (m.error) {
    inner += `<button class="btn btn-outline btn-sm" data-retry>↻ Retry</button>`;
  }
  if (m.role === "assistant" && m.products?.length) {
    inner += `<div class="chat-cards">${m.products.map((p) => `
      <div class="chat-card">
        <img src="${p.image}" alt="${esc(p.name)}" data-open="${p.id}"
             onerror="this.onerror=null;this.src='/assets/products/${p.id}.svg'" />
        <div class="cc-body">
          <div class="cc-name" data-open="${p.id}">${esc(p.name)}</div>
          <span class="pc-cat">${esc(p.category)}</span>
          <div class="cc-price">${fmt(p.price_inr)}</div>
          <button class="btn btn-primary btn-sm" data-add="${p.id}">Add to Cart</button>
        </div>
      </div>`).join("")}</div>`;
  }
  if (m.role === "assistant" && m.tools?.length) {
    inner += `<div class="msg-tools">🔧 Tools used: ${m.tools.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>`;
  }
  const roleClass = m.role === "user" ? "user" : "ai";
  return `<div class="msg ${roleClass} ${m.error ? "error" : ""}" data-msg="${i}">
    <div class="msg-av">${av}</div><div class="msg-body">${inner}</div></div>`;
}

async function sendChat() {
  const input = $("#chatInput");
  const text = input.value.trim();
  if (!text || state.chatBusy) return;
  input.value = "";
  state.chat.push({ role: "user", content: text });
  state.chatBusy = true;
  renderChatLog();
  try {
    const res = await api("/api/agent/chat", {
      method: "POST",
      body: { message: text, history: chatHistoryForApi().slice(0, -1) },
    });
    state.chat.push({ role: "assistant", content: res.reply, products: res.products, tools: res.tool_calls });
  } catch (err) {
    state.chat.push({ role: "assistant", content: err.message, error: true });
  } finally {
    state.chatBusy = false;
    renderChatLog();
  }
}

/* -------------------------------- CART ------------------------------ */

function renderCart() {
  const lines = state.cart
    .map((l) => ({ ...l, p: state.byId.get(l.id) }))
    .filter((l) => l.p);
  const subtotal = cartTotal();

  if (!lines.length) {
    view().innerHTML = `
      <div class="page-head"><h1>Your Cart</h1></div>
      <div class="empty-state"><div class="big">🛒</div><h3>Your cart is empty</h3>
        <p>Add some products first — or let the AI assistant find the perfect item for you.</p>
        <div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap">
          <a class="btn btn-primary" href="#/explore">Browse products</a>
          <a class="btn btn-outline" href="#/assistant">Ask the AI</a>
        </div></div>`;
    return;
  }

  view().innerHTML = `
    <div class="page-head"><h1>Your Cart</h1><p>${cartCount()} item(s) — stored in your browser, so it survives refreshes.</p></div>
    <div id="cartAlert"></div>
    <div class="cart-layout">
      <div class="cart-list">
        ${lines.map(({ p, qty }) => `
          <div class="cart-line">
            <img src="${p.image}" alt="${esc(p.name)}" data-open="${p.id}"
                 onerror="this.onerror=null;this.src='/assets/products/${p.id}.svg'" />
            <div class="cl-info">
              <div class="cl-name" data-open="${p.id}">${esc(p.name)}</div>
              <span class="cl-cat">${esc(p.category)} · ${stars(p.rating)}</span>
              <span class="cl-unit">${fmt(p.price_inr)} each</span>
            </div>
            <div class="cl-right">
              <div class="qty">
                <button data-qty="${p.id}" data-n="${qty - 1}" aria-label="Decrease quantity">−</button>
                <span>${qty}</span>
                <button data-qty="${p.id}" data-n="${qty + 1}" aria-label="Increase quantity">+</button>
              </div>
              <div class="cl-total">${fmt(p.price_inr * qty)}</div>
              <button class="btn btn-danger btn-sm" data-remove="${p.id}">Remove</button>
            </div>
          </div>`).join("")}
      </div>
      <aside class="summary">
        <h3>Order summary</h3>
        ${lines.map(({ p, qty }) => `<div class="sum-row"><span>${esc(p.name)} × ${qty}</span><span class="val">${fmt(p.price_inr * qty)}</span></div>`).join("")}
        <div class="sum-row total"><span>Total</span><span>${fmt(subtotal)}</span></div>
        ${state.health && state.health.currency !== "INR" ? `<div class="sum-note"><span>ℹ️</span><span>Store prices are in ₹. Because PayPal does not support INR, this server is configured to check out in <strong>${esc(state.health.currency)}</strong> for the same numeric amount (Sandbox demo funds only). See README → “Currency note (INR)”.</span></div>` : ""}
        <div class="sum-note"><span>🛡️</span><span>Before checkout, the server re-validates every item and <strong>recalculates this total from its own catalogue</strong>. The browser price is never trusted.</span></div>
        <button class="btn btn-primary btn-lg btn-block" id="checkoutBtn">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="5" width="20" height="14" rx="3"/><path d="M2 10h20"/><path d="M6 15h4"/></svg>
          Checkout with PayPal
        </button>
        <p style="font-size:11.5px;color:var(--muted);text-align:center;margin-top:10px">PayPal <strong>Sandbox</strong> — test mode, no real money.</p>
      </aside>
    </div>`;

  $$("[data-qty]", view()).forEach((b) => b.addEventListener("click", () => setQty(b.dataset.qty, +b.dataset.n)));
  $$("[data-remove]", view()).forEach((b) => b.addEventListener("click", () => {
    state.cart = state.cart.filter((l) => l.id !== b.dataset.remove);
    saveCart(); toast("Item removed from cart", "info"); render();
  }));
  $("#checkoutBtn").addEventListener("click", startCheckout);
}

async function startCheckout() {
  const btn = $("#checkoutBtn");
  if (!state.cart.length) { toast("Your cart is empty", "err"); return; }
  const alertBox = $("#cartAlert");
  alertBox.innerHTML = "";
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span> Creating your PayPal order…`;
  try {
    const res = await api("/api/payments/create-order", {
      method: "POST",
      body: { items: state.cart.map((l) => ({ product_id: l.id, quantity: l.qty })) },
    });
    // Hand over to PayPal for buyer approval.
    window.location.href = res.approval_url;
  } catch (err) {
    btn.disabled = false;
    btn.innerHTML = `Checkout with PayPal`;
    const isInr = /INR|currency/i.test(err.message);
    alertBox.innerHTML = `<div class="alert alert-error"><strong>Checkout could not start.</strong><br/>${esc(err.message)}
      ${isInr ? `<br/><br/>PayPilot never silently converts your ₹ total — see README.md → “Currency note (INR)” for your options.` : ""}</div>`;
    alertBox.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

/* ------------------------------- ORDERS ----------------------------- */

async function renderOrders() {
  view().innerHTML = `<div class="page-head"><h1>Orders &amp; Transactions</h1>
      <p>Your order history with payment status (demo user — authentication is not part of this demo).</p></div>
    <div id="ordersList"><div class="skel-card skeleton"></div>`;
  let orders;
  try {
    orders = await api("/api/orders");
  } catch (err) {
    $("#ordersList").innerHTML = `<div class="alert alert-error">${esc(err.message)}</div>`;
    return;
  }
  if (!orders.length) {
    $("#ordersList").innerHTML = `<div class="empty-state"><div class="big">📦</div>
      <h3>No orders yet</h3><p>Complete a PayPal Sandbox checkout and it will appear here with its full payment trail.</p>
      <a class="btn btn-primary" href="#/explore">Start shopping</a></div>`;
    return;
  }
  $("#ordersList").innerHTML = orders.map((o) => `
    <div class="order-card">
      <div class="order-top">
        <span class="order-id">${esc(o.order_id)}</span>
        <span class="status-pill st-${esc(o.payment_status)}">${esc(o.payment_status)}</span>
        ${o.failure_reason ? `<span style="font-size:11.5px;color:var(--danger)">${esc(o.failure_reason).slice(0, 140)}</span>` : ""}
        <span class="order-date">${new Date(o.created_at + "Z").toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</span>
        <span class="order-total">${fmt(o.total_amount)}</span>
      </div>
      <div class="order-items">
        ${o.items.map((it) => `<div class="oi-row">
          <span class="oi-name">${esc(it.product_name)} × ${it.quantity}</span>
          <span>${fmt(it.line_total)}</span></div>`).join("")}
      </div>
      <div class="order-meta">
        ${o.paypal_order_id ? `<span>PayPal order: <strong>${esc(o.paypal_order_id)}</strong></span>` : ""}
        ${o.capture_id ? `<span>Capture: <strong>${esc(o.capture_id)}</strong></span>` : ""}
        ${o.payer_email ? `<span>Payer: <strong>${esc(o.payer_email)}</strong></span>` : ""}
      </div>
    </div>`).join("");
}

/* -------------------------- CHECKOUT RESULTS ------------------------ */

async function checkoutSuccess() {
  const params = new URLSearchParams(location.search);
  const token = params.get("token");
  view().innerHTML = `
    <div class="result-hero" id="resultHero">
      <div class="result-icon wait"><span class="spinner spinner-dark" style="width:30px;height:30px;border-width:3.5px"></span></div>
      <h2>Confirming your payment…</h2>
      <p class="sub">Hold on — we're verifying the capture with PayPal before showing any result.</p>
    </div>`;
  if (!token) {
    showResult(false, "Missing payment reference", "This page was opened without a PayPal order token. Please start again from your cart.");
    return;
  }
  try {
    const res = await api("/api/payments/capture-order", {
      method: "POST",
      body: { paypal_order_id: token },
    });
    if (res.success && res.order) {
      const o = res.order;
      showResult(true, res.already_completed ? "Payment already confirmed" : "Payment successful! 🎉",
        `${res.message} Your order <strong>${esc(o.order_id)}</strong> is confirmed and saved to your history.`,
        receiptHtml(o));
      state.cart = [];
      saveCart();
    } else {
      showResult(false, "Payment not completed", res.message || "The capture did not complete.");
    }
  } catch (err) {
    showResult(false, "Payment could not be confirmed", err.message);
  }
}

function receiptHtml(o) {
  return `<div class="result-receipt">
    ${o.items.map((it) => `<div class="rr-row"><span>${esc(it.product_name)} × ${it.quantity}</span><strong>${fmt(it.line_total)}</strong></div>`).join("")}
    <div class="rr-row big"><span>Total</span><strong>${fmt(o.total_amount)}</strong></div>
    <div class="rr-row"><span>Payment status</span><strong>${esc(o.payment_status)}</strong></div>
    <div class="rr-row"><span>PayPal order currency</span><strong>${esc(o.currency)}</strong></div>
    ${o.capture_id ? `<div class="rr-row"><span>PayPal capture ID</span><strong>${esc(o.capture_id)}</strong></div>` : ""}
    ${o.payer_email ? `<div class="rr-row"><span>Payer</span><strong>${esc(o.payer_email)}</strong></div>` : ""}
    <div class="rr-row"><span>PayPal order</span><strong>${esc(o.paypal_order_id || "—")}</strong></div>
  </div>`;
}

function showResult(ok, title, subtitle, receipt = "") {
  $("#resultHero").innerHTML = `
    <div class="result-icon ${ok ? "ok" : "bad"}">${ok ? `<svg viewBox="0 0 24 24" width="38" height="38" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>` : `<svg viewBox="0 0 24 24" width="36" height="36" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M12 8v5"/><path d="M12 16.5v.5"/><circle cx="12" cy="12" r="10"/></svg>`}</div>
    <h2>${esc(title)}</h2>
    <p class="sub">${subtitle}</p>
    ${receipt}
    <div class="result-actions">
      <a class="btn btn-primary" href="#/orders">View my orders</a>
      <a class="btn btn-outline" href="#/explore">Continue shopping</a>
    </div>`;
}

async function checkoutCancel() {
  const params = new URLSearchParams(location.search);
  const token = params.get("token");
  if (token) {
    try { await api("/api/payments/cancel-order", { method: "POST", body: { paypal_order_id: token } }); } catch { /* best-effort */ }
  }
  view().innerHTML = `
    <div class="result-hero">
      <div class="result-icon bad" style="background:#f1f5f9;color:var(--muted)">
        <svg viewBox="0 0 24 24" width="34" height="34" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><path d="m15 9-6 6M9 9l6 6"/></svg>
      </div>
      <h2>Checkout cancelled</h2>
      <p class="sub">You cancelled the payment on PayPal. Nothing was charged — your cart is still intact whenever you want to try again.</p>
      <div class="result-actions">
        <a class="btn btn-primary" href="#/cart">Back to my cart</a>
        <a class="btn btn-outline" href="#/explore">Keep browsing</a>
      </div>
    </div>`;
}

/* ------------------------------- ROUTER ----------------------------- */

function route() {
  const hash = location.hash.replace(/^#\/?/, "") || "home";
  state.route = ["home", "explore", "assistant", "cart", "orders"].includes(hash) ? hash : "home";
  render();
}

window.addEventListener("hashchange", route);

/* ------------------------------ GLOBAL UI --------------------------- */

document.addEventListener("click", (e) => {
  const open = e.target.closest("[data-open]");
  const add = e.target.closest("[data-add]");
  const cmp = e.target.closest("[data-cmp]");
  const cmpX = e.target.closest("[data-cmp-x]");
  const close = e.target.closest("[data-close]");
  const retry = e.target.closest("[data-retry]");
  const suggest = e.target.closest("[data-suggest]");

  if (e.target === $("#modalBackdrop")) { closeModal(); return; }
  if (close) { closeModal(); return; }
  if (add) { addToCart(add.dataset.add); return; }
  if (cmp) { toggleCompare(cmp.dataset.cmp); return; }
  if (cmpX) { toggleCompare(cmpX.dataset.cmpX); return; }
  if (open) { const p = state.byId.get(open.dataset.open); if (p) productModal(p); return; }
  if (retry) {
    const idx = +retry.closest("[data-msg]").dataset.msg;
    const lastUser = [...state.chat.slice(0, idx)].reverse().find((m) => m.role === "user");
    state.chat = state.chat.slice(0, idx);
    if (lastUser) { $("#chatInput").value = lastUser.content; sendChat(); } else renderChatLog();
    return;
  }
  if (suggest) {
    state.pendingQuestion = suggest.dataset.suggest;
    location.hash = "#/assistant";
    if (state.route === "assistant") { renderAssistant(); }
    return;
  }
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

$("#compareNowBtn").addEventListener("click", compareModal);
$("#compareClearBtn").addEventListener("click", () => { state.compare = []; syncCompareUI(); });

$("#navToggle").addEventListener("click", () => {
  const links = $("#navLinks");
  const open = links.classList.toggle("open");
  $("#navToggle").classList.toggle("open", open);
  $("#navToggle").setAttribute("aria-expanded", open);
});

/* -------------------------------- INIT ------------------------------ */

async function init() {
  try {
    const [health, products] = await Promise.all([
      api("/api/health").catch(() => null),
      api("/api/products"),
    ]);
    state.health = health;
    state.products = products;
    state.byId = new Map(products.map((p) => [p.id, p]));
    // Drop cart lines whose products no longer exist.
    state.cart = state.cart.filter((l) => state.byId.has(l.id));
    saveCart();
  } catch (err) {
    view().innerHTML = `<div class="alert alert-error" style="margin-top:26px">
      <strong>Could not load the PayPilot catalogue.</strong><br/>${esc(err.message)}<br/><br/>
      Start the backend from the <code>backend/</code> folder with <code>uvicorn app:app --reload</code> and refresh this page.</div>`;
    return;
  }

  const path = location.pathname;
  if (path === "/checkout-success") { await checkoutSuccess(); return; }
  if (path === "/checkout-cancel") { await checkoutCancel(); return; }
  route();
}

init();
