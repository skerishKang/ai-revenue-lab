(function(){
  try{
    var T=["light","dark","cinematic","padiem-home","padiem-glass"];
    var G=["female","male"];
    var M=["auto","on","off"];
    var s=null;
    var glass="female";
    var mask="auto";
    var speed=100;
    try{
      var params=new URLSearchParams(location.search);
      var p=params.get("theme");
      var g=params.get("glass");
      var mk=params.get("mask");
      var sp=parseInt(params.get("speed")||"",10);
      if(T.indexOf(p)!==-1) s=p;
      if(G.indexOf(g)!==-1) glass=g;
      if(M.indexOf(mk)!==-1) mask=mk;
      if(sp>=20&&sp<=300) speed=sp;
    }catch(e){}
    if(T.indexOf(s)===-1){
      s="padiem-glass";
    }
    document.documentElement.setAttribute("data-theme",s);
    document.documentElement.setAttribute("data-glass-variant",glass);
    document.documentElement.setAttribute("data-glass-mask",mask);
    document.documentElement.setAttribute("data-glass-speed",String(speed));
    if(s==="padiem-glass"){
      if(!document.querySelector('link[data-padiem-glass-theme]')){
        var gl=document.createElement("link");
        gl.rel="stylesheet";
        gl.href="./padiem-glass.css";
        gl.setAttribute("data-padiem-glass-theme","");
        document.head.appendChild(gl);
      }
      if(!document.querySelector('link[data-padiem-glass-portrait]')){
        var portrait=document.createElement("link");
        portrait.rel="stylesheet";
        portrait.href="./padiem-glass-portrait.css";
        portrait.setAttribute("data-padiem-glass-portrait","");
        document.head.appendChild(portrait);
      }
    }
    if(!document.querySelector('script[data-padiem-conversation-motion]')){
      var motion=document.createElement("script");
      motion.src="./conversation-motion.js";
      motion.defer=true;
      motion.setAttribute("data-padiem-conversation-motion","");
      document.head.appendChild(motion);
    }
    var cs=(s==="light"||s==="padiem-home"||s==="padiem-glass")?"light":"dark";
    var mc=document.querySelector('meta[name="color-scheme"]'); if(mc) mc.setAttribute("content",cs);
    var tc=document.querySelector('meta[name="theme-color"]');
    if(tc){
      var map={light:"#f8f8fb",dark:"#131417",cinematic:"#04070d","padiem-home":"#e6e9ee","padiem-glass":"#aeb6bf"};
      tc.setAttribute("content",map[s]||"#04070d");
    }
  }catch(e){}
})();
