/* ============================================================
   AFUVAI — shared behaviour
   Guarded by element presence so one file serves every page.
   No dependencies. No backend.
   ============================================================ */
(function () {
  "use strict";
  var isDefined = function (v) { return v !== null && v !== undefined; };

  /* ---------- Mobile nav ---------- */
  var toggle = document.querySelector(".nav-toggle");
  var links = document.querySelector(".nav-links");
  if (isDefined(toggle) && isDefined(links)) {
    toggle.addEventListener("click", function () {
      var open = links.classList.toggle("open");
      toggle.setAttribute("aria-expanded", String(open));
    });
    // Close menu when a link is chosen (single-page anchors / navigation)
    links.addEventListener("click", function (e) {
      if (e.target.closest("a") && links.classList.contains("open")) {
        links.classList.remove("open");
        toggle.setAttribute("aria-expanded", "false");
      }
    });
  }

  /* ---------- Scroll reveals (motion-safe) ---------- */
  var reveals = document.querySelectorAll(".reveal");
  var prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reveals.length && !prefersReduced && "IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -8% 0px" });
    reveals.forEach(function (el) { io.observe(el); });
  } else {
    reveals.forEach(function (el) { el.classList.add("is-visible"); });
  }

  /* ---------- Inquiry form ---------- */
  var form = document.querySelector("[data-inquiry-form]");
  if (isDefined(form)) {
    var setError = function (field, message) {
      var wrap = field.closest(".field");
      var slot = wrap ? wrap.querySelector(".field__error") : null;
      if (wrap) wrap.classList.toggle("field--error", Boolean(message));
      if (slot) slot.textContent = message || "";
      field.setAttribute("aria-invalid", message ? "true" : "false");
    };
    var emailOk = function (v) { return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v); };

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var valid = true;
      var firstInvalid = null;
      var require = function (name, test, msg) {
        var field = form.elements[name];
        if (!field) return;
        var ok = test(String(field.value || "").trim());
        setError(field, ok ? "" : msg);
        if (!ok) { valid = false; firstInvalid = firstInvalid || field; }
      };

      require("name", function (v) { return v.length >= 2; }, "Please enter your name.");
      require("email", emailOk, "Please enter a valid email address.");
      require("occasion", function (v) { return v.length > 0; }, "Please choose an occasion.");
      require("message", function (v) { return v.length >= 10; }, "A sentence or two helps us tailor your proposal.");

      if (!valid) { if (firstInvalid) firstInvalid.focus(); return; }

      // No backend: collect the payload and surface a success state.
      var payload = {};
      Array.prototype.forEach.call(form.elements, function (el) {
        if (el.name) payload[el.name] = el.value;
      });
      payload.submittedAt = new Date().toISOString();
      console.log("AFUVAI inquiry submitted:", payload);

      var success = document.querySelector("[data-inquiry-success]");
      if (isDefined(success)) {
        form.hidden = true;
        success.hidden = false;
        success.setAttribute("tabindex", "-1");
        success.focus();
        success.scrollIntoView({ behavior: prefersReduced ? "auto" : "smooth", block: "center" });
      }
      form.reset();
    });
  }

  /* ---------- Newsletter capture ---------- */
  var news = document.querySelector("[data-newsletter]");
  if (isDefined(news)) {
    news.addEventListener("submit", function (e) {
      e.preventDefault();
      var input = news.querySelector("input[type=email]");
      var msg = news.parentElement.querySelector(".newsletter__msg");
      var value = input ? String(input.value || "").trim() : "";
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) {
        if (msg) msg.textContent = "Please enter a valid email.";
        return;
      }
      console.log("AFUVAI newsletter signup:", value);
      if (msg) msg.textContent = "Thank you — you're on the list.";
      news.reset();
    });
  }

  /* ---------- Portfolio lightbox ---------- */
  var triggers = document.querySelectorAll("[data-lightbox]");
  if (triggers.length) {
    var box = document.createElement("div");
    box.className = "lightbox";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    box.setAttribute("aria-label", "Image preview");
    box.innerHTML = '<button class="lightbox__close" aria-label="Close preview">&times;</button><img alt="">';
    document.body.appendChild(box);
    var boxImg = box.querySelector("img");
    var closeBtn = box.querySelector(".lightbox__close");
    var lastFocused = null;
    var open = function (src, alt) {
      lastFocused = document.activeElement;
      boxImg.src = src; boxImg.alt = alt || "";
      box.classList.add("open");
      closeBtn.focus();
    };
    var close = function () {
      box.classList.remove("open");
      boxImg.src = "";
      if (lastFocused) lastFocused.focus();
    };
    triggers.forEach(function (t) {
      t.addEventListener("click", function () {
        var img = t.querySelector("img");
        if (img) open(img.currentSrc || img.src, img.alt);
      });
    });
    closeBtn.addEventListener("click", close);
    box.addEventListener("click", function (e) { if (e.target === box) close(); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && box.classList.contains("open")) close(); });
  }

  /* ---------- Footer year ---------- */
  var yearEl = document.querySelector("[data-year]");
  if (isDefined(yearEl)) yearEl.textContent = String(new Date().getFullYear());

  /* ---------- Header shadow on scroll ---------- */
  var header = document.querySelector(".site-header");
  if (isDefined(header)) {
    var onScroll = function () { header.classList.toggle("scrolled", window.scrollY > 12); };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  /* ---------- Cookie consent (gates GA4 / Meta pixel) ---------- */
  var consent = document.querySelector("[data-consent]");
  if (isDefined(consent)) {
    var KEY = "afuvai-consent";
    var loadAnalytics = function () {
      // Placeholder: initialise GA4 / Meta Pixel here once the IDs exist.
      console.log("AFUVAI analytics: consent granted — load GA4 / Meta pixel here.");
    };
    var choice = null;
    try { choice = localStorage.getItem(KEY); } catch (e) {}
    if (choice === "accepted") { loadAnalytics(); }
    else if (choice !== "declined") { consent.hidden = false; }
    var decide = function (val) {
      try { localStorage.setItem(KEY, val); } catch (e) {}
      consent.hidden = true;
      if (val === "accepted") loadAnalytics();
    };
    var acc = consent.querySelector("[data-consent-accept]");
    var dec = consent.querySelector("[data-consent-decline]");
    if (acc) acc.addEventListener("click", function () { decide("accepted"); });
    if (dec) dec.addEventListener("click", function () { decide("declined"); });
  }
})();
