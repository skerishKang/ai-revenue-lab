(function(){
  "use strict";
  const VALID=["light","dark","cinematic","padiem-home"];
  const THEME_COLORS={light:"#f8f8fb",dark:"#131417",cinematic:"#04070d","padiem-home":"#e6e9ee"};
  const COLOR_SCHEMES={light:"light",dark:"dark",cinematic:"dark","padiem-home":"light"};
  function isValid(t){return VALID.indexOf(t)!==-1;}
  function getSystemFallback(){
    try{if(window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches) return "dark";}catch(e){}
    return "light";
  }
  function getUrlTheme(){
    try{
      var v=new URLSearchParams(location.search).get("theme");
      if(isValid(v)) return v;
    }catch(e){}
    return null;
  }
  function getCurrent(){
    var cur=document.documentElement.getAttribute("data-theme");
    if(isValid(cur)) return cur;
    var url=getUrlTheme();
    if(url) return url;
    return getSystemFallback();
  }
  function applyTheme(theme,persist){
    if(!isValid(theme)) return;
    document.documentElement.setAttribute("data-theme",theme);
    if(document.body) document.body.setAttribute("data-theme",theme);
    var cs=COLOR_SCHEMES[theme]||"dark";
    var mc=document.querySelector('meta[name="color-scheme"]'); if(mc) mc.setAttribute("content",cs);
    var tc=document.querySelector('meta[name="theme-color"]'); if(tc) tc.setAttribute("content",THEME_COLORS[theme]||"#04070d");
    if(persist){
      try{
        var url=new URL(location.href);
        if(url.searchParams.get("theme")!==theme){
          url.searchParams.set("theme",theme);
          history.replaceState(null,"",url.toString());
        }
      }catch(e){}
    }
    syncPicker(theme);
    try{window.dispatchEvent(new CustomEvent("padiem:themechange",{detail:{theme:theme}}));}catch(e){}
  }
  function syncPicker(theme){
    var picker=document.getElementById("themePicker");
    if(!picker) return;
    var opts=picker.querySelectorAll("[data-theme-value]");
    opts.forEach(function(btn){
      var v=btn.getAttribute("data-theme-value");
      var active=v===theme;
      btn.setAttribute("aria-pressed",active?"true":"false");
      if(active) btn.setAttribute("aria-current","true"); else btn.removeAttribute("aria-current");
    });
  }
  function init(){
    var cur=document.documentElement.getAttribute("data-theme");
    if(!isValid(cur)){
      var url=getUrlTheme();
      var initial=url||getSystemFallback();
      applyTheme(initial,false);
    } else {
      syncPicker(cur);
      if(document.body) document.body.setAttribute("data-theme",cur);
    }
    var picker=document.getElementById("themePicker");
    if(!picker) return;
    picker.addEventListener("click",function(e){
      var btn=e.target.closest("[data-theme-value]");
      if(!btn) return;
      var t=btn.getAttribute("data-theme-value");
      if(!isValid(t)) return;
      applyTheme(t,true);
    });
    window.addEventListener("popstate",function(){
      var url=getUrlTheme();
      if(url) applyTheme(url,false);
    });
    try{
      var mql=window.matchMedia("(prefers-color-scheme: dark)");
      var handler=function(){
        if(getUrlTheme()) return;
        var fallback=getSystemFallback();
        applyTheme(fallback,false);
      };
      if(mql.addEventListener) mql.addEventListener("change",handler);
      else if(mql.addListener) mql.addListener(handler);
    }catch(e){}
  }
  window.__padiemTheme={VALID:VALID,getUrlTheme:getUrlTheme,getCurrent:getCurrent,applyTheme:applyTheme};
  if(document.readyState==="loading"){document.addEventListener("DOMContentLoaded",init);} else {init();}
})();
