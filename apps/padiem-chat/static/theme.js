(function(){
  "use strict";
  const VALID=["light","dark","cinematic","padiem-home","padiem-glass"];
  const GLASS_VARIANTS=["female","male"];
  const THEME_COLORS={light:"#f8f8fb",dark:"#131417",cinematic:"#04070d","padiem-home":"#e6e9ee","padiem-glass":"#aeb6bf"};
  const COLOR_SCHEMES={light:"light",dark:"dark",cinematic:"dark","padiem-home":"light","padiem-glass":"light"};
  var glassMotionFrame=0;
  var glassObserver=null;

  function isValid(t){return VALID.indexOf(t)!==-1;}
  function isGlassVariant(v){return GLASS_VARIANTS.indexOf(v)!==-1;}

  function ensureStylesheet(href,marker){
    if(document.querySelector('link['+marker+']')) return;
    var link=document.createElement("link");
    link.rel="stylesheet";
    link.href=href;
    link.setAttribute(marker,"");
    document.head.appendChild(link);
  }

  function ensureGlassStyles(){
    ensureStylesheet("./padiem-glass.css","data-padiem-glass-theme");
    ensureStylesheet("./padiem-glass-portrait.css","data-padiem-glass-portrait");
  }

  function ensureGlassOption(){
    var picker=document.getElementById("themePicker");
    if(!picker || picker.querySelector('[data-theme-value="padiem-glass"]')) return;
    var button=document.createElement("button");
    button.type="button";
    button.className="theme-option";
    button.setAttribute("data-theme-value","padiem-glass");
    button.setAttribute("aria-pressed","false");
    button.textContent="Padiem Glass";
    picker.appendChild(button);
  }

  function getUrlGlassVariant(){
    try{
      var v=new URLSearchParams(location.search).get("glass");
      if(isGlassVariant(v)) return v;
    }catch(e){}
    return null;
  }

  function getGlassVariant(){
    var cur=document.documentElement.getAttribute("data-glass-variant");
    if(isGlassVariant(cur)) return cur;
    return getUrlGlassVariant()||"female";
  }

  function syncGlassVariant(variant,theme){
    var control=document.querySelector(".glass-variant-control");
    if(control) control.hidden=theme!=="padiem-glass";
    document.querySelectorAll("[data-glass-variant-value]").forEach(function(btn){
      var active=btn.getAttribute("data-glass-variant-value")===variant;
      btn.setAttribute("aria-pressed",active?"true":"false");
      if(active) btn.setAttribute("aria-current","true"); else btn.removeAttribute("aria-current");
    });
  }

  function applyGlassVariant(variant,persist){
    if(!isGlassVariant(variant)) return;
    document.documentElement.setAttribute("data-glass-variant",variant);
    if(document.body) document.body.setAttribute("data-glass-variant",variant);
    if(persist){
      try{
        var url=new URL(location.href);
        if(url.searchParams.get("glass")!==variant){
          url.searchParams.set("glass",variant);
          history.replaceState(null,"",url.toString());
        }
      }catch(e){}
    }
    syncGlassVariant(variant,getCurrent());
    queueGlassMotion();
    try{window.dispatchEvent(new CustomEvent("padiem:glassvariantchange",{detail:{variant:variant}}));}catch(e){}
  }

  function ensureGlassVariantControl(){
    var picker=document.getElementById("themePicker");
    if(!picker || document.querySelector(".glass-variant-control")) return;
    var control=document.createElement("div");
    control.className="glass-variant-control";
    control.hidden=true;

    var label=document.createElement("p");
    label.className="glass-variant-label";
    label.textContent="Padiem Glass background";
    control.appendChild(label);

    var group=document.createElement("div");
    group.className="glass-variant-picker";
    group.setAttribute("role","group");
    group.setAttribute("aria-label","Padiem Glass background selection");

    [["female","Female"],["male","Male"]].forEach(function(item){
      var button=document.createElement("button");
      button.type="button";
      button.className="glass-variant-option";
      button.setAttribute("data-glass-variant-value",item[0]);
      button.setAttribute("aria-pressed","false");
      button.textContent=item[1];
      group.appendChild(button);
    });
    control.appendChild(group);

    if(picker.parentNode) picker.parentNode.insertBefore(control,picker.nextSibling);
    control.addEventListener("click",function(e){
      var btn=e.target.closest("[data-glass-variant-value]");
      if(!btn) return;
      var variant=btn.getAttribute("data-glass-variant-value");
      applyGlassVariant(variant,true);
    });
    syncGlassVariant(getGlassVariant(),getCurrent());
  }

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
    if(theme==="padiem-glass") ensureGlassStyles();
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
    if(theme==="padiem-glass"){
      var requested=getUrlGlassVariant()||getGlassVariant();
      applyGlassVariant(requested,false);
    } else {
      syncGlassVariant(getGlassVariant(),theme);
    }
    syncPicker(theme);
    queueGlassMotion();
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
    syncGlassVariant(getGlassVariant(),theme);
  }

  function prefersReducedMotion(){
    try{return Boolean(window.matchMedia&&window.matchMedia("(prefers-reduced-motion: reduce)").matches);}catch(e){return false;}
  }

  function smoothstep(value){
    var v=Math.max(0,Math.min(1,value));
    return v*v*(3-2*v);
  }

  function pingPong(value){
    var phase=((value%2)+2)%2;
    return phase<=1?phase:2-phase;
  }

  function updateGlassMotion(){
    glassMotionFrame=0;
    if(getCurrent()!=="padiem-glass") return;
    var root=document.documentElement;
    if(prefersReducedMotion()){
      root.style.setProperty("--glass-art-x","0px");
      root.style.setProperty("--glass-art-y","0px");
      root.style.setProperty("--glass-art-scale","1");
      root.style.setProperty("--glass-mask-start","6%");
      root.style.setProperty("--glass-mask-full","24%");
      root.style.setProperty("--glass-reveal","0.8");
      return;
    }

    var list=document.getElementById("messageList");
    var messageCount=list?list.children.length:0;
    var conversationHeight=list?list.scrollHeight:0;
    var visibleConversation=Math.max(280,window.innerHeight*.42);
    var overflowTravel=Math.max(0,conversationHeight-visibleConversation)/620;
    var pageY=window.scrollY||document.documentElement.scrollTop||0;
    var scrollTravel=pageY/Math.max(520,window.innerHeight*.72);
    var messageTravel=messageCount*.28;

    /*
     * Padiem Glass mirrors the sibling's scroll-driven portrait reveal, but
     * conversation travel is the timeline here: as messages stack and the chat
     * rises, the mask opens, closes, and opens again in a continuous ping-pong
     * loop. No autonomous timer is used; the conversation itself drives it.
     */
    var travel=messageTravel+overflowTravel+scrollTravel;
    var reveal=smoothstep(pingPong(travel));
    var maskStart=24*(1-reveal);
    var maskFull=58-(46*reveal);

    root.style.setProperty("--glass-reveal",reveal.toFixed(3));
    root.style.setProperty("--glass-mask-start",maskStart.toFixed(1)+"%");
    root.style.setProperty("--glass-mask-full",maskFull.toFixed(1)+"%");
    root.style.setProperty("--glass-art-x",(-5*reveal).toFixed(1)+"px");
    root.style.setProperty("--glass-art-y",(-18*reveal).toFixed(1)+"px");
    root.style.setProperty("--glass-art-scale",(1+reveal*.012).toFixed(3));
  }

  function queueGlassMotion(){
    if(glassMotionFrame) return;
    glassMotionFrame=window.requestAnimationFrame(updateGlassMotion);
  }

  function updateGlassPointer(event){
    if(getCurrent()!=="padiem-glass"||prefersReducedMotion()) return;
    var root=document.documentElement;
    var nx=Math.max(-1,Math.min(1,(event.clientX/window.innerWidth-.5)*2));
    var ny=Math.max(-1,Math.min(1,(event.clientY/window.innerHeight-.5)*2));
    root.style.setProperty("--glass-pointer-x",(nx*8).toFixed(1)+"px");
    root.style.setProperty("--glass-pointer-y",(ny*5).toFixed(1)+"px");
  }

  function resetGlassPointer(){
    var root=document.documentElement;
    root.style.setProperty("--glass-pointer-x","0px");
    root.style.setProperty("--glass-pointer-y","0px");
  }

  function observeGlassConversation(){
    var list=document.getElementById("messageList");
    if(!list || !window.MutationObserver || glassObserver) return;
    glassObserver=new MutationObserver(queueGlassMotion);
    glassObserver.observe(list,{childList:true,subtree:true,characterData:true});
  }

  function init(){
    ensureGlassOption();
    ensureGlassVariantControl();
    var cur=document.documentElement.getAttribute("data-theme");
    if(cur==="padiem-glass"){
      ensureGlassStyles();
      applyGlassVariant(getUrlGlassVariant()||getGlassVariant(),false);
    }
    if(!isValid(cur)){
      var url=getUrlTheme();
      var initial=url||getSystemFallback();
      applyTheme(initial,false);
    } else {
      syncPicker(cur);
      if(document.body) document.body.setAttribute("data-theme",cur);
      if(document.body) document.body.setAttribute("data-glass-variant",getGlassVariant());
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
      if(url==="padiem-glass") applyGlassVariant(getUrlGlassVariant()||"female",false);
    });
    window.addEventListener("scroll",queueGlassMotion,{passive:true});
    window.addEventListener("resize",queueGlassMotion);
    window.addEventListener("pointermove",updateGlassPointer,{passive:true});
    document.addEventListener("mouseleave",resetGlassPointer);
    observeGlassConversation();
    queueGlassMotion();
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

  window.__padiemTheme={
    VALID:VALID,
    GLASS_VARIANTS:GLASS_VARIANTS,
    getUrlTheme:getUrlTheme,
    getCurrent:getCurrent,
    applyTheme:applyTheme,
    getGlassVariant:getGlassVariant,
    applyGlassVariant:applyGlassVariant
  };
  if(document.readyState==="loading"){document.addEventListener("DOMContentLoaded",init);} else {init();}
})();
