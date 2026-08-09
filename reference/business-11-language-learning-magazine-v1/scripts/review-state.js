(() => {
  const stateNames = ["cover", "reading", "vocabulary", "revision", "feedback", "mobile", "motion"];
  const shell = document.querySelector(".review-shell");
  const tabs = [...document.querySelectorAll("[data-state]")];
  const panels = [...document.querySelectorAll("[data-state-panel]")];
  const echoStage = document.querySelector(".echo-stage");
  const echoTrigger = document.querySelector(".echo-trigger");
  const echoReplay = document.querySelector("[data-echo-replay]");
  const echoReset = document.querySelector("[data-echo-reset]");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let echoTimer = 0;
  function normalizedState(value){return stateNames.includes(value)?value:"cover"}
  function showState(nextState,{updateHash=true,focusPanel=false}={}){const state=normalizedState(nextState);shell.dataset.currentState=state;panels.forEach(panel=>{const active=panel.dataset.statePanel===state;panel.hidden=!active;panel.classList.toggle("is-active",active);if(active&&focusPanel)panel.focus({preventScroll:false})});tabs.forEach(tab=>{const active=tab.dataset.state===state;tab.classList.toggle("is-active",active);tab.setAttribute("aria-pressed",String(active))});if(updateHash&&location.hash!==`#${state}`)history.replaceState(null,"",`#${state}`)}
  function syncReducedMotion(){document.documentElement.dataset.reducedMotion=String(reducedMotion.matches)}
  function setEchoExpanded(expanded){window.clearTimeout(echoTimer);echoStage.classList.remove("is-echoing");echoStage.classList.toggle("is-expanded",expanded);echoTrigger.classList.toggle("is-expanded",expanded);echoTrigger.setAttribute("aria-expanded",String(expanded));echoReplay.setAttribute("aria-busy","false")}
  function replayEcho(){const stableScrollY=window.scrollY;window.clearTimeout(echoTimer);echoStage.classList.remove("is-expanded","is-echoing");echoTrigger.classList.remove("is-expanded");echoTrigger.setAttribute("aria-expanded","false");echoReplay.setAttribute("aria-busy","true");if(reducedMotion.matches){setEchoExpanded(true);window.scrollTo(0,stableScrollY);return}requestAnimationFrame(()=>{requestAnimationFrame(()=>{echoStage.classList.add("is-echoing");window.scrollTo(0,stableScrollY);echoTimer=window.setTimeout(()=>{setEchoExpanded(true);window.scrollTo(0,stableScrollY)},700)})})}
  tabs.forEach((tab,index)=>{tab.addEventListener("click",()=>showState(tab.dataset.state));tab.addEventListener("keydown",event=>{if(!["ArrowLeft","ArrowRight","Home","End"].includes(event.key))return;event.preventDefault();let nextIndex=index;if(event.key==="ArrowRight")nextIndex=(index+1)%tabs.length;if(event.key==="ArrowLeft")nextIndex=(index-1+tabs.length)%tabs.length;if(event.key==="Home")nextIndex=0;if(event.key==="End")nextIndex=tabs.length-1;tabs[nextIndex].focus();showState(tabs[nextIndex].dataset.state)})});
  echoTrigger.addEventListener("click",()=>setEchoExpanded(!echoStage.classList.contains("is-expanded")));echoReplay.addEventListener("click",replayEcho);echoReset.addEventListener("click",()=>setEchoExpanded(false));window.addEventListener("hashchange",()=>showState(location.hash.slice(1),{updateHash:false}));reducedMotion.addEventListener("change",syncReducedMotion);
  const reviewBar=document.querySelector('.review-bar');if(reviewBar){const links=document.createElement('div');links.setAttribute('aria-label','제품 사용 링크');links.style.cssText='display:flex;gap:10px;flex-wrap:wrap;padding:8px 0;font:700 12px system-ui';links.innerHTML='<a href="./guide.html" style="color:inherit;text-underline-offset:3px">30초 사용법</a><a href="./ux.html#read" style="color:inherit;text-underline-offset:3px">학습 체험</a>';reviewBar.appendChild(links)}
  syncReducedMotion();showState(location.hash.slice(1),{updateHash:false});
})();
