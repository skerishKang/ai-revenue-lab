/* Padiem Glass shell layer.
 *
 * Port of the Drive 원본 "Identity Fragment Loader V2" (버전2/최종본.html)
 * mechanics onto the chat portrait, adapted to the reviewed product contract:
 * 20 thin, pixel-registered shell ribbons fade in place over the CLEAN portrait.
 * There is no scatter ring, large mosaic tile, pointer scrub, or face duplication.
 *
 * Drivers come from theme.js CSS variables: --glass-pointer-reveal and
 * --glass-answer-reveal. Mode/speed come from data-glass-mask /
 * data-glass-speed attributes (URL-authoritative, set in theme-init/theme.js).
 * No browser storage, no synthetic overlay art.
 */
(function(){
  "use strict";

  var FRAG_COUNT=20, COLS=1, ROWS=20; /* 20 thin registered shell ribbons */
  var CLIP_SHAPES=[
    "polygon(0 10%,100% 0,100% 90%,0 100%)",
    "polygon(0 0,100% 9%,100% 100%,0 91%)",
    "polygon(0 7%,100% 2%,100% 93%,0 98%)",
    "polygon(0 2%,100% 8%,100% 98%,0 92%)",
    "polygon(0 6%,100% 0,100% 94%,0 100%)"
  ];
  var ASSEMBLE_START=.02, ASSEMBLE_SPAN=.80;  /* source: ease(clamp((p-.08)/.78)) */
  var DISSOLVE_AT=.90, DISSOLVE_SPAN=.10;     /* source: fragments dissolve ~89% */
  var RATE_UP=.0075, RATE_DOWN=.0065;        /* measured ~2–3 s cinematic peel/reassembly at 1× */

  var field=null, portal=null, veinLayer=null;
  var frags=[];
  var progress=1, raf=0, lastT=0;
  var mx=.5, my=.5;
  var imgL=0, imgT=0, imgW=0, imgH=0;
  var fieldW=0, fieldH=0, fieldTop=68;
  var lastVariant="";

  function root(){return document.documentElement;}

  function isGlass(){return root().getAttribute("data-theme")==="padiem-glass";}

  function reducedMotion(){
    try{return Boolean(window.matchMedia&&window.matchMedia("(prefers-reduced-motion: reduce)").matches);}catch(e){return false;}
  }

  function maskMode(){
    var m=root().getAttribute("data-glass-mask");
    return m==="on"||m==="off"?m:"auto";
  }

  function speedMul(){
    var v=parseInt(root().getAttribute("data-glass-speed")||"100",10);
    if(!(v>=20&&v<=300)) v=100;
    return v/100;
  }

  function variant(){
    var v=root().getAttribute("data-glass-variant");
    return v==="male"?"male":"female";
  }

  function shellUrl(){
    return "./assets/padiem-glass-"+variant()+"-shell.jpg";
  }

  function clamp(v,a,b){return Math.max(a,Math.min(b,v));}

  function ease(t){return t<.5?4*t*t*t:1-Math.pow(-2*t+2,3)/2;}

  function driver(name){
    /* Prefer the live synchronous driver readout from theme.js exports;
     * CSS variables are the deferred (rAF-gated) fallback. */
    var api=window.__padiemTheme;
    if(api&&api.glassMotionDrivers){
      var d=api.glassMotionDrivers();
      return clamp(name==="--glass-pointer-reveal"?d.pointer:d.answer,0,1);
    }
    var v=parseFloat(getComputedStyle(root()).getPropertyValue(name));
    return isNaN(v)?0:clamp(v,0,1);
  }

  function ensureLayer(){
    var panel=document.querySelector(".main-panel");
    if(!panel) return false;
    if(!portal){
      portal=document.createElement("div");
      portal.className="glass-shell-portrait";
      portal.setAttribute("aria-hidden","true");
      panel.appendChild(portal);
    }
    if(!field){
      field=document.createElement("div");
      field.className="glass-shell-field";
      field.setAttribute("aria-hidden","true");
      var ns="http://www.w3.org/2000/svg";
      var vein=document.createElementNS(ns,"svg");
      vein.setAttribute("class","glass-shell-vein");
      vein.setAttribute("viewBox","0 0 1000 1000");
      vein.setAttribute("preserveAspectRatio","none");
      vein.setAttribute("aria-hidden","true");
      var defs=document.createElementNS(ns,"defs");
      var grad=document.createElementNS(ns,"linearGradient");
      grad.setAttribute("id","glassShellVeinGradient");
      grad.setAttribute("x1","0");grad.setAttribute("y1","0");
      grad.setAttribute("x2","1");grad.setAttribute("y2","1");
      [["0","#9db8d1",".15"],[".45","#ffc2e4",".7"],["1","#9d83d1",".2"]].forEach(function(s){
        var stop=document.createElementNS(ns,"stop");
        stop.setAttribute("offset",s[0]);
        stop.setAttribute("stop-color",s[1]);
        stop.setAttribute("stop-opacity",s[2]);
        grad.appendChild(stop);
      });
      defs.appendChild(grad);
      vein.appendChild(defs);
      veinLayer=document.createElementNS(ns,"g");
      vein.appendChild(veinLayer);
      field.appendChild(vein);
      /* source drawVeins: 12 derived connective curves */
      for(var i=0;i<12;i++){
        var x1=70+(i*83)%880, y1=120+(i*137)%770,
            x2=80+((i+4)*121)%850, y2=130+((i+7)*91)%760,
            cx=(x1+x2)*.5+Math.sin(i*2.2)*90, cy=(y1+y2)*.5+Math.cos(i*1.7)*75;
        var path=document.createElementNS(ns,"path");
        path.setAttribute("d","M "+x1+" "+y1+" Q "+cx+" "+cy+" "+x2+" "+y2);
        path.setAttribute("stroke","url(#glassShellVeinGradient)");
        veinLayer.appendChild(path);
      }
      for(var j=0;j<FRAG_COUNT;j++){
        var el=document.createElement("div");
        el.className="glass-shell-frag";
        field.appendChild(el);
        frags.push({el:el,d:null});
      }
      panel.appendChild(field);
    }
    return true;
  }

  /* Mirror .main-panel::before computed geometry so the shell image box
   * lands exactly on the live portrait (all breakpoints included). */
  function layout(){
    if(!field||!portal) return;
    var panel=document.querySelector(".main-panel");
    if(!panel) return;
    var cs;
    try{cs=getComputedStyle(panel,"::before");}catch(e){return;}
    if(!cs) return;
    ["top","right","bottom","width"].forEach(function(prop){
      field.style[prop]=cs[prop];
      portal.style[prop]=cs[prop];
    });
    portal.style.backgroundSize=cs.backgroundSize;
    portal.style.backgroundPosition=cs.backgroundPosition;

    fieldW=parseFloat(cs.width);
    fieldH=parseFloat(cs.height);
    fieldTop=parseFloat(cs.top)||68;
    if(!(fieldW>0&&fieldH>0)) return;
    var m=/auto\s+([0-9.]+)px/.exec(cs.backgroundSize||"");
    imgH=m?parseFloat(m[1]):fieldH;
    imgW=imgH*.75; /* 900x1200 asset aspect */
    var bpx=cs.backgroundPositionX||"", bpy=cs.backgroundPositionY||"";
    if(!bpx){
      var parts=(cs.backgroundPosition||"100% 52%").split(/\s+/);
      bpx=parts[0]; bpy=parts[1]||"52%";
    }
    function axisOffset(value, freeSpace, fallbackFraction){
      var raw=String(value||"").trim().toLowerCase();
      if(raw==="left"||raw==="top") return 0;
      if(raw==="center") return freeSpace*.5;
      if(raw==="right"||raw==="bottom") return freeSpace;
      if(raw.endsWith("%")){
        var pct=parseFloat(raw);
        return isNaN(pct)?freeSpace*fallbackFraction:freeSpace*(pct/100);
      }
      if(raw.endsWith("px")){
        var px=parseFloat(raw);
        return isNaN(px)?freeSpace*fallbackFraction:px;
      }
      var n=parseFloat(raw);
      return isNaN(n)?freeSpace*fallbackFraction:freeSpace*(n/100);
    }
    imgL=axisOffset(bpx,fieldW-imgW,1);
    imgT=axisOffset(bpy,fieldH-imgH,.52);

    var cellW=imgW/COLS, cellH=imgH/ROWS;
    var url=shellUrl();
    lastVariant=variant();
    for(var i=0;i<FRAG_COUNT;i++){
      var f=frags[i], col=i%COLS, row=Math.floor(i/COLS);
      /*
       * Position is field-relative, but the fragment's background crop is
       * image-local. Including imgL/imgT in the crop offset double-shifts the
       * source pixels and creates displaced duplicate eyes/face pieces.
       */
      var cropX=col*cellW, cropY=row*cellH;
      var fx=imgL+cropX, fy=imgT+cropY;
      f.d={fx:fx,fy:fy,fw:cellW+1,fh:cellH+1,cropX:cropX,cropY:cropY};
      f.el.style.backgroundImage='url("'+url+'")';
      f.el.style.backgroundSize=imgW+"px "+imgH+"px";
      f.el.style.backgroundPosition=(-cropX)+"px "+(-cropY)+"px";
      f.el.style.clipPath=CLIP_SHAPES[i%CLIP_SHAPES.length];
    }
  }

  function target(){
    var mode=maskMode();
    if(mode==="on") return 1;
    if(mode==="off") return 0;
    /* Auto is intentionally reverse: the completed shell is the resting state
     * and pointer proximity peels it away to reveal the clean portrait. */
    var p=driver("--glass-pointer-reveal");
    return 1-clamp(p,0,1);
  }

  function render(p,peeling){
    /* The clean portrait is always underneath. The shell transition is a
     * time-driven dissolve of ALIGNED portrait tiles — never a pointer-scrubbed
     * scatter ring. This prevents duplicated/displaced eyes and face chunks. */
    var phase=peeling?1-p:p; /* 0→1 for either direction */
    var portal=ease(clamp(p,0,1));

    for(var i=0;i<FRAG_COUNT;i++){
      var f=frags[i]; if(!f.d) continue;
      var d=f.d;
      var order=((i*7)%FRAG_COUNT)/(FRAG_COUNT-1);
      var delay=order*.16;
      var appear=ease(clamp((phase-delay)/.20,0,1));
      var disappear=1-ease(clamp((phase-(.50+delay))/.28,0,1));
      var fragOpacity=.24*appear*disappear;

      /* Keep every tile exactly registered over the same portrait pixels.
       * The cinematic effect comes from staggered opacity only: no scatter,
       * parallax, rotation, or drift that can duplicate facial features. */
      var x=d.fx, y=d.fy;

      f.el.style.width=d.fw+"px";
      f.el.style.height=d.fh+"px";
      f.el.style.opacity=String(clamp(fragOpacity,0,.42));
      f.el.style.transform="translate3d("+x+"px,"+y+"px,0) rotate(0deg) scale(1)";
      f.el.style.filter="saturate(1) blur(0px)";
    }

    root().style.setProperty("--glass-shell-progress",clamp(p,0,1).toFixed(3));
    root().style.setProperty("--glass-shell-dissolve",clamp(portal,0,1).toFixed(3));
    if(veinLayer&&veinLayer.parentNode){
      var transitionBand=1-Math.abs(p-.5)*2;
      veinLayer.parentNode.style.opacity=String(clamp(transitionBand*.16,0,.16));
    }
  }

  function tick(now){
    raf=0;
    step(now);
  }

  function step(now){
    if(!isGlass()) return;
    if(!ensureLayer()){schedule();return;}
    var v=variant();
    if(v!==lastVariant) layout();
    var t=reducedMotion()?(maskMode()==="off"?0:1):target();
    var peeling=t<progress;
    if(reducedMotion()){
      progress=t;
    }else{
      /* frame-rate independent exponential approach: the source rates are
       * normalized to a 60fps step so 120Hz/headless/low-power renders the
       * same wall-clock speed. */
      var dt=lastT?Math.max(0,Math.min(100,now-lastT)):16.7;
      lastT=now;
      var base=(t>progress?RATE_UP:RATE_DOWN)*speedMul();
      var rate=1-Math.pow(1-Math.min(.95,base),dt/16.7);
      progress+=(t-progress)*rate;
      if(Math.abs(t-progress)<.001) progress=t;
    }
    render(progress,peeling);
    /* keep animating while transitioning; drivers re-arm via wake() */
    if(progress!==t) schedule();
  }

  function schedule(){
    if(!raf) raf=requestAnimationFrame(tick);
  }

  function wake(){
    if(isGlass()) schedule();
  }

  function onPointer(e){
    /* Resolve against the actual live field rect. Breakpoints can move the
     * portrait with positive/negative right offsets and transforms, so
     * viewport-width subtraction is not an exact origin. */
    var rect=field&&field.getBoundingClientRect?field.getBoundingClientRect():null;
    if(rect&&fieldW>0&&fieldH>0&&imgW>0&&imgH>0){
      var scaleX=rect.width/fieldW, scaleY=rect.height/fieldH;
      if(!(scaleX>0)) scaleX=1;
      if(!(scaleY>0)) scaleY=1;
      var imageLeft=rect.left+imgL*scaleX;
      var imageTop=rect.top+imgT*scaleY;
      mx=(e.clientX-imageLeft)/(imgW*scaleX);
      my=(e.clientY-imageTop)/(imgH*scaleY);
    }
    wake();
  }

  function init(){
    /* Answer activity: same conversation mutations theme.js already observes. */
    var list=document.getElementById("messageList");
    if(list&&window.MutationObserver){
      new MutationObserver(function(){wake();})
        .observe(list,{childList:true,subtree:true,characterData:true});
    }
    /* data-* authority changes (theme/variant/mask/speed) re-arm the loop;
     * variant change also re-cuts the jigsaw. */
    if(window.MutationObserver){
      new MutationObserver(function(){
        if(variant()!==lastVariant) layout();
        wake();
      }).observe(root(),{attributes:true,attributeFilter:["data-theme","data-glass-variant","data-glass-mask","data-glass-speed"]});
    }
    window.addEventListener("pointermove",onPointer,{passive:true});
    window.addEventListener("resize",function(){layout();wake();},{passive:true});
    document.addEventListener("visibilitychange",function(){if(!document.hidden)wake();});
    /* Convergence watchdog: timers still fire under rAF starvation, so a
     * stalled loop steps manually and always finishes its transition. */
    setInterval(function(){
      if(!isGlass()) return;
      if(!field&&ensureLayer()) layout();
      var t=reducedMotion()?(maskMode()==="off"?0:1):target();
      if(progress===t) return;
      var now=performance.now();
      if(now-lastT<300) return; /* live rAF stream already stepping */
      if(raf){cancelAnimationFrame(raf);raf=0;}
      step(now);
    },150);
    /* Read-only QA/state handle (progress, target, mode). */
    window.__padiemGlassShell={
      progress:function(){return progress;},
      target:function(){return reducedMotion()?(maskMode()==="off"?0:1):target();},
      mode:function(){return maskMode();},
      imageRect:function(){
        var rect=field&&field.getBoundingClientRect?field.getBoundingClientRect():null;
        if(!rect||!(fieldW>0&&fieldH>0&&imgW>0&&imgH>0)) return null;
        var scaleX=rect.width/fieldW, scaleY=rect.height/fieldH;
        if(!(scaleX>0)) scaleX=1;
        if(!(scaleY>0)) scaleY=1;
        var left=rect.left+imgL*scaleX;
        var top=rect.top+imgT*scaleY;
        var width=imgW*scaleX;
        var height=imgH*scaleY;
        return {left:left,top:top,right:left+width,bottom:top+height,width:width,height:height};
      }
    };
    if(document.fonts&&document.fonts.ready) document.fonts.ready.then(function(){layout();});
    progress=maskMode()==="off"?0:1;
    if(isGlass()&&ensureLayer()){
      layout(); /* fragments exist even if rAF never fires */
      render(progress,false);
    }
    layout();
    wake();
  }

  if(document.readyState==="loading"){
    document.addEventListener("DOMContentLoaded",init);
  }else{
    init();
  }
})();
