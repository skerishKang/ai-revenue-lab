(function(){
  "use strict";
  const VALID=["light","dark","cinematic","padiem-home","padiem-glass"];
  const GLASS_VARIANTS=["female","male"];
  const GLASS_MASK_MODES=["auto","on","off"];
  const GLASS_SPEED_MIN=20, GLASS_SPEED_MAX=300, GLASS_SPEED_DEFAULT=100;
  const THEME_COLORS={light:"#f8f8fb",dark:"#131417",cinematic:"#04070d","padiem-home":"#e6e9ee","padiem-glass":"#aeb6bf"};
  const COLOR_SCHEMES={light:"light",dark:"dark",cinematic:"dark","padiem-home":"light","padiem-glass":"light"};
  var glassMotionFrame=0;
  var glassObserver=null;
  var glassStateObserver=null;
  var glassPointerReveal=0;
  var glassAnswerLastActivity=0;

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
    ensureStylesheet("./padiem-glass-reading.css","data-padiem-glass-reading");
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

  /* Shell mask + motion speed are URL-authoritative like the glass variant:
   * ?mask=auto|on|off and ?speed=20..300 (percent). No browser storage. */
  function isGlassMaskMode(v){return GLASS_MASK_MODES.indexOf(v)!==-1;}

  function getUrlGlassMask(){
    try{
      var v=new URLSearchParams(location.search).get("mask");
      if(isGlassMaskMode(v)) return v;
    }catch(e){}
    return null;
  }

  function getGlassMaskMode(){
    var cur=document.documentElement.getAttribute("data-glass-mask");
    if(isGlassMaskMode(cur)) return cur;
    return getUrlGlassMask()||"auto";
  }

  function clampGlassSpeed(v){
    v=Math.round(Number(v));
    if(!(v>=GLASS_SPEED_MIN&&v<=GLASS_SPEED_MAX)) return GLASS_SPEED_DEFAULT;
    return v;
  }

  function getUrlGlassSpeed(){
    try{
      var v=parseInt(new URLSearchParams(location.search).get("speed"),10);
      if(v>=GLASS_SPEED_MIN&&v<=GLASS_SPEED_MAX) return v;
    }catch(e){}
    return null;
  }

  function getGlassSpeed(){
    var cur=parseInt(document.documentElement.getAttribute("data-glass-speed")||"",10);
    if(cur>=GLASS_SPEED_MIN&&cur<=GLASS_SPEED_MAX) return cur;
    return getUrlGlassSpeed()||GLASS_SPEED_DEFAULT;
  }

  function setGlassUrlParam(key,value){
    try{
      var url=new URL(location.href);
      if(value===null) url.searchParams.delete(key);
      else url.searchParams.set(key,value);
      history.replaceState(null,"",url.toString());
    }catch(e){}
  }

  function applyGlassMask(mode,persist){
    if(!isGlassMaskMode(mode)) return;
    document.documentElement.setAttribute("data-glass-mask",mode);
    if(document.body) document.body.setAttribute("data-glass-mask",mode);
    if(persist) setGlassUrlParam("mask",mode==="auto"?null:mode);
    syncGlassShellControl();
  }

  function applyGlassSpeed(pct,persist){
    pct=clampGlassSpeed(pct);
    document.documentElement.setAttribute("data-glass-speed",String(pct));
    if(document.body) document.body.setAttribute("data-glass-speed",String(pct));
    if(persist) setGlassUrlParam("speed",pct===GLASS_SPEED_DEFAULT?null:String(pct));
    syncGlassShellControl();
  }

  function glassMode(){
    var shell=document.querySelector(".app-shell");
    return shell && shell.dataset.state==="chat" ? "reading" : "home";
  }

  function syncGlassMode(){
    var root=document.documentElement;
    if(getCurrent()!=="padiem-glass"){
      root.removeAttribute("data-glass-mode");
      return "home";
    }
    var mode=glassMode();
    root.setAttribute("data-glass-mode",mode);
    return mode;
  }

  function syncGlassVariant(variant,theme){
    var control=document.querySelector(".glass-variant-control");
    if(control) control.hidden=theme!=="padiem-glass";
    syncGlassShellControl();
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
    ensureGlassShellControl(control);
  }

  /* Shell mask mode (Auto/On/Off) + motion speed bar, next to the variant picker. */
  function ensureGlassShellControl(anchor){
    if(!anchor || !anchor.parentNode || document.querySelector(".glass-shell-control")) return;
    var control=document.createElement("div");
    control.className="glass-shell-control";
    control.hidden=true;

    var label=document.createElement("p");
    label.className="glass-variant-label";
    label.textContent="Shell mask";
    control.appendChild(label);

    var group=document.createElement("div");
    group.className="glass-variant-picker glass-mask-picker";
    group.setAttribute("role","group");
    group.setAttribute("aria-label","Shell mask mode");

    [["auto","Auto"],["on","On"],["off","Off"]].forEach(function(item){
      var button=document.createElement("button");
      button.type="button";
      button.className="glass-variant-option";
      button.setAttribute("data-glass-mask-value",item[0]);
      button.setAttribute("aria-pressed","false");
      button.textContent=item[1];
      group.appendChild(button);
    });
    control.appendChild(group);

    var speedRow=document.createElement("div");
    speedRow.className="glass-speed-row";
    var speedLabel=document.createElement("label");
    speedLabel.className="glass-speed-label";
    speedLabel.setAttribute("for","glassSpeedRange");
    speedLabel.textContent="Motion speed";
    var range=document.createElement("input");
    range.type="range";
    range.id="glassSpeedRange";
    range.className="glass-speed-range";
    range.min=String(GLASS_SPEED_MIN);
    range.max=String(GLASS_SPEED_MAX);
    range.step="10";
    var val=document.createElement("span");
    val.className="glass-speed-value";
    speedRow.appendChild(speedLabel);
    speedRow.appendChild(range);
    speedRow.appendChild(val);
    control.appendChild(speedRow);

    anchor.parentNode.insertBefore(control,anchor.nextSibling);
    control.addEventListener("click",function(e){
      var btn=e.target.closest("[data-glass-mask-value]");
      if(!btn) return;
      applyGlassMask(btn.getAttribute("data-glass-mask-value"),true);
    });
    range.addEventListener("input",function(){
      applyGlassSpeed(parseInt(range.value,10),true);
    });
    syncGlassShellControl();
  }

  function syncGlassShellControl(){
    var control=document.querySelector(".glass-shell-control");
    if(!control) return;
    control.hidden=getCurrent()!=="padiem-glass";
    var mode=getGlassMaskMode();
    control.querySelectorAll("[data-glass-mask-value]").forEach(function(btn){
      var active=btn.getAttribute("data-glass-mask-value")===mode;
      btn.setAttribute("aria-pressed",active?"true":"false");
      if(active) btn.setAttribute("aria-current","true"); else btn.removeAttribute("aria-current");
    });
    var range=control.querySelector(".glass-speed-range");
    var val=control.querySelector(".glass-speed-value");
    var pct=getGlassSpeed();
    if(range && range.value!==String(pct)) range.value=String(pct);
    if(val) val.textContent=(pct/100).toFixed(1)+"\u00d7";
  }

  function getSystemFallback(){
    return "padiem-glass";
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
    syncGlassMode();
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

  function glassHoverCapable(){
    try{return Boolean(window.matchMedia&&window.matchMedia("(hover: hover) and (pointer: fine)").matches);}catch(e){return true;}
  }

  function currentGlassTime(){
    try{return window.performance&&window.performance.now?window.performance.now():Date.now();}catch(e){return Date.now();}
  }

  function noteGlassAnswerActivity(){
    if(getCurrent()!=="padiem-glass"||prefersReducedMotion()) return;
    glassAnswerLastActivity=currentGlassTime();
    queueGlassMotion();
  }

  function glassAnswerReveal(now){
    if(!glassAnswerLastActivity) return 0;
    var age=Math.max(0,now-glassAnswerLastActivity);
    var envelope=age<=260?1:Math.max(0,1-(age-260)/1500);
    if(envelope<=0){
      glassAnswerLastActivity=0;
      return 0;
    }
    /* A slow ping-pong keeps streaming answers cinematic without flashing. */
    var breathing=.58+.42*smoothstep(pingPong(now/1500));
    return envelope*breathing;
  }

  function updateGlassMotion(){
    glassMotionFrame=0;
    if(getCurrent()!=="padiem-glass") return;
    var root=document.documentElement;
    var mode=syncGlassMode();
    if(prefersReducedMotion()){
      root.style.setProperty("--glass-art-x","0px");
      root.style.setProperty("--glass-art-y","0px");
      root.style.setProperty("--glass-art-scale","1");
      root.style.setProperty("--glass-mask-start","6%");
      root.style.setProperty("--glass-mask-full","24%");
      root.style.setProperty("--glass-reveal","0.8");
      root.style.setProperty("--glass-pointer-reveal","0");
      root.style.setProperty("--glass-answer-reveal","0");
      root.style.setProperty("--glass-reading-art-opacity","0.28");
      glassAnswerLastActivity=0;
      resetGlassPointer();
      return;
    }

    var now=currentGlassTime();
    var pointerReveal=glassHoverCapable()?glassPointerReveal:0;
    var answerReveal=mode==="reading"?glassAnswerReveal(now):0;
    var baseReveal=0;

    if(mode!=="reading"){
      var list=document.getElementById("messageList");
      var messageCount=list?list.children.length:0;
      var conversationHeight=list?list.scrollHeight:0;
      var visibleConversation=Math.max(280,window.innerHeight*.42);
      var overflowTravel=Math.max(0,conversationHeight-visibleConversation)/620;
      var pageY=window.scrollY||document.documentElement.scrollTop||0;
      var scrollTravel=pageY/Math.max(520,window.innerHeight*.72);
      var messageTravel=messageCount*.28;
      var travel=messageTravel+overflowTravel+scrollTravel;
      baseReveal=smoothstep(pingPong(travel));
    }

    /*
     * Three bounded drivers share one reveal envelope:
     * - existing home scroll/message travel,
     * - portrait-zone pointer proximity,
     * - live assistant-answer activity.
     * Union composition lets pointer + answer strengthen each other without
     * exceeding 1 or fighting over the same CSS variables.
     */
    var reveal=1
      -(1-baseReveal)
      *(1-pointerReveal*.94)
      *(1-answerReveal*.90);
    reveal=Math.max(0,Math.min(1,reveal));

    var variant=getGlassVariant();
    var reading=mode==="reading";
    /* The art is right-aligned, so these ranges are intentionally large enough
     * to move the visible face/visor zone rather than only the empty left fade. */
    var restMaskStart=reading?(variant==="male"?30:34):(variant==="male"?14:18);
    var restMaskFull=reading?(variant==="male"?58:62):(variant==="male"?42:46);
    var openMaskStart=reading?(variant==="male"?4:5):0;
    var openMaskFull=reading?(variant==="male"?20:22):(variant==="male"?8:10);
    var maskStart=restMaskStart-((restMaskStart-openMaskStart)*reveal);
    var maskFull=restMaskFull-((restMaskFull-openMaskFull)*reveal);
    var travelY=reading?-14:-24;
    var scaleGain=reading?.012:.018;

    root.style.setProperty("--glass-reveal",reveal.toFixed(3));
    /* Shell layer drivers (read by padiem-glass-shell.js). */
    root.style.setProperty("--glass-pointer-reveal",pointerReveal.toFixed(3));
    root.style.setProperty("--glass-answer-reveal",answerReveal.toFixed(3));
    root.style.setProperty("--glass-mask-start",maskStart.toFixed(1)+"%");
    root.style.setProperty("--glass-mask-full",maskFull.toFixed(1)+"%");
    root.style.setProperty("--glass-art-x",(-9*reveal).toFixed(1)+"px");
    root.style.setProperty("--glass-art-y",(travelY*reveal).toFixed(1)+"px");
    root.style.setProperty("--glass-art-scale",(1+reveal*scaleGain).toFixed(3));
    root.style.setProperty("--glass-reading-art-opacity",(0.28+reveal*(variant==="male"?.22:.20)).toFixed(3));

    if(answerReveal>0) queueGlassMotion();
  }

  function queueGlassMotion(){
    if(glassMotionFrame) return;
    glassMotionFrame=window.requestAnimationFrame(updateGlassMotion);
  }

  function updateGlassPointer(event){
    if(getCurrent()!=="padiem-glass"||prefersReducedMotion()) return;
    if(!glassHoverCapable()){
      resetGlassPointer();
      return;
    }
    var root=document.documentElement;
    var field=document.querySelector(".glass-shell-field");
    var rect=field&&field.getBoundingClientRect?field.getBoundingClientRect():null;
    var portraitLeft=rect&&rect.width>0?rect.left:window.innerWidth-Math.min(window.innerWidth*.48,680);
    var portraitTop=rect&&rect.height>0?rect.top:68;
    var portraitBottom=rect&&rect.height>0?rect.bottom:window.innerHeight;
    var verticalActive=event.clientY>=portraitTop-36&&event.clientY<=portraitBottom+36;
    var hoverRamp=rect&&rect.width>0
      ?Math.max(120,Math.min(220,rect.width*.45))
      :180;
    /* Reverse shell starts only after the pointer enters the live portrait
     * field. Composer/send interactions to the left must not peel the face. */
    var proximity=verticalActive
      ?Math.max(0,Math.min(1,(event.clientX-portraitLeft)/hoverRamp))
      :0;
    glassPointerReveal=smoothstep(proximity);

    var basisX=rect&&rect.width>0?rect.left+rect.width/2:window.innerWidth/2;
    var basisY=rect&&rect.height>0?rect.top+rect.height/2:window.innerHeight/2;
    var spanX=rect&&rect.width>0?Math.max(1,rect.width/2):Math.max(1,window.innerWidth/2);
    var spanY=rect&&rect.height>0?Math.max(1,rect.height/2):Math.max(1,window.innerHeight/2);
    var nx=Math.max(-1,Math.min(1,(event.clientX-basisX)/spanX));
    var ny=Math.max(-1,Math.min(1,(event.clientY-basisY)/spanY));
    root.style.setProperty("--glass-pointer-x",(nx*8*glassPointerReveal).toFixed(1)+"px");
    root.style.setProperty("--glass-pointer-y",(ny*5*glassPointerReveal).toFixed(1)+"px");
    queueGlassMotion();
  }

  function resetGlassPointer(){
    var root=document.documentElement;
    glassPointerReveal=0;
    root.style.setProperty("--glass-pointer-x","0px");
    root.style.setProperty("--glass-pointer-y","0px");
  }

  function mutationTouchesAssistant(mutation){
    var target=mutation.target;
    if(target&&target.nodeType===3) target=target.parentElement;
    if(target&&target.closest&&target.closest(".assistant-message")) return true;
    var added=mutation.addedNodes||[];
    for(var i=0;i<added.length;i+=1){
      var node=added[i];
      if(!node||node.nodeType!==1) continue;
      if((node.matches&&node.matches(".assistant-message"))
        ||(node.closest&&node.closest(".assistant-message"))
        ||(node.querySelector&&node.querySelector(".assistant-message"))) return true;
    }
    return false;
  }

  function observeGlassConversation(){
    var list=document.getElementById("messageList");
    if(!list || !window.MutationObserver || glassObserver) return;
    glassObserver=new MutationObserver(function(mutations){
      if(mutations.some(mutationTouchesAssistant)) noteGlassAnswerActivity();
      else queueGlassMotion();
    });
    glassObserver.observe(list,{childList:true,subtree:true,characterData:true});
  }

  function observeGlassState(){
    var shell=document.querySelector(".app-shell");
    if(!shell || !window.MutationObserver || glassStateObserver) return;
    glassStateObserver=new MutationObserver(function(mutations){
      var changed=mutations.some(function(mutation){
        return mutation.type==="attributes" && mutation.attributeName==="data-state";
      });
      if(!changed) return;
      syncGlassMode();
      queueGlassMotion();
    });
    glassStateObserver.observe(shell,{attributes:true,attributeFilter:["data-state"]});
  }

  function init(){
    ensureGlassOption();
    ensureGlassVariantControl();
    var cur=document.documentElement.getAttribute("data-theme");
    if(cur==="padiem-glass"){
      ensureGlassStyles();
      applyGlassVariant(getUrlGlassVariant()||getGlassVariant(),false);
      applyGlassMask(getUrlGlassMask()||getGlassMaskMode(),false);
      applyGlassSpeed(getUrlGlassSpeed()||getGlassSpeed(),false);
    }
    if(!isValid(cur)){
      var url=getUrlTheme();
      var initial=url||getSystemFallback();
      applyTheme(initial,false);
    } else {
      syncPicker(cur);
      if(document.body) document.body.setAttribute("data-theme",cur);
      if(document.body) document.body.setAttribute("data-glass-variant",getGlassVariant());
      syncGlassMode();
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
      applyGlassMask(getUrlGlassMask()||"auto",false);
      applyGlassSpeed(getUrlGlassSpeed()||GLASS_SPEED_DEFAULT,false);
    });
    window.addEventListener("scroll",queueGlassMotion,{passive:true});
    window.addEventListener("resize",queueGlassMotion);
    window.addEventListener("pointermove",updateGlassPointer,{passive:true});
    document.addEventListener("mouseleave",function(){
      resetGlassPointer();
      queueGlassMotion();
    });
    observeGlassConversation();
    observeGlassState();
    queueGlassMotion();
    try{
      var reducedMotion=window.matchMedia("(prefers-reduced-motion: reduce)");
      var reducedMotionHandler=function(){
        resetGlassPointer();
        queueGlassMotion();
      };
      if(reducedMotion.addEventListener) reducedMotion.addEventListener("change",reducedMotionHandler);
      else if(reducedMotion.addListener) reducedMotion.addListener(reducedMotionHandler);
    }catch(e){}
    try{
      var mql=window.matchMedia("(prefers-color-scheme: dark)");
      var handler=function(){
        if(getUrlTheme()) return;
        return;
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
    applyGlassVariant:applyGlassVariant,
    getGlassMaskMode:getGlassMaskMode,
    applyGlassMask:applyGlassMask,
    getGlassSpeed:getGlassSpeed,
    applyGlassSpeed:applyGlassSpeed,
    /* Live driver readout for the shell layer: computed synchronously so the
     * shell loop stays correct even when this module's own rAF is starved
     * (occluded/headless/low-power rendering). */
    glassMotionDrivers:function(){
      var reading=syncGlassMode()==="reading";
      return {
        pointer:prefersReducedMotion()?0:glassPointerReveal,
        answer:reading?glassAnswerReveal(currentGlassTime()):0
      };
    }
  };
  if(document.readyState==="loading"){document.addEventListener("DOMContentLoaded",init);} else {init();}
})();
