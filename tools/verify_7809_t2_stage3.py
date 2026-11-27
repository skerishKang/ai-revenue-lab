from pathlib import Path
import re,subprocess
root=Path(__file__).resolve().parents[1]
rel="apps/padiem-chat/static/app.js"
base=subprocess.check_output(["git","show","4a8cede7a17a1c843fd0dd14d0ac151812d24c4d:"+rel],cwd=root).decode()
app=(root/rel).read_text(encoding="utf-8")
mod=(root/rel).with_name("chat-entry-module.js").read_text(encoding="utf-8")
refs={x:"deps."+x for x in "authState inFlight authViewEpoch clawConversationLabelsRead clawConversationIds PRODUCT_CLAW PRODUCT_CHAT messageList conversationState conversationProduct activeProject activeProjectFileCount conversationArtifactContext clawArtifactShownFor input shell clawManualForm lastCompletedAnswerRequest selectedAttachments".split()}
refs.update({x:"deps."+x.split(".")[-1] for x in ["coreModule().uiT","coreModule().setNote","projectModule.ensureProject","projectModule.renderProjectState","projectModule.refreshActiveProjectFileCount","navModuleInstance.openClawWorkspace","app.syncApprovedMemoryVisibility","runHistory.syncClawRunHistoryVisibility","pcRunModuleInstance.resumeUnfinishedPcRun","sidebar.closeSidebar","authModule().requireSessionForModelUse","streaming.requestAnswer"]})
refs.update({"conversationModule()."+x:"deps."+x for x in ["clearAttachment","showConversation","addUserMessage","renderStoredAssistant","updateComposer"]})
def block(s,n):
    return re.search(r"^  (?:async )?function "+n+r"\(.*?^  }\n",s,re.M|re.S).group()
print("| Function | Lines | Dependency reference changes | Exact match |")
print("|---|---:|---|---|")
for n in ("openSavedConversation","clawGeneralRequestActive","storedRegenerateRequest","submitPrompt"):
    old=block(base,n); expected=old; used=[]
    for a,b in sorted(refs.items(),key=lambda pair:-len(pair[0])):
        if a=="messageList":
            pattern=r'(?<![\w."])'+re.escape(a)+r'(?![\w"])'
        else:
            pattern=r"(?<![\w.])"+re.escape(a)+r"(?![\w])"
        expected,count=re.subn(pattern,b,expected)
        if count: used.append(a+" -> "+b)
    assert block(mod,n)==expected,n
    assert not re.search(r"^  (?:async )?function "+n+r"\(",app,re.M),n
    print("| "+n+" | "+str(len(old.splitlines()))+" | "+", ".join(used)+" | PASS |")
for n in ("readStoredAndroidHandoff","storeAndroidHandoff","resumeAndroidHandoff"):
    assert block(base,n)==block(app,n),n
assert len(base.splitlines())-len(app.splitlines())>=100
assert re.findall(r"window\.\w+\s*=(?!=)",app)==re.findall(r"window\.\w+\s*=(?!=)",base)
print("app.js lines:",len(base.splitlines()),"->",len(app.splitlines()))
