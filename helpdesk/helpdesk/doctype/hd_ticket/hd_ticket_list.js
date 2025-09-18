// /home/frappe/frappe-bench/apps/helpdesk/helpdesk/helpdesk/doctype/hd_ticket/hd_ticket_list.js
// TR: HD Ticket – List UX v3.3 (tam genişlik + formatter + CSS injection)

(function () {
  const CSS_ID = "hd-ticket-list-css-v33";
  const STYLE_ID = "hd-ticket-fullwidth-css";
  const SCORE_THRESHOLDS = { good: 0.10, mid: 0.30 }; // <=0.10 iyi, <=0.30 orta, > kötü

  frappe.listview_settings["HD Ticket"] = {
    hide_name_column: true,
    add_fields: [
      "status",
      "priority",
      "last_sentiment",
      "sentiment_trend",
      "effort_score",
      "effort_band",
    ],
onload(listview) {
  inject_css_once();

  if (!document.getElementById(STYLE_ID)) {
    const css = `
      /* Container sınırını kaldır ama yan boşluk bırak */
      .container {
        max-width: 100% !important;
        width: 100% !important;
        padding-left: 12px !important;
        padding-right: 12px !important;
      }

      /* HD Ticket List tam genişlik + iç padding */
      .app-page .layout-main-section,
      .app-page .frappe-list,
      .app-page .page-form,
      .app-page .result {
        max-width: 100% !important;
        width: 100% !important;
        margin-left: 0 !important;
        margin-right: 0 !important;
        padding-left: 12px !important;
        padding-right: 12px !important;
      }

      /* Liste içeriklerinde yatay scroll izni */
      .app-page .frappe-list .result {
        overflow-x: auto;
      }
    `;
    const tag = document.createElement("style");
    tag.id = STYLE_ID;
    tag.textContent = css;
    document.head.appendChild(tag);
  }
},

    formatters: {
      // (2) TR: Last Sentiment – pozitif yeşil, negatif kırmızı, nötr gri; hafif arka plan
      last_sentiment(val) {
        const raw = String(val || "").toLowerCase();
        let k = "neutral",
          em = "😐";
        if (/positive|pozitif/.test(raw)) {
          k = "positive";
          em = "🙂";
        } else if (/negative|negatif/.test(raw)) {
          k = "negative";
          em = "🙁";
        }
        return pill(`${em} ${frappe.utils.escape_html(val || "-")}`, `hd-sent ${k}`, {
          title: "Last Sentiment",
        });
      },

      // (3) TR: Sentiment Trend – ikon + renk (yukarı iyi, sabit nötr, aşağı kötü)
      sentiment_trend(val) {
        const raw = String(val || "").toLowerCase();
        let k = "steady",
          icon = "➡️";
        if (/improv|iyileş|art/.test(raw)) {
          k = "up";
          icon = "📈";
        } else if (/wors|kötü|azal/.test(raw)) {
          k = "down";
          icon = "📉";
        }
        return pill(`${icon} ${frappe.utils.escape_html(val || "-")}`, `hd-trend ${k}`, {
          title: "Sentiment Trend",
        });
      },

      // (4) TR: Effort Score – TEK sayı; locale uyumlu; sadece çerçeve rengi (düşük=iyi)
      effort_score(val) {
        const num = toNumber(val);
        const txt = isFinite(num) ? formatNum(num, 2) : "-";
        const band = bandForScore(num); // good/mid/bad
        // TR: İçerik olarak sadece sayıyı yaz; ekstra ::after KULLANMIYORUZ => tekrar yok.
        return chip(`${txt}`, `hd-score ${band}`, { title: "Effort Score" });
      },

      // (5) TR: Effort Band – sadece çerçeve rengi; Low=iyi (yeşil), High=kırmızı
      effort_band(val) {
        const raw = String(val || "").toLowerCase();
        const k = /low|düşük/.test(raw)
          ? "low"
          : /high|yüksek/.test(raw)
          ? "high"
          : "medium";
        return chip(`${frappe.utils.escape_html(val || "-")}`, `hd-eff ${k}`, {
          title: "Effort Band",
        });
      },

      // (6) TR: Priority – standard chip (renk çerçevede)
      priority(val) {
        const v = String(val || "").toLowerCase();
        const k = v === "high" ? "high" : v === "low" ? "low" : "med";
        return chip(frappe.utils.escape_html(val || "-"), `hd-pri ${k}`);
      },

      // (7) TR: Status – Frappe’nin orijinal indicator-pill davranışına DOKUNMA
      status(val) {
        return frappe.utils.escape_html(val || "-");
      },
    },
  };

  /* =====================[ Yardımcılar ]===================== */
  function pill(text, cls, attrs = {}) {
    const a = Object.entries(attrs)
      .map(([k, v]) =>
        v !== undefined && v !== "" ? ` ${k}="${frappe.utils.escape_html(v)}"` : ""
      )
      .join("");
    return `<span class="hd-pill ${cls}"${a}>${text}</span>`;
  }
  function chip(text, cls, attrs = {}) {
    const a = Object.entries(attrs)
      .map(([k, v]) =>
        v !== undefined && v !== "" ? ` ${k}="${frappe.utils.escape_html(v)}"` : ""
      )
      .join("");
    return `<span class="hd-chip ${cls}"${a}>${text}</span>`;
  }
  function toNumber(x) {
    if (x == null) return NaN;
    return parseFloat(String(x).replace(",", ".").replace(/[^\d.-]/g, ""));
  }
  function formatNum(n, digits = 2) {
    try {
      // TR: Türkçe biçimi (virgül) koru
      return new Intl.NumberFormat("tr-TR", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      }).format(n);
    } catch {
      return String(n.toFixed(digits)).replace(".", ",");
    }
  }
  function bandForScore(n) {
    if (!isFinite(n)) return "mid";
    if (n <= SCORE_THRESHOLDS.good) return "good";
    if (n <= SCORE_THRESHOLDS.mid) return "mid";
    return "bad";
  }

  /* =====================[ CSS ]===================== */
  function inject_css_once() {
    if (document.getElementById(CSS_ID)) return;
    const css = `
:root{
  --hd-ok:#16a34a;      /* yeşil */
  --hd-ok-bg:#ecfdf5;   /* yeşil çok hafif arka plan */
  --hd-mid:#f59e0b;     /* turuncu */
  --hd-low:#9ca3af;     /* gri */
  --hd-red:#ef4444;     /* kırmızı */
  --hd-red-bg:#fef2f2;  /* kırmızı çok hafif arka plan */
}

/* Satır hover */
.result .list-row-container:hover{ background: rgba(0,0,0,.03); }

/* PILL – ortak görünüm */
.hd-pill{
  display:inline-flex; align-items:center; gap:6px;
  padding:2px 8px; border-radius:999px; border:1px solid #e5e7eb; background:#fff; line-height:1.25;
}
.hd-pill::before{ content:""; width:8px; height:8px; border-radius:999px; background:var(--hd-low); }

/* Last Sentiment: hafif arka plan + nokta rengi */
.hd-sent.positive{ border-color: var(--hd-ok); background: var(--hd-ok-bg); color:#065f46; }
.hd-sent.positive::before{ background: var(--hd-ok); }

.hd-sent.neutral { border-color: var(--hd-low); }
.hd-sent.neutral::before{ background: var(--hd-low); }

.hd-sent.negative{ border-color: var(--hd-red); background: var(--hd-red-bg); color:#7f1d1d; }
.hd-sent.negative::before{ background: var(--hd-red); }

/* Trend – ikon zaten içerikte, sadece çerçeve rengi */
.hd-trend.up{ border-color: var(--hd-ok); }
.hd-trend.steady{ border-color: var(--hd-low); }
.hd-trend.down{ border-color: var(--hd-red); }

/* CHIP – sade çerçeve (arka plan beyaz), düşük=iyi mantığına göre renkler */
.hd-chip{
  display:inline-flex; align-items:center; padding:2px 8px;
  border-radius:999px; border:1px solid rgba(0,0,0,.12); background:#fff; line-height:1.2;
}

/* Effort Score: sadece çerçeve rengi */
.hd-score.good{ border-color: var(--hd-ok); }
.hd-score.mid { border-color: var(--hd-mid); }
.hd-score.bad { border-color: var(--hd-red); }

/* Effort Band: Low=iyi */
.hd-eff.low{ border-color: var(--hd-ok); }
.hd-eff.medium{ border-color: var(--hd-mid); }
.hd-eff.high{ border-color: var(--hd-red); }

/* Priority: bilgi amaçlı (aynı kaldı) */
.hd-pri.high{ border-color: var(--hd-red); }
.hd-pri.med { border-color: var(--hd-mid); }
.hd-pri.low{ border-color: var(--hd-low); }
`;
    const tag = document.createElement("style");
    tag.id = CSS_ID;
    tag.textContent = css;
    document.head.appendChild(tag);
  }
})();
