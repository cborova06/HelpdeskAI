// /home/frappe/frappe-bench/apps/helpdesk/helpdesk/helpdesk/doctype/hd_ticket/hd_ticket.js
// TR: HD Ticket – AI Insights v8 (uyumlu upgrade; DOM boyama + UX iyileştirmeleri, kırılım yok)

(function(){
  // ------------ Küresel hafıza (form başına cache ve event temizliği) ------------
  const FORM_CACHE = new WeakMap(); // frm -> {scope, fields, observer}
  const NS = ".ai_v8";

  // ------------ Küçük yardımcılar ------------
  const raf = (fn)=> window.requestAnimationFrame ? requestAnimationFrame(fn) : setTimeout(fn,16);
  const debounce = (fn, ms=120)=>{ let t; return function(...a){ clearTimeout(t); t=setTimeout(()=>fn.apply(this,a), ms); }; };
  const throttle = (fn, ms=120)=>{ let t=0; return function(...a){ const now=Date.now(); if(now-t>=ms){ t=now; fn.apply(this,a);} }; };

  // (1) TR: Form açılış/yenileme ve sekme geçişinde UI uygula (event namespaced)
  frappe.ui.form.on("HD Ticket", {
    refresh(frm) {
      init_ai_ui(frm);
      const $tabs = $(frm.wrapper).find(".form-tabs .nav-link");
      $tabs.off("shown.bs.tab"+NS).on("shown.bs.tab"+NS, () => init_ai_ui(frm));
    },
    // (1b) TR: Form kapatılırken/yeniden yüklenirken observer ve event’leri temizle
    on_form_unload(frm){
      teardown(frm);
    }
  });

  function init_ai_ui(frm){
    // (2) TR: Global CSS tek sefer
    inject_css_v8();

    // (3) TR: AI sekmesi kapsamını bul + cache’le
    let cache = FORM_CACHE.get(frm);
    if(!cache){ cache = {}; FORM_CACHE.set(frm, cache); }
    let $scope = cache.scope || resolve_ai_scope(frm);
    if(!$scope){ setTimeout(()=>init_ai_ui(frm), 120); return; }
    cache.scope = $scope;

    // (4) TR: Başlığı sade bırak (gradyans yok) ve kapsamı işaretle
    $scope.addClass("hd-ai--plain");

    // (5) TR: Alanları tek sefer yakala (DOM sorgularını azalt)
    cache.fields = cache.fields || pick_fields(frm, [
      "ai_summary","ai_reply_suggestion","last_sentiment","sentiment_trend",
      "effort_score","effort_band","route_confidence","problem_confidence","sentiment_analysis_section"
    ]);

    // (6) TR: AI Summary kutusu + etikete 🤖 (idempotent)
    style_summary(frm, cache);

    // (7) TR: Editör yumuşatma + emoji/kopyala bar (klavye erişimi + ARIA)
    soften_editor(frm,"ai_summary");
    soften_editor(frm,"ai_reply_suggestion");
    emoji_toolbar(frm,"ai_summary");
    emoji_toolbar(frm,"ai_reply_suggestion");

    // (8) TR: Metrik alanlarını pill görünümü
    ["last_sentiment","sentiment_trend","effort_score","effort_band","route_confidence","problem_confidence"]
      .forEach(fn=>pillify(frm,fn));

    // (9) TR: Dinamik bayraklar + meter yüzdeleri + label emoji
    const do_flags = throttle(()=>update_value_flags(frm), 120);
    const do_meters = throttle(()=>update_meters(frm,["route_confidence","problem_confidence"]), 120);
    const do_labels = debounce(()=>decorate_labels(frm), 60);
    do_flags(); do_meters(); do_labels();

    // (10) TR: Reply Suggestion kart/ton/istatistik
    setup_reply_suggestion(frm);
    update_reply_suggestion_meta(frm);

    // (11) TR: Sekme re-render’larını gözlemle (tekil, disconnect yönetimi)
    attach_observer($scope, frm, ()=>{
      $scope.addClass("hd-ai--plain");
      do_flags(); do_meters(); do_labels();
      update_reply_suggestion_meta(frm);
    });
  }

  /* =====================[ Yardımcılar ]===================== */

  function resolve_ai_scope(frm){
    let $tab = $(frm.wrapper).find('.tab-pane[data-fieldname="ai_insights"]');
    if($tab.length) return $tab;
    $tab = $(frm.wrapper).find('[data-fieldname="ai_insights"]').closest('.tab-pane, .form-page, .layout-main-section');
    if($tab.length) return $tab;
    const anchors = ["sentiment_analysis_section","ai_summary","last_sentiment","ai_reply_suggestion"];
    for(const f of anchors){
      const fld = frm.get_field(f);
      if(fld && fld.$wrapper){
        const $p = fld.$wrapper.closest('.tab-pane, .form-page, .layout-main-section');
        if($p.length) return $p;
      }
    }
    return null;
  }

  function pick_fields(frm, names){
    const out={};
    names.forEach(n=>{
      const c=frm.get_field(n);
      if(c&&c.$wrapper) out[n]=c;
    });
    return out;
  }

  function style_summary(frm, cache){
    const sum = cache.fields?.ai_summary || frm.get_field("ai_summary");
    if(sum && sum.$wrapper && !sum.$wrapper.data("ai-sum-styled")){
      sum.$wrapper.data("ai-sum-styled",1);
      sum.$wrapper.addClass("ai-summary-box");
      const $label = sum.$wrapper.find("label.control-label").first();
      if($label.length && !$label.data("ai-sum-label")){
        $label.data("ai-sum-label",1);
        $label.prepend("🤖 ");
      }
    }
  }

  function soften_editor(frm, fieldname){
    const c=frm.get_field(fieldname);
    if(c&&c.$wrapper)
      c.$wrapper.find(".ql-editor, textarea, .control-input").addClass("hd-ai-soft");
  }

  function emoji_toolbar(frm, fieldname){
    const c=frm.get_field(fieldname); if(!c||!c.$wrapper) return;
    if(c.$wrapper.data("ai-emoji")) return; c.$wrapper.data("ai-emoji",1);

    const $ctrl=c.$wrapper.find(".frappe-control").first();
    const $bar=$(`<div class="ai-emoji-bar" role="toolbar" aria-label="AI kısayolları"></div>`);

    const addBtn = (label, onClick, extraClass="")=>{
      const $b=$(`<button type="button" class="ai-emoji ${extraClass}" aria-label="${label}" title="${label}"></button>`)
        .text(label).on("click", onClick)
        .on("keydown", (e)=>{ if(e.key==="Enter"||e.key===" "){ e.preventDefault(); onClick(); }});
      $bar.append($b);
      return $b;
    };

    ["✅","⚡","✨","🚀","🧠","📈","🧩","📌","🤝","⏱️","🔧","💬"]
      .forEach(e=> addBtn(e, ()=>append_emoji(frm,fieldname,e)));

    // Kopyala (güvenli, http ortamında fallback)
    addBtn("Kopyala", async ()=>{
      const html=(frm.doc[fieldname]||"")+""; const tmp=document.createElement("div"); tmp.innerHTML=html;
      const text=(tmp.innerText||tmp.textContent||html).trim();
      try{
        if(navigator.clipboard && window.isSecureContext){
          await navigator.clipboard.writeText(text);
        }else{
          const ta=document.createElement("textarea");
          ta.value=text; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
        }
        frappe.show_alert({message:"Kopyalandı ✅",indicator:"green"});
      }catch{
        frappe.show_alert({message:"Kopyalanamadı",indicator:"red"});
      }
    },"ai-copy");

    $ctrl.prepend($bar);
  }

  function append_emoji(frm,f,e){
    const cur=(frm.doc[f]||"")+"", sep=cur && !cur.endsWith(" ")?" ":"";
    frm.set_value(f,cur+sep+e).then(()=>frm.dirty());
  }

  function pillify(frm, fieldname){
    const c=frm.get_field(fieldname);
    if(c&&c.$wrapper) c.$wrapper.addClass("ai-pill").attr("data-fieldname",fieldname);
  }

  function update_value_flags(frm){
    set_value_flag(frm,"last_sentiment",(raw)=>{
      if(/pozitif|positive/.test(raw)) return "positive";
      if(/negatif|negative/.test(raw)) return "negative";
      return "neutral";
    });
    set_value_flag(frm,"effort_band",(raw)=>{
      if(/low|düşük/.test(raw)) return "low";
      if(/high|yüksek/.test(raw)) return "high";
      return "medium";
    });
    set_trend_flag(frm,"sentiment_trend");
  }

  function set_value_flag(frm, fieldname, mapper){
    const c=frm.get_field(fieldname); if(!c||!c.$wrapper) return;
    const norm = mapper(((frm.doc[fieldname]||"")+"").toLowerCase().trim());
    c.$wrapper.attr("data-value", norm);
  }

  function set_trend_flag(frm, field){
    const c=frm.get_field(field); if(!c||!c.$wrapper) return;
    const raw=((frm.doc[field]||"")+"").toLowerCase();
    let t="steady"; if(/improv|iyileş|art/.test(raw)) t="up"; else if(/wors|kötü|azal/.test(raw)) t="down";
    c.$wrapper.attr("data-trend", t);
  }

  function update_meters(frm, fields){
    fields.forEach(fn=>{
      const c=frm.get_field(fn); if(!c||!c.$wrapper) return;
      let v=Number(frm.doc[fn]||0); if(isNaN(v)) v=0;
      v=Math.max(0,Math.min(100,v));
      c.$wrapper[0].style.setProperty("--pct", v.toFixed(0));
      const col = v>=70? "var(--ai-green-500)" : (v>=40? "var(--ai-amber-500)" : "var(--ai-gray-400)");
      c.$wrapper[0].style.setProperty("--meter", col);
      c.$wrapper.attr("title", `${v.toFixed(0)}%`);
    });
  }

  function decorate_labels(frm){
    const map = {
      last_sentiment: {base:"Last Sentiment", em:{positive:"🙂", neutral:"😐", negative:"🙁"}},
      sentiment_trend:{base:"Sentiment Trend", em:{up:"📈", steady:"➡️", down:"📉"}},
      effort_score:   {base:"Effort Score", em:"⚙️"},
      effort_band:    {base:"Effort Band",  em:{low:"🟢", medium:"🟡", high:"🔴"}},
      route_confidence:{base:"Route Confidence", em:"🧭"},
      problem_confidence:{base:"Problem Confidence", em:"🧩"},
    };
    Object.keys(map).forEach(fn=>{
      const cfg=map[fn], ctrl=frm.get_field(fn);
      if(!ctrl||!ctrl.$wrapper) return;
      const $label = ctrl.$wrapper.find("label.control-label").first();
      if(!$label.length) return;
      const curVal = ctrl.$wrapper.attr("data-value") || ctrl.$wrapper.attr("data-trend") || "";
      const em = typeof cfg.em==="string" ? cfg.em : (cfg.em[curVal] || "");
      const key = "__ai_labeled_"+fn;
      if($label.data(key)) return;
      $label.data(key,1);
      $label.text(`${em? em+" " : ""}${cfg.base}`);
    });
  }

  function setup_reply_suggestion(frm){
    const c = frm.get_field("ai_reply_suggestion");
    if(!c || !c.$wrapper) return;

    const $label = c.$wrapper.find("label.control-label").first();
    if($label.length && !$label.data("ai-rs-labeled")){
      $label.data("ai-rs-labeled",1);
      $label.prepend("📬 ");
    }
    c.$wrapper.addClass("ai-reply-box");

    const $edit = c.$wrapper.find(".ql-editor, textarea, .control-input").first();
    if($edit.length && !$edit.data("ai-rs-watch")){
      $edit.data("ai-rs-watch",1);
      const handler = debounce(()=> update_reply_suggestion_meta(frm), 120);
      $edit.on("input"+NS, handler);
      // (A11y) İçerik alanına landmark
      $edit.attr("role","region").attr("aria-label","AI Reply İçeriği");
    }
    if(!frm.__ai_rs_bound){
      frm.__ai_rs_bound = true;
      frappe.ui.form.on("HD Ticket", "ai_reply_suggestion", function(f){ update_reply_suggestion_meta(f); });
    }
  }

  function update_reply_suggestion_meta(frm){
    const c = frm.get_field("ai_reply_suggestion");
    if(!c || !c.$wrapper) return;

    const html = (frm.doc.ai_reply_suggestion || "") + "";
    // XSS güvenliği: yalnızca text’e indirgeriz
    const tmp = document.createElement("div"); tmp.innerHTML = html;
    const text = (tmp.innerText || tmp.textContent || "").trim();

    const words = text ? text.split(/\s+/).filter(Boolean).length : 0;
    const secs  = Math.max(1, Math.round(words / 3.5)); // ~3.5 wps
    const $edit = c.$wrapper.find(".ql-editor, textarea, .control-input").first();

    c.$wrapper.toggleClass("has-content", words > 0);
    if($edit.length){
      $edit.attr("data-words", words);
      $edit.attr("data-rt", secs);
      $edit.attr("aria-live","polite").attr("aria-atomic","true");
    }

    const raw = (frm.doc.last_sentiment || "").toString().toLowerCase();
    let tone = "neutral";
    if(/positive|pozitif/.test(raw)) tone = "positive";
    else if(/negative|negatif/.test(raw)) tone = "negative";
    c.$wrapper.attr("data-tone", tone);
  }

  function attach_observer($scope, frm, onChange){
    const cache = FORM_CACHE.get(frm) || {};
    if(cache.observer){ return; }
    const obs=new MutationObserver(()=> raf(onChange));
    obs.observe($scope.get(0),{childList:true,subtree:true});
    cache.observer = obs;
    FORM_CACHE.set(frm, cache);
  }

  function teardown(frm){
    const cache = FORM_CACHE.get(frm);
    if(!cache) return;
    // Observer’ı kapat
    if(cache.observer){ try{ cache.observer.disconnect(); }catch{} }
    // Sekme eventlerini temizle
    $(frm.wrapper).find(".form-tabs .nav-link").off(NS);
    FORM_CACHE.delete(frm);
  }

  /* =====================[ CSS Enjeksiyonu ]===================== */
  function inject_css_v8(){
    if(document.getElementById("ai-css-v8")) return;
    const css = `
  :root{
    --ai-green-500:#22c55e; --ai-amber-500:#f59e0b; --ai-gray-400:#9ca3af; --ai-red-500:#ef4444;
    --ai-card-shadow: 0 2px 10px rgba(0,0,0,.04);
  }
  @media (prefers-color-scheme: dark){
    :root{
      --ai-gray-400:#9ca3af; --ai-amber-500:#f59e0b; --ai-green-500:#22c55e; --ai-red-500:#ef4444;
    }
    .hd-ai--plain .section-head{ background:#0b1220; border-color:#25324a; box-shadow:0 2px 12px rgba(0,0,0,.35); }
    .ai-summary-box .ql-editor, .ai-summary-box textarea, .ai-summary-box .control-input{
      background: linear-gradient(90deg,#0b1a2a,#1a1f2e);
      border-color:#25324a; border-left-color:#3b82f6;
    }
    .ai-reply-box .ql-editor, .ai-reply-box textarea, .ai-reply-box .like-disabled-input{
      background:#0b1220; border-color:#25324a;
    }
  }

  /* Başlık/Bölüm – sade */
  .hd-ai--plain .section-head{
    background:#fff; border:1px solid #f1d08c; border-radius:10px;
    padding:8px 12px; margin:6px 0 12px 0; box-shadow:var(--ai-card-shadow);
  }

  /* Genel UI – boşluk sıkı */
  .hd-ai--plain .section-body{ padding-top:8px; }
  .hd-ai--plain .frappe-control{ margin-bottom:8px !important; }
  .hd-ai--plain label.control-label{ margin-bottom:4px !important; }
  .hd-ai--plain .like-disabled-input, .hd-ai--plain .control-input{ min-height:30px; }
  .hd-ai--plain .section-body > .row{ row-gap:10px; }
  @media (max-width: 992px){
    .hd-ai--plain .frappe-control{ margin-bottom:6px !important; }
    .hd-ai--plain .form-column{ gap:6px; }
  }

  /* Reduced motion */
  @media (prefers-reduced-motion: reduce){
    .ai-emoji:hover{ transform:none !important; }
    .ai-pill[data-fieldname="last_sentiment"][data-value="negative"] .like-disabled-input::before{ animation:none !important; }
  }

  /* Editor yumuşatma */
  .hd-ai-soft{
    box-shadow: inset 0 0 0 2px rgba(0,0,0,.03), 0 3px 14px rgba(0,0,0,.04) !important;
    border-radius:12px !important;
  }

  /* Emoji araç çubuğu */
  .ai-emoji-bar{ display:flex; flex-wrap:wrap; gap:6px; margin:6px 0 8px 0; align-items:center; }
  .ai-emoji{ border:1px solid rgba(0,0,0,.08); border-radius:8px; padding:4px 6px; background:#fff; cursor:pointer; font-size:16px; }
  .ai-emoji:hover{ transform: translateY(-1px); }
  .ai-copy{ margin-left:auto; border:1px solid rgba(0,0,0,.08); border-radius:8px; padding:4px 8px; background:#fff; cursor:pointer; font-size:12px; font-weight:600; }

  /* Pill görünümü */
  .ai-pill .control-input, .ai-pill .control-value, .ai-pill .like-disabled-input{
    background:#fff !important; border:1px solid rgba(0,0,0,.08) !important;
    border-radius:999px !important; padding:5px 10px 5px 26px !important;
    min-height:30px; box-shadow:0 1px 4px rgba(0,0,0,.04); position:relative;
  }
  .ai-pill .control-input::before, .ai-pill .control-value::before, .ai-pill .like-disabled-input::before{
    content:""; position:absolute; left:10px; top:50%; transform:translateY(-50%); width:10px; height:10px; border-radius:999px; background:var(--ai-gray-400);
  }

  /* Sentiment renk */
  .ai-pill[data-fieldname="last_sentiment"][data-value="positive"] .like-disabled-input::before,
  .ai-pill[data-fieldname="last_sentiment"][data-value="positive"] .control-input::before{ background:var(--ai-green-500); }
  .ai-pill[data-fieldname="last_sentiment"][data-value="neutral"]  .like-disabled-input::before,
  .ai-pill[data-fieldname="last_sentiment"][data-value="neutral"]  .control-input::before{ background:var(--ai-gray-400); }
  .ai-pill[data-fieldname="last_sentiment"][data-value="negative"] .like-disabled-input::before,
  .ai-pill[data-fieldname="last_sentiment"][data-value="negative"] .control-input::before{ background:var(--ai-red-500); animation: ai-pulse 1.8s infinite; }
  @keyframes ai-pulse{0%{transform:translateY(-50%) scale(.9)}50%{transform:translateY(-50%) scale(1.15)}100%{transform:translateY(-50%) scale(.9)}}

  /* Trend oku */
  .ai-pill[data-fieldname="sentiment_trend"][data-trend="up"] .like-disabled-input::before,
  .ai-pill[data-fieldname="sentiment_trend"][data-trend="up"] .control-input::before{
    width:0;height:0;border-left:6px solid transparent;border-right:6px solid transparent;border-bottom:10px solid var(--ai-green-500);border-radius:0; left:13px;
  }
  .ai-pill[data-fieldname="sentiment_trend"][data-trend="down"] .like-disabled-input::before,
  .ai-pill[data-fieldname="sentiment_trend"][data-trend="down"] .control-input::before{
    width:0;height:0;border-left:6px solid transparent;border-right:6px solid transparent;border-top:10px solid var(--ai-red-500);border-radius:0; left:13px;
  }

  /* Effort band noktası */
  .ai-pill[data-fieldname="effort_band"][data-value="low"] .like-disabled-input::before,
  .ai-pill[data-fieldname="effort_band"][data-value="low"] .control-input::before{ background:var(--ai-green-500); }
  .ai-pill[data-fieldname="effort_band"][data-value="medium"] .like-disabled-input::before,
  .ai-pill[data-fieldname="effort_band"][data-value="medium"] .control-input::before{ background:var(--ai-amber-500); }
  .ai-pill[data-fieldname="effort_band"][data-value="high"] .like-disabled-input::before,
  .ai-pill[data-fieldname="effort_band"][data-value="high"] .control-input::before{ background:var(--ai-red-500); }

  /* Meter (Route/Problem) */
  .ai-pill[data-fieldname="route_confidence"] .like-disabled-input,
  .ai-pill[data-fieldname="route_confidence"] .control-input,
  .ai-pill[data-fieldname="problem_confidence"] .like-disabled-input,
  .ai-pill[data-fieldname="problem_confidence"] .control-input{
    --pct:0; --meter:var(--ai-gray-400);
    background-image: linear-gradient(90deg, color-mix(in srgb, var(--meter) 25%, transparent),
                                           color-mix(in srgb, var(--meter) 25%, transparent));
    background-repeat:no-repeat; background-size: calc(var(--pct) * 1%) 100%; background-position:0 0;
  }

  /* AI Summary – kompakt kart */
  .ai-summary-box .ql-editor, .ai-summary-box textarea, .ai-summary-box .control-input{
    background: linear-gradient(90deg,#f0f9ff,#fef9c3);
    border: 1px solid #e2e8f0; border-left: 4px solid #3b82f6;
    border-radius: 10px; box-shadow: var(--ai-card-shadow);
    padding:8px !important; min-height:72px;
  }
  .ai-summary-box{ margin-bottom:8px; }
  .ai-summary-box label.control-label{ font-weight:600; color:#1e3a8a; }

  /* AI Reply Suggestion – kart */
  .ai-reply-box .ql-editor, .ai-reply-box textarea, .ai-reply-box .like-disabled-input{
     position:relative; background:#fff; border:1px solid #e5e7eb; border-left:4px solid var(--ai-green-500);
     border-radius:12px; padding:10px !important; min-height:78px;
     box-shadow:var(--ai-card-shadow); transition:border-color .2s ease, box-shadow .2s ease;
   }
  .ai-reply-box.has-content .ql-editor, .ai-reply-box.has-content textarea, .ai-reply-box.has-content .control-input{
    background: linear-gradient(90deg, #ecfeff 0%, #f0fdf4 55%, #fef9c3 100%);
    box-shadow: 0 6px 18px rgba(0,0,0,.06);
  }
  .ai-reply-box.has-content .ql-editor::before, .ai-reply-box.has-content textarea::before, .ai-reply-box.has-content .like-disabled-input::before{
     content:"🤖 Suggested Reply"; position:absolute; top:-8px; left:12px;
     font-size:11px; font-weight:700; background:inherit; border:1px solid #e5e7eb; border-radius:999px; padding:2px 8px;
     box-shadow:0 2px 6px rgba(0,0,0,.05);
   }
  .ai-reply-box.has-content .ql-editor::after, .ai-reply-box.has-content textarea::after, .ai-reply-box.has-content .like-disabled-input::after{
     content: attr(data-words);
     position:absolute; right:10px; bottom:4px; font-size:10.5px; opacity:.65;
   }
  .ai-reply-box[data-tone="positive"] .ql-editor, .ai-reply-box[data-tone="positive"] textarea, .ai-reply-box[data-tone="positive"] .like-disabled-input{ border-left-color:var(--ai-green-500); }
  .ai-reply-box[data-tone="negative"] .ql-editor, .ai-reply-box[data-tone="negative"] textarea, .ai-reply-box[data-tone="negative"] .like-disabled-input{ border-left-color:var(--ai-red-500); }
  .ai-reply-box[data-tone="neutral"]  .ql-editor, .ai-reply-box[data-tone="neutral"]  textarea, .ai-reply-box[data-tone="neutral"]  .like-disabled-input{ border-left-color:var(--ai-gray-400); }
  .ai-reply-box.has-content .ql-editor:hover, .ai-reply-box.has-content textarea:hover, .ai-reply-box.has-content .like-disabled-input:hover{
     box-shadow:0 8px 20px rgba(0,0,0,.08);
   }
  .ai-reply-box label.control-label{ font-weight:600; color:#065f46; }
    `;
    const tag=document.createElement("style"); tag.id="ai-css-v8"; tag.textContent=css; document.head.appendChild(tag);
  }
})();
