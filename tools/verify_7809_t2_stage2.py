from pathlib import Path
import re, subprocess
root=Path(__file__).resolve().parents[1]
p=root/"apps/padiem-chat/static/app.js"
q=p.with_name("chat-conversation-module.js")
rel=p.relative_to(root).as_posix()
base=subprocess.check_output(["git","show","fbe74cba329ab568f050581491cf309c28fef0c6:"+rel],cwd=root).decode("utf-8")
app=p.read_text(encoding="utf-8")
mod=q.read_text(encoding="utf-8")
names="lifecycleForError addAssistantShell renderStoredAssistant renderWebGroundingNotice clawBoundedRefusalCopy clawGeneralFailure buildRetryBox revealErrorState failureCodeNote failureStatusLabel renderError renderCancelled handleCustomRequestFailure".split()
refs={"coreModule().uiT":"deps.uiT","authModule().loadAuthStatus":"deps.loadAuthStatus","navModuleInstance.openClawWorkspace":"deps.openClawWorkspace","projectModule.renderProjectState":"deps.renderProjectState","streaming.requestAnswer":"deps.requestAnswer","conversationModule().clearAttachment":"deps.clearAttachment"}
refs.update({n:"deps."+n for n in "MESSAGE_LIFECYCLE shell messageList authState conversationState conversationProduct activeProject selectedAttachments".split()})
def block(s,n):
    return re.search(r"^  function "+n+r"\(.*?^  }\n",s,re.M|re.S).group()
print("| Function | Dependency reference changes | Exact normalized match |")
print("|---|---|---|")
for n in names:
    old=block(base,n); new=old; used=[]
    for a,b in refs.items():
        new,count=re.subn(r"(?<![\w.])"+re.escape(a)+r"(?![\w])",b,new)
        if count: used.append(a+" -> "+b)
    assert block(mod,n)==new,n
    assert not re.search(r"^  function "+n+r"\(",app,re.M),n
    print("| "+n+" | "+(", ".join(used) or "none")+" | PASS |")
for n in ["CLAW_BOUNDED_REFUSAL_COPY","CUSTOM_AUTH_FAILURE_CODE","FAILURE_CODE_PATTERN"]:
    pattern=r"^  const "+n+r" = .*?;\n"
    assert re.search(pattern,base,re.M|re.S).group()==re.search(pattern,mod,re.M|re.S).group()
    assert not re.search(pattern,app,re.M|re.S)
    print("| "+n+" | none | PASS |")
assert len(app.splitlines())<len(base.splitlines())
assert re.findall(r"window\.\w+\s*=(?!=)",app)==re.findall(r"window\.\w+\s*=(?!=)",base)
print("app.js lines:",len(base.splitlines()),"->",len(app.splitlines()))

