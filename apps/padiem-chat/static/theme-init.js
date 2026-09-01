(function(){
  try{
    var T=["light","dark","cinematic","padiem-home"];
    var s=null;
    try{
      var p=new URLSearchParams(location.search).get("theme");
      if(T.indexOf(p)!==-1) s=p;
    }catch(e){}
    if(T.indexOf(s)===-1){
      s=(window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches)?"dark":"light";
    }
    document.documentElement.setAttribute("data-theme",s);
    var cs=s==="light"?"light":s==="padiem-home"?"light":"dark";
    var mc=document.querySelector('meta[name="color-scheme"]'); if(mc) mc.setAttribute("content",cs);
    var tc=document.querySelector('meta[name="theme-color"]');
    if(tc){
      var map={light:"#f8f8fb",dark:"#131417",cinematic:"#04070d","padiem-home":"#e6e9ee"};
      tc.setAttribute("content",map[s]||"#04070d");
    }
  }catch(e){}
})();
