// HelpdeskAI Settings – Lisans butonları + durum başlığı (Yeni API + Reactivate)
frappe.ui.form.on("HelpdeskAI Settings", {
  refresh(frm) {
    frm.dashboard.clear_headline();

    // TR: Rozet + başlık
    frappe
      .call({ method: "helpdesk.api.license.gatekeeper", type: "GET" })
      .then((r) => {
        const status = (r?.message?.status || "unknown").toUpperCase();
        const map = { VALID: "green", GRACE: "orange", INVALID: "red", UNKNOWN: "gray", NETWORK_ERROR: "gray" };
        frm.dashboard.add_indicator(__("License Status: {0}", [status]), map[status] || "gray");

        const exp = frm.doc.expires_at ? frappe.datetime.str_to_user(frm.doc.expires_at) : __("—");
        const last = frm.doc.last_check_on ? frappe.datetime.str_to_user(frm.doc.last_check_on) : __("—");
        const lastRes = frm.doc.last_check_status || "UNKNOWN";
        frm.dashboard.set_headline(__("Expires At: {0} | Last Check: {1} ({2})", [exp, last, lastRes]));
      })
      .catch(() => {
        frm.dashboard.add_indicator(__("License Status: {0}", ["UNKNOWN"]), "gray");
      });

    // TR: Aksiyon butonları
    add_license_buttons(frm);
  },
});

function add_license_buttons(frm) {
  frm.clear_custom_buttons();

  /**
   * TR: Ortak çağrı wrapper'ı
   * @param {string} method - Sunucu metodu
   * @param {string} label - UI etiketi
   * @param {boolean} needsKey - license_key gerekli mi?
   * @param {boolean} needsToken - activation_token gerekli mi?
   */
  const run = (method, label, needsKey = false, needsToken = false) => {
    // TR: Ön-koşullar
    if (needsKey && !frm.doc.license_key) {
      frappe.msgprint(__("Önce geçerli bir 'License Key' girip kaydedin."));
      return;
    }
    if (needsToken && !frm.doc.activation_token) {
      frappe.msgprint(__("Bu işlem için 'Activation Token' gerekli. Lütfen önce Activate çalıştırın."));
      return;
    }

    // TR: Çağrı
    frappe.dom.freeze(__(`${label} çalışıyor...`));
    frappe
      .call({ method, type: "POST" })
      .then((r) => {
        const st = (r?.message?.status || "").toString().toUpperCase();
        const ok = !!r?.message?.ok;
        const msg = st ? `${label}: ${st}` : `${label} tamamlandı`;
        frappe.show_alert({ message: __(msg), indicator: ok ? "green" : "orange" });
      })
      .catch((e) => {
        frappe.msgprint({ title: __(label + " Hatası"), message: e?.message || e, indicator: "red" });
      })
      .always(() => {
        frappe.dom.unfreeze();
        frm.reload_doc();
      });
  };

  // TR: Yeni API uçları: activate / reactivate / validate / deactivate
  frm.add_custom_button(
    __("Activate License"),
    () => run("helpdesk.api.license.activate", "Activate", true),
    __("License")
  );

  // TR: **YENİ** Reactivate butonu – token gerektirir
  frm.add_custom_button(
    __("Reactivate License"),
    () => run("helpdesk.api.license.reactivate", "Reactivate", true, true),
    __("License")
  );

  frm.add_custom_button(
    __("Validate Now"),
    () => run("helpdesk.api.license.validate", "Validate", true),
    __("License")
  );

  frm.add_custom_button(
    __("Deactivate License"),
    () =>
      frappe.confirm(
        __("Lisansı devre dışı bırakmak istediğinize emin misiniz?"),
        () => run("helpdesk.api.license.deactivate", "Deactivate", false)
      ),
    __("License")
  );

  // TR: Bilgi – parmak izi kopyalama (opsiyonel kalite-of-life)
  if (frm.doc.device_fingerprint) {
    frm.add_custom_button(
      __("Copy Fingerprint"),
      () => {
        frappe.utils.copy_to_clipboard(frm.doc.device_fingerprint);
        frappe.show_alert({ message: __("Fingerprint panoya kopyalandı."), indicator: "green" });
      },
      __("License")
    );
  }
}
