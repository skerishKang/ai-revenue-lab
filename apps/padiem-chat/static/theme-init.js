(function(){
  try{
    var T=["light","dark","cinematic","padiem-home"];
    var k="padiem_theme";
    var s=null;
    try{ s=localStorage.getItem(k); }catch(e){}
    if(T.indexOf(s)===-1){
      s = (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) ? "dark" : "light";
    }
    document.documentElement.setAttribute("data-theme", s);
    var cs = s==="light" ? "light" : s==="padiem-home" ? "light" : "dark";
    var mc = document.querySelector('meta[name="color-scheme"]'); if(mc) mc.setAttribute("content", cs);
    var tc = document.querySelector('meta[name="theme-color"]');
    if(tc){
      var map={light:"#f8f8fb",dark:"#0b0c0e",cinematic:"#06080d","padiem-home":"#e6e9ee"};
      tc.setAttribute("content", map[s]||"#06080d");
    }
  }catch(e){}
})();
