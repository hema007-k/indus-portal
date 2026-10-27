/* Indomer HR Portal - page scripts.
 *
 * The portal uses Turbo, so links and form submits replace the page in place (no full reload).
 * That means these scripts must run again for every new page: everything is inside init(), which runs
 * on the first load and after every Turbo visit. Without Turbo (e.g. no internet for the CDN) the
 * portal still works as a normal website.
 */
(function () {
  "use strict";

  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var clockTimer = null;
  var pendingScroll = null;   // {url, y} - keeps your place when a button on a page reloads the same page

  function pad(n) { return String(n).padStart(2, "0"); }
  function all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function safely(fn) { try { fn(); } catch (e) { if (window.console) { console.error(e); } } }
  function submitForm(f) { if (f.requestSubmit) { f.requestSubmit(); } else { f.submit(); } }

  /* ---------- success messages fade away ---------- */
  function initAlerts() {
    all(".alert.alert-success").forEach(function (el) {
      setTimeout(function () {
        if (window.bootstrap && document.body.contains(el)) { bootstrap.Alert.getOrCreateInstance(el).close(); }
      }, 4000);
    });
  }

  /* ---------- light / dark theme (remembered in the browser) ---------- */
  function initTheme() {
    var root = document.documentElement;
    var btn = document.querySelector("[data-theme-toggle]");
    if (!btn) { return; }
    var label = function () {
      btn.textContent = root.getAttribute("data-bs-theme") === "dark" ? "Light mode" : "Dark mode";
    };
    label();
    btn.addEventListener("click", function () {
      var next = root.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
      root.setAttribute("data-bs-theme", next);
      try { localStorage.setItem("hr-theme", next); } catch (e) { /* private mode */ }
      label();
    });
  }

  /* ---------- Monthly / Yearly filter: show the month box or the year box, apply by itself ---------- */
  function initPeriodForms() {
    all("[data-period-form]").forEach(function (form) {
      var mode = function () {
        var checked = form.querySelector('input[name="period"]:checked');
        return checked ? checked.value : "month";
      };
      var sync = function () {
        var m = mode();
        all("[data-show]", form).forEach(function (el) { el.hidden = el.getAttribute("data-show") !== m; });
      };
      all('input[name="period"]', form).forEach(function (r) {
        r.addEventListener("change", function () { sync(); submitForm(form); });
      });
      // choosing another month / year applies at once - no need to press Apply
      all('input[name="month"], select[name="year"]', form).forEach(function (el) {
        el.addEventListener("change", function () { submitForm(form); });
      });
      sync();
    });
  }

  /* ---------- selects that submit their form when changed ---------- */
  function initAutoSubmit() {
    all("select[data-autosubmit]").forEach(function (sel) {
      sel.addEventListener("change", function () { if (sel.form) { submitForm(sel.form); } });
    });
  }

  /* ---------- date pickers: always show 12-Oct-2026 (d-M-Y); the form still submits Y-m-d ---------- */
  function initDates() {
    if (!window.flatpickr) { return; }
    all("input[data-date]").forEach(function (el) {
      if (el._flatpickr) { return; }
      flatpickr(el, { altInput: true, altFormat: "d-M-Y", dateFormat: "Y-m-d", allowInput: false, disableMobile: true });
    });
  }

  /* ---------- live clock in the same d-M-Y format ---------- */
  function initClock() {
    if (clockTimer) { clearInterval(clockTimer); clockTimer = null; }
    var clock = document.querySelector("[data-live-clock]");
    if (!clock) { return; }
    var tick = function () {
      var d = new Date();
      var h = d.getHours() % 12 || 12;
      clock.textContent = "Now: " + pad(d.getDate()) + "-" + MONTHS[d.getMonth()] + "-" + d.getFullYear() + " " +
        pad(h) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds()) + (d.getHours() >= 12 ? " PM" : " AM");
    };
    tick();
    clockTimer = setInterval(tick, 1000);
  }

  /* ---------- instant search: filters the rows of table(s) while you type (no server round trip) ---------- */
  function initLiveFilter() {
    all("input[data-live-filter]").forEach(function (input) {
      var ids = input.getAttribute("data-live-filter").split(/\s+/).filter(Boolean);
      var bodies = ids.map(function (id) {
        var t = document.getElementById(id);
        return t ? t.tBodies[0] : null;
      }).filter(Boolean);
      if (!bodies.length) { return; }
      var run = function () {
        var words = input.value.toLowerCase().split(/\s+/).filter(Boolean);
        bodies.forEach(function (body) {
          var shown = 0, real = 0;
          all("tr", body).forEach(function (tr) {
            if (tr.hasAttribute("data-no-match") || tr.querySelector("td[colspan]")) { return; }
            real++;
            var text = (tr.getAttribute("data-search") || tr.textContent).toLowerCase();
            var ok = words.every(function (w) { return text.indexOf(w) !== -1; });
            tr.hidden = !ok;
            if (ok) { shown++; }
          });
          var msg = body.querySelector("tr[data-no-match]");
          if (real && !shown && words.length) {
            if (!msg) {
              msg = document.createElement("tr");
              msg.setAttribute("data-no-match", "");
              msg.className = "empty-row";
              msg.innerHTML = '<td colspan="12" class="text-center text-secondary">Nothing matches your search.</td>';
              body.appendChild(msg);
            }
            msg.hidden = false;
          } else if (msg) {
            msg.hidden = true;
          }
        });
      };
      input.addEventListener("input", run);
      run();   // the box may already hold a search (e.g. ?q=arun)
    });
  }

  /* ---------- project form: search / select the members ---------- */
  function initMemberPicker() {
    all("[data-member-picker]").forEach(function (box) {
      var search = box.querySelector("[data-member-search]");
      var rows = all("[data-member-row]", box);
      var counter = box.querySelector("[data-member-count]");
      var onlyBtn = box.querySelector("[data-member-only]");
      var allBtn = box.querySelector("[data-member-all]");
      var clearBtn = box.querySelector("[data-member-clear]");
      var empty = box.querySelector("[data-member-empty]");
      var onlySelected = false;

      var box_ = function (row) { return row.querySelector('input[type="checkbox"]'); };
      var isOn = function (row) { var c = box_(row); return !!(c && c.checked); };

      var refresh = function () {
        var words = (search ? search.value : "").toLowerCase().split(/\s+/).filter(Boolean);
        var shown = 0;
        rows.forEach(function (row) {
          var text = (row.getAttribute("data-search") || row.textContent).toLowerCase();
          var ok = words.every(function (w) { return text.indexOf(w) !== -1; });
          var on = isOn(row);
          if (onlySelected && !on) { ok = false; }
          row.hidden = !ok;
          if (ok) { shown++; }
          row.classList.toggle("member-on", on);
          var sel = row.querySelector("select");
          // a ticked member must get Office or Field - highlight the box until it is chosen
          if (sel) { sel.classList.toggle("needs-choice", on && !sel.value); }
        });
        var picked = rows.filter(isOn).length;
        if (counter) { counter.textContent = picked + " selected"; }
        if (empty) { empty.hidden = shown !== 0; }
        if (onlyBtn) { onlyBtn.classList.toggle("active", onlySelected); }
      };

      box.addEventListener("change", refresh);
      if (search) {
        search.addEventListener("input", refresh);
        // pressing Enter in the search box must not submit the whole project form
        search.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); } });
      }
      if (onlyBtn) { onlyBtn.addEventListener("click", function () { onlySelected = !onlySelected; refresh(); }); }
      if (allBtn) {
        allBtn.addEventListener("click", function () {
          rows.forEach(function (row) {
            var c = box_(row);
            if (c && !row.hidden) { c.checked = true; }
          });
          refresh();
        });
      }
      if (clearBtn) {
        clearBtn.addEventListener("click", function () {
          rows.forEach(function (row) { var c = box_(row); if (c) { c.checked = false; } });
          onlySelected = false;
          refresh();
        });
      }
      refresh();
    });
  }

  /* ---------- keep your place on the page after a button that reloads the same page ---------- */
  function restoreScroll() {
    if (pendingScroll && pendingScroll.url === location.pathname + location.search) {
      window.scrollTo(0, pendingScroll.y);
    }
    pendingScroll = null;
  }

  function init() {
    if (document.body.dataset.portalReady) { return; }   // the <body> is replaced on every Turbo visit
    document.body.dataset.portalReady = "1";
    safely(initAlerts);
    safely(initTheme);
    safely(initPeriodForms);
    safely(initAutoSubmit);
    safely(initDates);
    safely(initClock);
    safely(initLiveFilter);
    safely(initMemberPicker);
    // login / logout: forget the pages Turbo kept for the Back button (nobody sees the old user's pages)
    all("form[data-clear-cache]").forEach(function (f) {
      f.addEventListener("submit", function () { if (window.Turbo && Turbo.cache) { Turbo.cache.clear(); } });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  var progressSet = false;
  document.addEventListener("turbo:load", function () {
    if (!progressSet && window.Turbo && Turbo.setProgressBarDelay) { Turbo.setProgressBarDelay(100); progressSet = true; }
    init();
    safely(restoreScroll);
  });
  document.addEventListener("turbo:submit-start", function (e) {
    pendingScroll = { url: location.pathname + location.search, y: window.scrollY };
    if (e.target && e.target.classList) { e.target.classList.add("is-busy"); }
  });
  document.addEventListener("turbo:submit-end", function (e) {
    if (e.target && e.target.classList) { e.target.classList.remove("is-busy"); }
  });
  // what Turbo keeps for the Back button must be clean: no date-picker copies, no old messages
  document.addEventListener("turbo:before-cache", function () {
    all("input[data-date]").forEach(function (el) { if (el._flatpickr) { el._flatpickr.destroy(); } });
    all(".alert").forEach(function (el) { el.remove(); });
    all("[data-no-match]").forEach(function (el) { el.remove(); });
    all("tr[hidden]").forEach(function (el) { el.hidden = false; });
    delete document.body.dataset.portalReady;
    if (clockTimer) { clearInterval(clockTimer); clockTimer = null; }
  });
})();
