// "Actualiser" button: asks the server (`observatoire web`) to run the update, follows it,
// then reloads the page. It shows only when /api/status answers, so the offline archive
// and `make serve` (a plain file server) look exactly as before.
(function () {
  "use strict";

  var POLL_MS = 3000;
  var TEXT = {
    fr: {
      idle: "Actualiser les données",
      running: "Mise à jour en cours…",
      last: "Dernière mise à jour",
      never: "Jamais actualisé depuis ce serveur",
      failed: "La dernière mise à jour a échoué",
      tooSoon: "Prochaine actualisation possible à",
      error: "Serveur injoignable",
    },
    en: {
      idle: "Refresh the data",
      running: "Updating…",
      last: "Last update",
      never: "Never refreshed from this server",
      failed: "The last update failed",
      tooSoon: "Next refresh possible at",
      error: "Server unreachable",
    },
  };

  function lang() {
    var node = document.querySelector("x-dc [lang]") || document.documentElement;
    return (node.getAttribute("lang") || "fr").slice(0, 2) === "en" ? "en" : "fr";
  }

  function t(key) {
    return TEXT[lang()][key];
  }

  function time(iso, withDay) {
    var options = { hour: "2-digit", minute: "2-digit" };
    if (withDay) {
      options.day = "numeric";
      options.month = "long";
    }
    return new Date(iso).toLocaleString(lang() === "en" ? "en-GB" : "fr-FR", options);
  }

  var ICON =
    '<svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" ' +
    'stroke="currentColor" stroke-width="2" stroke-linecap="square"><path d="M20 12a8 8 0 1 1-2.34-5.66"/>' +
    '<path d="M20 4v5h-5"/></svg>';

  var root, button, label, note, polling = null;

  function build() {
    var style = document.createElement("style");
    style.textContent =
      "#ia-refresh{position:fixed;right:24px;bottom:24px;z-index:70;display:flex;flex-direction:column;align-items:flex-end;gap:6px;font-family:'JetBrains Mono',ui-monospace,monospace}" +
      "#ia-refresh button{appearance:none;display:inline-flex;align-items:center;gap:10px;padding:11px 16px;border:1px solid rgba(243,241,236,.25);border-radius:3px;background:#0B0C0F;color:#F3F1EC;font:inherit;font-size:12px;letter-spacing:.06em;text-transform:uppercase;cursor:pointer;box-shadow:0 12px 32px rgba(11,12,15,.28);transition:transform .2s,background .2s}" +
      "#ia-refresh button:hover:not(:disabled){background:#1A1B1F;transform:translateY(-2px)}" +
      "#ia-refresh button:focus-visible{outline:2px solid #1B33B4;outline-offset:3px}" +
      "#ia-refresh button:disabled{cursor:progress}" +
      "#ia-refresh[data-running] svg{animation:ia-spin 1s linear infinite}" +
      "#ia-refresh p{margin:0;padding:4px 8px;background:rgba(243,241,236,.92);color:#3A3E46;font-size:11px;letter-spacing:.02em;border-radius:3px}" +
      "@keyframes ia-spin{to{transform:rotate(360deg)}}";
    document.head.appendChild(style);
    root = document.createElement("div");
    root.id = "ia-refresh";
    button = document.createElement("button");
    button.type = "button";
    button.innerHTML = ICON;
    label = document.createElement("span");
    button.appendChild(label);
    note = document.createElement("p");
    note.setAttribute("role", "status");
    root.appendChild(button);
    root.appendChild(note);
    button.addEventListener("click", refresh);
    document.body.appendChild(root);
  }

  function show(status, message) {
    if (!root) build();
    var running = Boolean(status && status.running);
    root.toggleAttribute("data-running", running);
    button.disabled = running;
    label.textContent = running ? t("running") : t("idle");
    var last = latest(status);
    if (message) {
      note.textContent = message;
    } else if (last && last.code) {
      note.textContent = t("failed");
    } else if (last) {
      note.textContent = t("last") + " : " + time(last.at, true);
    } else {
      note.textContent = t("never");
    }
  }

  // The most recent update, scheduled or asked from this button: the scheduled one is only
  // known through lastUpdateAt; a button run cut short only through finishedAt.
  function latest(status) {
    if (!status) return null;
    var scheduled = status.lastUpdateAt ? { at: status.lastUpdateAt, code: status.lastUpdateExitCode } : null;
    var asked = status.finishedAt ? { at: status.finishedAt, code: status.exitCode } : null;
    if (!scheduled || !asked) return scheduled || asked;
    return new Date(asked.at) > new Date(scheduled.at) ? asked : scheduled;
  }

  function getStatus() {
    return fetch("/api/status", { cache: "no-store" }).then(function (response) {
      if (!response.ok) throw new Error(String(response.status));
      return response.json();
    });
  }

  function follow() {
    if (polling) return;
    polling = setInterval(function () {
      getStatus()
        .then(function (status) {
          if (status.running) return show(status);
          clearInterval(polling);
          polling = null;
          if (status.exitCode === 0) return window.location.reload();
          show(status);
        })
        .catch(function () {
          show(null, t("error"));
        });
    }, POLL_MS);
  }

  function refresh() {
    fetch("/api/refresh", { method: "POST" })
      .then(function (response) {
        return response.json().then(function (body) {
          if (response.status === 429) {
            return show(body, t("tooSoon") + " " + time(body.nextAllowedAt, false));
          }
          show(body);
          follow();
        });
      })
      .catch(function () {
        show(null, t("error"));
      });
  }

  function start() {
    getStatus()
      .then(function (status) {
        show(status);
        if (status.running) follow();
      })
      .catch(function () {
        /* plain file server or offline archive: no button */
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
