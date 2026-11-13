/* bookai #7574 — 항목 9: 절 번호 색을 지금 종이 바탕에 맞춰 정한다.
   기본 종이(#fffdf8)에서 #a99d90 은 2.6:1 이라 작은 절 번호를 읽기 어렵다.
   테마(밝게·세피아·어둡게)와 사용자 지정 종이 색까지 같은 규칙으로 계산해
   본문 바탕과 4.5:1 이상인 가장 가벼운 색을 고른다. 종이 배경만 읽고, 본문·AI
   지시문·스포일러 로직은 건드리지 않는다. */
(function(){
  'use strict';

  var LIGHT_INKS=['#8b7f70','#7a6d5e','#6b5f52','#4f453c','#2f2a24'];
  var DARK_INKS=['#bfb19c','#d0c2ac','#e9e1d2','#f5eee2'];

  function parseColor(value){
    if(!value)return null;
    var text=String(value).trim();
    var rgb=text.match(/^rgba?\(([^)]+)\)$/i);
    if(rgb){
      var parts=rgb[1].split(',').map(function(part){return parseFloat(part);});
      if(parts.length<3)return null;
      return {r:parts[0],g:parts[1],b:parts[2],a:parts.length>3?parts[3]:1};
    }
    var hex=text.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
    if(!hex)return null;
    var digits=hex[1];
    if(digits.length===3)digits=digits[0]+digits[0]+digits[1]+digits[1]+digits[2]+digits[2];
    return {
      r:parseInt(digits.slice(0,2),16),
      g:parseInt(digits.slice(2,4),16),
      b:parseInt(digits.slice(4,6),16),
      a:1
    };
  }

  function channel(value){
    var c=value/255;
    return c<=0.04045?c/12.92:Math.pow((c+0.055)/1.055,2.4);
  }

  function luminance(color){
    return 0.2126*channel(color.r)+0.7152*channel(color.g)+0.0722*channel(color.b);
  }

  function contrast(a,b){
    var first=luminance(a),second=luminance(b);
    var high=Math.max(first,second),low=Math.min(first,second);
    return (high+0.05)/(low+0.05);
  }

  function paperElement(){
    return document.getElementById('paper');
  }

  function paperBackground(){
    var paper=paperElement();
    if(!paper)return null;
    var painted=parseColor(getComputedStyle(paper).backgroundColor);
    if(painted&&painted.a>=0.5)return painted;
    var token=getComputedStyle(document.documentElement).getPropertyValue('--reader-paper');
    return parseColor(token);
  }

  function inkFor(background){
    var list=luminance(background)>0.34?LIGHT_INKS:DARK_INKS;
    var chosen=list[list.length-1];
    for(var i=0;i<list.length;i+=1){
      var candidate=parseColor(list[i]);
      if(candidate&&contrast(candidate,background)>=4.5){chosen=list[i];break;}
    }
    return chosen;
  }

  function apply(){
    var paper=paperElement();
    if(!paper)return;
    var background=paperBackground();
    if(!background)return;
    var ink=inkFor(background);
    if(paper.style.getPropertyValue('--sm-vn-ink')!==ink){
      paper.style.setProperty('--sm-vn-ink',ink);
    }
  }

  var queued=false;
  function queueApply(){
    if(queued)return;
    queued=true;
    var run=function(){queued=false;apply();};
    if(window.requestAnimationFrame)window.requestAnimationFrame(run);
    else setTimeout(run,16);
  }

  function observe(){
    apply();
    if(!window.MutationObserver)return;
    new MutationObserver(queueApply).observe(document.body,{attributes:true,attributeFilter:['class']});
    new MutationObserver(queueApply).observe(document.documentElement,{attributes:true,attributeFilter:['style']});
    var paper=paperElement();
    if(paper)new MutationObserver(queueApply).observe(paper,{attributes:true,attributeFilter:['style','class']});
    document.addEventListener('sm-reader-entry',queueApply);
  }

  function boot(){
    observe();
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});
  else boot();
  window.addEventListener('bookai-ready',queueApply,{once:true});
})();
