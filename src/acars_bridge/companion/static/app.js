(() => {
  const $ = (id) => document.getElementById(id);
  const listEl = $("messageList");
  const emptyEl = $("inboxEmpty");
  let oldestId = null;
  let newestId = 0;
  let busy = false;
  let detailId = null;

  function headers() {
    return { "Content-Type": "application/json" };
  }

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      ...opts,
      headers: { ...headers(), ...(opts.headers || {}) },
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.error || `HTTP ${res.status}`);
    }
    return data;
  }

  function toast(message, error = false) {
    const el = $("toast");
    el.textContent = message;
    el.classList.toggle("error", !!error);
    el.classList.remove("hidden");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => el.classList.add("hidden"), error ? 7000 : 3500);
  }

  function setBusy(on) {
    busy = on;
    document.querySelectorAll("button.accent, button.primary").forEach((b) => {
      b.disabled = on;
    });
  }

  function fmtTime(iso) {
    if (!iso) return "—";
    try {
      const raw = String(iso).trim();
      const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw);
      const d = new Date(hasZone ? raw : `${raw}Z`);
      if (Number.isNaN(d.getTime())) return raw;
      const pad = (n) => String(n).padStart(2, "0");
      return (
        `${pad(d.getUTCDate())}.${pad(d.getUTCMonth() + 1)}.${d.getUTCFullYear()}` +
        ` - ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`
      );
    } catch {
      return iso;
    }
  }

  function renderMessages(rows, { append = false, prependOlder = false } = {}) {
    if (!append && !prependOlder) listEl.innerHTML = "";
    const frag = document.createDocumentFragment();
    for (const m of rows) {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "msg";
      btn.dataset.id = String(m.id);
      btn.innerHTML = `
        <div class="meta">
          <span class="${m.direction === "in" ? "dir-in" : "dir-out"}">
            ${m.direction.toUpperCase()} · ${(m.message_type || "").toUpperCase()}
          </span>
          <span>${fmtTime(m.received_at)} · ${m.station || "—"}</span>
        </div>
        <div class="preview">${escapeHtml(m.preview || m.normalized_body || "")}</div>
      `;
      btn.addEventListener("click", () => openDetail(m.id));
      li.appendChild(btn);
      frag.appendChild(li);
      if (oldestId === null || m.id < oldestId) oldestId = m.id;
      if (m.id > newestId) newestId = m.id;
    }
    if (prependOlder) {
      listEl.appendChild(frag);
    } else if (append) {
      listEl.insertBefore(frag, listEl.firstChild);
    } else {
      listEl.appendChild(frag);
    }
    emptyEl.style.display = listEl.children.length ? "none" : "block";
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  async function openDetail(id) {
    try {
      const m = await api(`/api/messages/${id}`);
      detailId = m.id;
      $("detailTitle").textContent = `${(m.message_type || "").toUpperCase()} · ${m.station || "—"}`;
      $("detailBody").textContent = m.normalized_body || "";
      const replyRow = $("replyRow");
      replyRow.innerHTML = "";
      const choices = m.can_reply ? m.reply_choices || [] : [];
      if (choices.length) {
        replyRow.classList.remove("hidden");
        for (const reply of choices) {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = reply === "WILCO" || reply === "ROGER" || reply === "AFFIRM"
            ? "accent"
            : "primary";
          btn.textContent = reply;
          btn.addEventListener("click", () => sendReply(reply));
          replyRow.appendChild(btn);
        }
      } else {
        replyRow.classList.add("hidden");
      }
      $("detail").classList.remove("hidden");
      $("detail").setAttribute("aria-hidden", "false");
    } catch (e) {
      toast(e.message, true);
    }
  }

  async function sendReply(reply) {
    if (busy || !detailId) return;
    setBusy(true);
    try {
      await api(`/api/messages/${detailId}/reply`, {
        method: "POST",
        body: JSON.stringify({ reply }),
      });
      toast(`${reply} sent`);
      $("detail").classList.add("hidden");
      await loadInbox({ reset: true });
    } catch (e) {
      toast(e.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function loadInbox({ reset = false } = {}) {
    const data = await api(`/api/messages?limit=40`);
    oldestId = null;
    newestId = 0;
    renderMessages(data.messages || [], { append: false });
    $("countPill").textContent = `${data.count || 0} msg`;
  }

  async function loadOlder() {
    if (!oldestId) return;
    const data = await api(`/api/messages?before_id=${oldestId}&limit=40`);
    const rows = data.messages || [];
    if (!rows.length) {
      toast("No older messages");
      return;
    }
    renderMessages(rows, { prependOlder: true });
  }

  async function pollNew() {
    if (!newestId) return;
    try {
      const data = await api(`/api/messages?since_id=${newestId}&limit=50`);
      const rows = (data.messages || []).slice().reverse();
      if (rows.length) renderMessages(rows, { append: true });
      $("countPill").textContent = `${data.count || 0} msg`;
    } catch {
      /* ignore transient */
    }
  }

  async function refreshStatus() {
    const s = await api("/api/status");
    const sourceLabels = {
      network: "Network",
      simbrief: "SimBrief",
      message: "Last message",
      remembered: "Remembered",
      wire: "Connect",
    };
    const cs = s.callsign || "";
    const src = sourceLabels[s.callsign_source] || "";
    $("callsign").textContent = cs
      ? src
        ? `${cs} · ${src}`
        : cs
      : "NO CALLSIGN";
    const pill = $("stationPill");
    if (s.companion_station_enabled) {
      pill.textContent = s.station_error ? "STN ERR" : "STN ON";
      pill.className = "pill " + (s.station_error ? "warn" : "ok");
    } else if (s.wire_session && s.wire_session.ready) {
      pill.textContent = "VIA CONN";
      pill.className = "pill ok";
    } else {
      pill.textContent = "STN OFF";
      pill.className = "pill muted";
    }
    $("countPill").textContent = `${s.message_count || 0} msg`;
    let line;
    if (s.companion_station_enabled) {
      line =
        "Station mode — this PC polls and can send weather, ATIS, telex, and PDC.";
    } else if (s.can_send && s.wire_session && s.wire_session.ready) {
      line =
        "Connect active — phone sends use the aircraft’s live Hoppie session (no station mode needed).";
    } else {
      line =
        "Inbox only — Connect and wait for a Hoppie/SayIntentions ACARS exchange (Fenix ATIS does not count), or enable station mode when the plane is not on Hoppie.";
    }
    if (s.station_error) line = s.station_error;
    if (!s.can_send) {
      if (s.companion_station_enabled && !s.has_logon) {
        line =
          "Station mode needs a Hoppie logon under Network on the desktop.";
      } else if (s.companion_station_enabled && !s.has_callsign) {
        line =
          "No callsign yet — load a SimBrief OFP, tap/print one ACARS message, or set the Network callsign filter.";
      }
    }
    $("statusLine").textContent = line;

    if (s.last_icao && !$("wxIcao").value) $("wxIcao").value = s.last_icao;
    const d = s.pdc_defaults || {};
    if (d.station && !$("pdcStation").value) $("pdcStation").value = d.station;
    if (d.departure && !$("pdcDep").value) $("pdcDep").value = d.departure;
    if (d.destination && !$("pdcDest").value) $("pdcDest").value = d.destination;
    if (d.aircraft_type && !$("pdcType").value) $("pdcType").value = d.aircraft_type;
    if (d.stand && !$("pdcStand").value) $("pdcStand").value = d.stand;
    if (d.atis_letter && !$("pdcAtis").value) $("pdcAtis").value = d.atis_letter;
  }

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
      tab.classList.add("active");
      $(`view-${tab.dataset.view}`).classList.add("active");
    });
  });

  $("btnCloseDetail").addEventListener("click", () => {
    $("detail").classList.add("hidden");
    $("detail").setAttribute("aria-hidden", "true");
    detailId = null;
  });
  $("btnReprint").addEventListener("click", async () => {
    if (busy || !detailId) return;
    setBusy(true);
    try {
      const r = await api(`/api/messages/${detailId}/print`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      toast(r.result === "deferred" ? "Print deferred" : "Printed");
    } catch (e) {
      toast(e.message, true);
    } finally {
      setBusy(false);
    }
  });
  $("detail").addEventListener("click", (e) => {
    if (e.target === $("detail")) $("btnCloseDetail").click();
  });

  $("btnRefresh").addEventListener("click", () => {
    loadInbox({ reset: true }).catch((e) => toast(e.message, true));
  });
  $("btnMore").addEventListener("click", () => {
    loadOlder().catch((e) => toast(e.message, true));
  });

  document.querySelectorAll("[data-wx]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (busy) return;
      setBusy(true);
      try {
        const icao = $("wxIcao").value.trim().toUpperCase();
        await api("/api/weather", {
          method: "POST",
          body: JSON.stringify({ kind: btn.dataset.wx, icao }),
        });
        toast(`${btn.dataset.wx.toUpperCase()} ${icao} requested`);
        await loadInbox({ reset: true });
        document.querySelector('.tab[data-view="inbox"]').click();
      } catch (e) {
        toast(e.message, true);
      } finally {
        setBusy(false);
      }
    });
  });

  $("btnAtis").addEventListener("click", async () => {
    if (busy) return;
    setBusy(true);
    try {
      const icao = $("wxIcao").value.trim().toUpperCase();
      await api("/api/atis", {
        method: "POST",
        body: JSON.stringify({
          icao,
          side: $("atisSide").value,
          source: "vatatis",
        }),
      });
      toast(`ATIS ${icao} requested`);
      await loadInbox({ reset: true });
      document.querySelector('.tab[data-view="inbox"]').click();
    } catch (e) {
      toast(e.message, true);
    } finally {
      setBusy(false);
    }
  });

  $("btnTelex").addEventListener("click", async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api("/api/telex", {
        method: "POST",
        body: JSON.stringify({
          to: $("telexTo").value.trim().toUpperCase(),
          text: $("telexBody").value,
        }),
      });
      toast("Telex sent");
      $("telexBody").value = "";
      await loadInbox({ reset: true });
      document.querySelector('.tab[data-view="inbox"]').click();
    } catch (e) {
      toast(e.message, true);
    } finally {
      setBusy(false);
    }
  });

  $("btnPdc").addEventListener("click", async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api("/api/pdc", {
        method: "POST",
        body: JSON.stringify({
          station: $("pdcStation").value.trim().toUpperCase(),
          departure: $("pdcDep").value.trim().toUpperCase(),
          destination: $("pdcDest").value.trim().toUpperCase(),
          aircraft_type: $("pdcType").value.trim().toUpperCase(),
          stand: $("pdcStand").value.trim().toUpperCase(),
          atis_letter: $("pdcAtis").value.trim().toUpperCase(),
        }),
      });
      toast("PDC request sent");
      await loadInbox({ reset: true });
      document.querySelector('.tab[data-view="inbox"]').click();
    } catch (e) {
      toast(e.message, true);
    } finally {
      setBusy(false);
    }
  });

  async function boot() {
    try {
      await refreshStatus();
      await loadInbox({ reset: true });
      setInterval(() => {
        refreshStatus().catch(() => undefined);
        pollNew();
      }, 2500);
    } catch (e) {
      toast(e.message, true);
      $("statusLine").textContent = e.message;
    }
  }

  boot();
})();
