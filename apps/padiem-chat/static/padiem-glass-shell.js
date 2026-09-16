/* Padiem Glass shell layer.
 *
 * Port of the Drive 원본 "Identity Fragment Loader V2" (버전2/최종본.html)
 * mechanics onto the chat portrait: 20 clip-path plate fragments of the shell
 * portrait (same adopted face + transplanted mask asset) scatter, assemble
 * over the CLEAN portrait, then dissolve into the completed shell portrait.
 *
 * Drivers come from theme.js CSS variables: --glass-pointer-reveal and
 * --glass-answer-reveal. Mode/speed come from data-glass-mask /
 * data-glass-speed attributes (URL-authoritative, set in theme-init/theme.js).
 * No browser storage, no synthetic overlay art.
 */
(function(){
  "use strict";

  var FRAG_COUNT=20, COLS=4, ROWS=5; /* source loader: 20 fragments; portrait grid 4x5 */
  var CLIP_SHAPES=[
    "polygon(8% 0,100% 7%,91% 100%,0 88%)",
    "polygon(0 11%,88% 0,100% 91%,13% 100%)",
    "polygon(13% 0,100% 16%,86% 100%,0 91%)",
    "polygon(0 4%,95% 0,100% 84%,8% 100%)",
    "polygon(6% 0,100% 11%,93% 92%,0 100%)"
  ];
  var ASSEMBLE_START=.02, ASSEMBLE_SPAN=.80;  /* source: ease(clamp((p-.08)/.78)) */
  var DISSOLVE_AT=.90, DISSOLVE_SPAN=.10;     /* source: fragments dissolve ~89% */
  var RATE_UP=.075, RATE_DOWN=.03;            /* source exponential approach */

  var field=null, portal=null, veinLayer=null;
  var frags=[];
  var progress=0, raf=0;
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
    var px=parseFloat(bpx), py=parseFloat(bpy);
    px=isNaN(px)?1:px/100; py=isNaN(py)?.52:py/100;
    imgL=(fieldW-imgW)*px;
    imgT=(fieldH-imgH)*py;

    var cellW=imgW/COLS, cellH=imgH/ROWS;
    var cx=imgL+imgW/2, cy=imgT+imgH/2;
    var url=shellUrl();
    lastVariant=variant();
    for(var i=0;i<FRAG_COUNT;i++){
      var f=frags[i], col=i%COLS, row=Math.floor(i/COLS);
      /* source: golden-angle scatter ring + per-plate size/rotation deltas */
      var angle=i*2.399, ring=Math.min(imgW,imgH)*(.42+(i%5)*.07);
      var sx=cx+Math.cos(angle)*ring, sy=cy+Math.sin(angle)*ring;
      var fx=imgL+col*cellW, fy=imgT+row*cellH;
      f.d={sx:sx,sy:sy,fx:fx,fy:fy,
           sw:cellW*(.5+(i%4)*.12), sh:cellH*(.44+((i+2)%4)*.12),
           fw:cellW+1, fh:cellH+1,
           sr:-68+(i*37)%136, fr:(i%3-1)*2.2};
      f.el.style.backgroundImage='url("'+url+'")';
      f.el.style.backgroundSize=imgW+"px "+imgH+"px";
      f.el.style.backgroundPosition=(-fx)+"px "+(-fy)+"px";
      f.el.style.clipPath=CLIP_SHAPES[i%CLIP_SHAPES.length];
    }
  }

  function target(){
    var mode=maskMode();
    if(mode==="on") return 1;
    if(mode==="off") return 0;
    var p=driver("--glass-pointer-reveal"), a=driver("--glass-answer-reveal");
    var t=Math.max(.62*p,.8*a);       /* pointer assembles, answer drives deeper */
    if(p>.45&&a>.45) t=1;             /* pointer + answer → full shell reveal */
    return t;
  }

  function render(p){
    var assemble=ease(clamp((p-ASSEMBLE_START)/ASSEMBLE_SPAN,0,1));
    var dissolve=clamp((p-DISSOLVE_AT)/DISSOLVE_SPAN,0,1);
    var parX=(mx-.5), parY=(my-.5);
    for(var i=0;i<FRAG_COUNT;i++){
      var f=frags[i]; if(!f.d) continue;
      var d=f.d, delay=(i%7)*.014;
      var local=ease(clamp((assemble-delay)/(1-delay),0,1));
      var x=d.sx+(d.fx-d.sx)*local+parX*(1-local)*(18+(i%5)*6);
      var y=d.sy+(d.fy-d.sy)*local+parY*(1-local)*(14+(i%4)*7);
      var w=d.sw+(d.fw-d.sw)*local, h=d.sh+(d.fh-d.sh)*local;
      var rot=d.sr+(d.fr-d.sr)*local, depth=(1-local)*(40+(i%4)*22);
      f.el.style.width=w+"px";
      f.el.style.height=h+"px";
      f.el.style.opacity=String(clamp(local*1.15-dissolve*1.3,0,1));
      f.el.style.transform="translate3d("+x+"px,"+y+"px,"+depth+"px) rotate("+rot+"deg) scale("+(0.72+local*.28)+")";
      f.el.style.filter="saturate("+(0.65+local*.45)+") blur("+((1-local)*1.4)+"px)";
    }
    root().style.setProperty("--glass-shell-progress",clamp(p,0,1).toFixed(3));
    root().style.setProperty("--glass-shell-dissolve",clamp(dissolve*1.15,0,1).toFixed(3));
    if(veinLayer&&veinLayer.parentNode){
      veinLayer.parentNode.style.opacity=String(clamp(.1+p*.6,0,.7)*(1-dissolve*.5));
    }
  }

  function tick(){
    raf=0;
    if(!isGlass()) return;
    if(!ensureLayer()){schedule();return;}
    var v=variant();
    if(v!==lastVariant) layout();
    var t=reducedMotion()?(maskMode()==="on"?1:0):target();
    if(reducedMotion()){
      progress=t;
    }else{
      var rate=(t>progress?RATE_UP:RATE_DOWN)*speedMul();
      progress+=(t-progress)*rate;
      if(Math.abs(t-progress)<.001) progress=t;
    }
    render(progress);
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
     * window.innerWidth-fieldW is not an exact origin. */
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
    if(document.fonts&&document.fonts.ready) document.fonts.ready.then(function(){layout();});
    layout();
    wake();
  }

  if(document.readyState==="loading"){
    document.addEventListener("DOMContentLoaded",init);
  }else{
    init();
  }
})();
