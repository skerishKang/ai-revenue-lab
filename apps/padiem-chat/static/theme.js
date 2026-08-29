(function(){
  "use strict";
  const VALID=["light","dark","cinematic","padiem-home"];
  const THEME_COLORS={light:"#f8f8fb",dark:"#0b0c0e",cinematic:"#06080d","padiem-home":"#e6e9ee"};
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
    var tc=document.querySelector('meta[name="theme-color"]'); if(tc) tc.setAttribute("content",THEME_COLORS[theme]||"#06080d");
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

(function(){
  "use strict";
  const PROFILE_HEADER="X-Padiem-Model-Profile";
  const ACK_HEADER="X-Padiem-High-Contributor-Ack";
  const ACK_VERSION="contributor-v1";
  const VALID_PROFILES=["low","medium","high"];
  let selectedProfile="medium";
  let highAcknowledged=false;
  let nativeFetch=window.fetch.bind(window);

  function ensureStyles(){
    if(document.querySelector('link[data-padiem-model-profile]')) return;
    const link=document.createElement("link");
    link.rel="stylesheet";
    link.href="./model-profile.css";
    link.dataset.padiemModelProfile="true";
    document.head.appendChild(link);
  }

  function referenceContextActive(){
    const attachment=document.getElementById("attachmentTray");
    const project=document.getElementById("projectBanner");
    return Boolean((attachment&&!attachment.hidden)||(project&&!project.hidden));
  }

  function setRuntimeNote(message,state){
    const note=document.getElementById("runtimeNote");
    if(!note) return;
    note.textContent=message;
    if(state) note.dataset.state=state; else delete note.dataset.state;
  }

  function makeButton(text,className){
    const button=document.createElement("button");
    button.type="button";
    button.textContent=text;
    if(className) button.className=className;
    return button;
  }

  function buildDialog(){
    const dialog=document.createElement("dialog");
    dialog.id="highContributorDialog";
    dialog.className="high-contributor-dialog";
    dialog.setAttribute("aria-labelledby","highContributorTitle");

    const card=document.createElement("section");
    card.className="high-contributor-card";
    const title=document.createElement("h2");
    title.id="highContributorTitle";
    title.textContent="HIGH 사용 전 데이터 안내";
    const intro=document.createElement("p");
    intro.textContent="HIGH는 Contributor 제공 경로를 사용합니다. 입력 내용은 해당 제공 경로의 데이터 정책에 따라 처리될 수 있습니다.";
    const warning=document.createElement("p");
    warning.className="high-contributor-warning";
    warning.textContent="개인정보·기밀정보·첨부 문서·프로젝트 자료는 HIGH에 보내지 마세요. 파일, 프로젝트, 웹 도구가 연결된 요청은 서버에서 차단됩니다.";

    const label=document.createElement("label");
    label.className="high-contributor-check";
    const checkbox=document.createElement("input");
    checkbox.type="checkbox";
    checkbox.id="highContributorAck";
    const checkText=document.createElement("span");
    checkText.textContent="위 안내를 확인했고, 참고 자료가 없는 일반 텍스트 질문에만 HIGH를 사용하겠습니다.";
    label.append(checkbox,checkText);

    const actions=document.createElement("div");
    actions.className="high-contributor-actions";
    const cancel=makeButton("취소","");
    const confirm=makeButton("확인하고 HIGH 사용","high-confirm");
    confirm.disabled=true;
    actions.append(cancel,confirm);
    card.append(title,intro,warning,label,actions);
    dialog.appendChild(card);
    document.body.appendChild(dialog);

    checkbox.addEventListener("change",function(){confirm.disabled=!checkbox.checked;});
    cancel.addEventListener("click",function(){dialog.close("cancel");});
    dialog.addEventListener("cancel",function(event){event.preventDefault();dialog.close("cancel");});
    confirm.addEventListener("click",function(){
      if(!checkbox.checked) return;
      if(referenceContextActive()){
        checkbox.checked=false;
        confirm.disabled=true;
        setRuntimeNote("HIGH는 파일이나 프로젝트 참고 자료와 함께 사용할 수 없습니다.","error");
        dialog.close("blocked");
        return;
      }
      selectedProfile="high";
      highAcknowledged=true;
      syncSelect();
      dialog.close("confirmed");
      setRuntimeNote("HIGH가 선택되었습니다. 파일·프로젝트·웹 도구가 없는 일반 텍스트 질문에만 사용됩니다.","normal");
    });
    return {dialog:dialog,checkbox:checkbox,confirm:confirm};
  }

  let select=null;
  let dialogParts=null;

  function labelFor(profile){
    if(profile==="low") return "빠름 (LOW)";
    if(profile==="high") return "고급 (HIGH)";
    return "기본 (MEDIUM)";
  }

  function syncSelect(){
    if(select) select.value=selectedProfile;
    const pill=document.querySelector(".model-pill");
    if(!pill) return;
    const label=pill.querySelector(".model-profile-label");
    if(label) label.textContent=selectedProfile==="medium"?"기본 대화":selectedProfile==="low"?"빠른 대화":"고급 대화";
  }

  function setProfile(profile){
    if(VALID_PROFILES.indexOf(profile)===-1) return;
    if(profile==="high"){
      if(referenceContextActive()){
        setRuntimeNote("HIGH는 파일이나 프로젝트 참고 자료와 함께 사용할 수 없습니다.","error");
        syncSelect();
        return;
      }
      highAcknowledged=false;
      dialogParts.checkbox.checked=false;
      dialogParts.confirm.disabled=true;
      dialogParts.dialog.showModal();
      syncSelect();
      return;
    }
    selectedProfile=profile;
    highAcknowledged=false;
    syncSelect();
  }

  function resetForNewConversation(){
    selectedProfile="medium";
    highAcknowledged=false;
    syncSelect();
  }

  function installPicker(){
    const pill=document.querySelector(".model-pill");
    if(!pill) return;
    const existingText=Array.from(pill.querySelectorAll("span")).find(function(node){return node.textContent&&node.textContent.trim()==="기본 대화";});
    if(existingText) existingText.classList.add("model-profile-label");
    select=document.createElement("select");
    select.id="modelProfileSelect";
    select.className="model-profile-select";
    select.setAttribute("aria-label","AI 품질 선택");
    VALID_PROFILES.forEach(function(profile){
      const option=document.createElement("option");
      option.value=profile;
      option.textContent=labelFor(profile);
      if(profile==="medium") option.selected=true;
      select.appendChild(option);
    });
    select.addEventListener("change",function(){setProfile(select.value);});
    pill.appendChild(select);
    syncSelect();
  }

  function installContextObserver(){
    const targets=[document.getElementById("attachmentTray"),document.getElementById("projectBanner")].filter(Boolean);
    if(!targets.length||typeof MutationObserver!=="function") return;
    const observer=new MutationObserver(function(){
      if(selectedProfile==="high"&&referenceContextActive()){
        selectedProfile="medium";
        highAcknowledged=false;
        syncSelect();
        setRuntimeNote("참고 자료가 연결되어 HIGH가 해제되었습니다. 기본 AI 품질을 사용합니다.","normal");
      }
    });
    targets.forEach(function(target){observer.observe(target,{attributes:true,attributeFilter:["hidden"]});});
  }

  function installFetchGuard(){
    window.fetch=function(input,init){
      const options=init?Object.assign({},init):{};
      let url;
      try{url=new URL(typeof input==="string"?input:input.url,location.href);}catch(e){return nativeFetch(input,init);}
      const method=String(options.method||(typeof Request!=="undefined"&&input instanceof Request?input.method:"GET")).toUpperCase();
      if(method==="POST"&&(url.pathname==="/api/chat"||url.pathname==="/api/chat/stream")){
        const headers=new Headers(options.headers||(typeof Request!=="undefined"&&input instanceof Request?input.headers:undefined));
        headers.set(PROFILE_HEADER,selectedProfile);
        if(selectedProfile==="high"&&highAcknowledged){headers.set(ACK_HEADER,ACK_VERSION);}else{headers.delete(ACK_HEADER);}
        options.headers=headers;
      }
      return nativeFetch(input,options);
    };
  }

  // Install synchronously while theme.js is evaluated. search-sources.js and
  // other feature layers load later and intentionally wrap this guarded fetch.
  // Installing again on DOMContentLoaded would clobber those feature wrappers.
  installFetchGuard();

  function init(){
    ensureStyles();
    dialogParts=buildDialog();
    installPicker();
    installContextObserver();
    const newChat=document.getElementById("newChatButton");
    if(newChat) newChat.addEventListener("click",resetForNewConversation);
    window.__padiemModelProfile={
      getCurrent:function(){return selectedProfile;},
      isHighAcknowledged:function(){return highAcknowledged;},
      acknowledgementVersion:ACK_VERSION,
      reset:resetForNewConversation,
    };
  }

  if(document.readyState==="loading"){document.addEventListener("DOMContentLoaded",init);}else{init();}
})();
