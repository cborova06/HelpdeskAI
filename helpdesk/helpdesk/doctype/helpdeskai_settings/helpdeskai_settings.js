// HelpdeskAI Settings – Lisans butonları + durum başlığı
frappe.ui.form.on("HelpdeskAI Settings", {
  refresh(frm) {
    frm.dashboard.clear_headline();

    // Rozet + başlık
    frappe.call({ method: "helpdesk.api.license.gatekeeper", type: "GET" }).then((r) => {
      const status = (r?.message?.status || "unknown").toUpperCase();
      const map = { VALID: "green", GRACE: "orange", INVALID: "red", UNKNOWN: "gray", NETWORK_ERROR: "gray" };
      frm.dashboard.add_indicator(__("License Status: {0}", [status]), map[status] || "gray");

      const exp = frm.doc.expires_at ? frappe.datetime.str_to_user(frm.doc.expires_at) : __("—");
      const last = frm.doc.last_check_on ? frappe.datetime.str_to_user(frm.doc.last_check_on) : __("—");
      const lastRes = frm.doc.last_check_status || "UNKNOWN";
      frm.dashboard.set_headline(__("Expires At: {0} | Last Check: {1} ({2})", [exp, last, lastRes]));
    });

    // Aksiyon butonları
    add_license_buttons(frm);
  },
});

function add_license_buttons(frm) {
  frm.clear_custom_buttons();

  const run = (method, label) => {
    console.log("[HelpdeskAI]", "call:", method);
    if (!frm.doc.license_key) {
      frappe.msgprint(__("Önce geçerli bir 'License Key' girip kaydedin."));
      return;
    }
    frappe.dom.freeze(__(`${label} çalışıyor...`));
    frappe
      .call({ method, type: "POST" })
      .then((r) => {
        console.log("[HelpdeskAI]", method, "→", r?.message);
        const msg = r?.message?.status ? `${label}: ${r.message.status.toUpperCase()}` : `${label} tamamlandı`;
        frappe.show_alert({ message: __(msg), indicator: "green" });
      })
      .catch((e) => {
        console.error("[HelpdeskAI]", method, e);
        frappe.msgprint({ title: __(label + " Hatası"), message: e?.message || e, indicator: "red" });
      })
      .always(() => {
        frappe.dom.unfreeze();
        frm.reload_doc();
      });
  };

  frm.add_custom_button(__("Activate License"), () => run("helpdesk.api.license.activate", "Activate"), __("License"));
  frm.add_custom_button(__("Verify Now"), () => run("helpdesk.api.license.verify", "Verify"), __("License"));
  frm.add_custom_button(
    __("Deactivate License"),
    () =>
      frappe.confirm(__("Lisansı devre dışı bırakmak istediğinize emin misiniz?"), () =>
        run("helpdesk.api.license.deactivate", "Deactivate")
      ),
    __("License")
  );
}
