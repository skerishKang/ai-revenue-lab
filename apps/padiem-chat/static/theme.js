(function(){
  "use strict";
  const STORAGE_KEY = "padiem_theme";
  const VALID = ["light","dark","cinematic","padiem-home"];
  const THEME_COLORS = { light:"#f8f8fb", dark:"#0b0c0e", cinematic:"#06080d", "padiem-home":"#e6e9ee" };
  const COLOR_SCHEMES = { light:"light", dark:"dark", cinematic:"dark", "padiem-home":"light" };

  function isValid(t){ return VALID.indexOf(t)!==-1; }
  function getSystemFallback(){
    try{
      if(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) return "dark";
    }catch(e){}
    return "light";
  }
  function getSaved(){
    try{ var v=localStorage.getItem(STORAGE_KEY); if(isValid(v)) return v; }catch(e){}
    return null;
  }
  function getCurrent(){
    var cur = document.documentElement.getAttribute("data-theme");
    if(isValid(cur)) return cur;
    var saved=getSaved();
    if(saved) return saved;
    return getSystemFallback();
  }
  function applyTheme(theme, persist){
    if(!isValid(theme)) return;
    document.documentElement.setAttribute("data-theme", theme);
    // also set on body for compatibility with older CSS that targets body
    if(document.body) document.body.setAttribute("data-theme", theme);
    var cs = COLOR_SCHEMES[theme] || "dark";
    var mc = document.querySelector('meta[name="color-scheme"]');
    if(mc) mc.setAttribute("content", cs);
    var tc = document.querySelector('meta[name="theme-color"]');
    if(tc) tc.setAttribute("content", THEME_COLORS[theme] || "#06080d");
    if(persist){
      try{ localStorage.setItem(STORAGE_KEY, theme); }catch(e){}
    }
    syncPicker(theme);
    try{
      window.dispatchEvent(new CustomEvent("padiem:themechange", {detail:{theme:theme}}));
    }catch(e){}
  }
  function syncPicker(theme){
    var picker=document.getElementById("themePicker");
    if(!picker) return;
    var opts=picker.querySelectorAll("[data-theme-value]");
    opts.forEach(function(btn){
      var v=btn.getAttribute("data-theme-value");
      var active=v===theme;
      btn.setAttribute("aria-pressed", active ? "true" : "false");
      // for a11y state, also set aria-current when active
      if(active) btn.setAttribute("aria-current","true");
      else btn.removeAttribute("aria-current");
    });
  }
  function init(){
    // Ensure data-theme is set (inline script already did, but double-check)
    var cur=document.documentElement.getAttribute("data-theme");
    if(!isValid(cur)){
      var saved=getSaved();
      var initial = saved || getSystemFallback();
      applyTheme(initial, false);
    } else {
      // sync picker to current
      syncPicker(cur);
      if(document.body) document.body.setAttribute("data-theme", cur);
    }
    var picker=document.getElementById("themePicker");
    if(!picker) return;
    picker.addEventListener("click", function(e){
      var btn=e.target.closest("[data-theme-value]");
      if(!btn) return;
      var t=btn.getAttribute("data-theme-value");
      if(!isValid(t)) return;
      applyTheme(t, true);
    });
    // keyboard: buttons natively handle Enter/Space; ensure focus stays
    // also listen for storage events (cross-tab)
    window.addEventListener("storage", function(e){
      if(e.key===STORAGE_KEY && isValid(e.newValue)){
        applyTheme(e.newValue, false);
      }
    });
    // react to system change only when no explicit saved preference
    try{
      var mql=window.matchMedia("(prefers-color-scheme: dark)");
      var handler=function(){
        if(getSaved()) return; // explicit choice wins
        var fallback=getSystemFallback();
        applyTheme(fallback, false);
      };
      if(mql.addEventListener) mql.addEventListener("change", handler);
      else if(mql.addListener) mql.addListener(handler);
    }catch(e){}
  }
  // expose for tests / debugging without polluting global
  window.__padiemTheme = { VALID: VALID, getSaved: getSaved, getCurrent: getCurrent, applyTheme: applyTheme, STORAGE_KEY: STORAGE_KEY };

  if(document.readyState==="loading"){
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
