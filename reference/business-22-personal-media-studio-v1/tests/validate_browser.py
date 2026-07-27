#!/usr/bin/env python3
from __future__ import annotations

import json
from typing import Any
from playwright.sync_api import sync_playwright
from browser_harness import EVIDENCE, STATES, computed_relay_timing, load_state, relay_snapshot, same_geometry, state_metrics, write_motion_evidence


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"kind":"business-22-browser-validation","baseUrl":"in-memory://business-22/index.html",
      "browserEnvironment":"Chromium headless with fully inlined set_content; localhost and file navigation blocked by administrator policy",
      "viewports":{},"consoleErrors":[],"pageErrors":[],"failedRequests":[],"externalRequests":[],"keyboard":{},"motion":{},"reducedMotion":{}}
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path="/usr/bin/chromium",headless=True,args=["--no-sandbox"])
        context=browser.new_context(viewport={"width":1440,"height":1100},device_scale_factor=1); page=context.new_page()
        page.on("console",lambda msg: report["consoleErrors"].append(msg.text) if msg.type=="error" else None)
        page.on("pageerror",lambda exc: report["pageErrors"].append(str(exc)))
        page.on("requestfailed",lambda req: report["failedRequests"].append({"url":req.url,"failure":req.failure}))
        page.on("request",lambda req: report["externalRequests"].append(req.url) if req.url.startswith(("http://","https://")) else None)

        desktop=[]
        for state in STATES:
            load_state(page,state); desktop.append(state_metrics(page,state))
        report["viewports"]["1440x1100"]=desktop
        load_state(page,"cover"); page.locator("#tab-cover").focus(); page.keyboard.press("ArrowRight")
        right,focus=page.evaluate("window.__B22_REVIEW__.getState()"),page.evaluate("document.activeElement?.id")
        page.keyboard.press("End"); end=page.evaluate("window.__B22_REVIEW__.getState()")
        page.keyboard.press("Home"); home=page.evaluate("window.__B22_REVIEW__.getState()")
        report["keyboard"]={"arrowRightState":right,"arrowRightFocus":focus,"endState":end,"homeState":home,"passed":right=="sources" and focus=="tab-sources" and end=="mobile" and home=="cover"}

        for size,states in [((768,1024),["sources","suite","adaptation"]),((390,844),["cover","suite","mobile"])]:
            page.set_viewport_size({"width":size[0],"height":size[1]}); metrics=[]
            for state in states:
                load_state(page,state); metrics.append(state_metrics(page,state))
            report["viewports"][f"{size[0]}x{size[1]}"]=metrics

        page.set_viewport_size({"width":1440,"height":1100}); load_state(page,"adaptation",True); page.wait_for_timeout(360)
        page.locator('[data-action="replay"]').focus(); page.evaluate("document.documentElement.style.scrollBehavior='auto';scrollTo(0,20)"); page.wait_for_function("scrollY===20")
        before=relay_snapshot(page); page.keyboard.press("Enter"); running=relay_snapshot(page); timing=computed_relay_timing(page)
        page.wait_for_function("document.querySelector('[data-relay]').dataset.motionState==='complete'",timeout=2000); after=relay_snapshot(page)
        stable=before["focus"]==after["focus"]=="replay" and before["x"]==after["x"] and before["y"]==after["y"] and before["h"]==after["h"] and same_geometry(before["source"],after["source"])
        timing_ok=680<=timing["computedFinalEndMs"]<=760
        report["motion"]={"before":before,"running":running,"after":after,"computedTiming":timing,"computedFinalEndMs":timing["computedFinalEndMs"],
          "timingRangePassed":timing_ok,"runningStatePassed":running["state"]=="running","completionStatePassed":after["state"]=="complete",
          "focusScrollGeometryPassed":stable,"humanReviewVisible":after["reviewVisible"],"passed":timing_ok and running["state"]=="running" and after["state"]=="complete" and stable and after["reviewVisible"],
          "evidenceFrames":["motion-relay-frames.svg / 00 before","motion-relay-frames.svg / 01 annotation","motion-relay-frames.svg / 02 article","motion-relay-frames.svg / 03 formats","motion-relay-frames.svg / 04 review"]}
        context.close()

        reduced=browser.new_context(viewport={"width":1440,"height":1100},reduced_motion="reduce"); rp=reduced.new_page(); load_state(rp,"adaptation",True)
        rp.locator('[data-action="replay"]').focus(); rp.evaluate("document.documentElement.style.scrollBehavior='auto';scrollTo(0,20)"); rp.wait_for_function("scrollY===20")
        rb=relay_snapshot(rp); rp.keyboard.press("Enter"); ra=relay_snapshot(rp)
        visible=rp.evaluate("[...document.querySelectorAll('.relay-step')].every(el=>getComputedStyle(el).opacity==='1')")
        stable=rb["x"]==ra["x"] and rb["y"]==ra["y"] and rb["h"]==ra["h"] and same_geometry(rb["source"],ra["source"])
        report["reducedMotion"]={"before":rb,"after":ra,"allFinalStepsVisible":visible,"humanReviewVisible":ra["reviewVisible"],"focus":ra["focus"],"state":ra["state"],"geometryStable":stable,
          "passed":bool(visible and ra["reviewVisible"] and ra["focus"]=="replay" and ra["state"]=="complete" and stable)}
        reduced.close(); browser.close()

    metrics=[item for group in report["viewports"].values() for item in group]
    report["summary"]={"allQueriesResolve":all(m["active"]==m["state"] and m["visible"] for m in metrics),"zeroHorizontalOverflow":all(m["horizontalOverflow"]<=0 for m in metrics),
      "zeroBrokenImages":all(not m["brokenImages"] for m in metrics),"zeroConsoleErrors":not report["consoleErrors"],"zeroPageErrors":not report["pageErrors"],
      "zeroFailedRequests":not report["failedRequests"],"zeroExternalRequests":not report["externalRequests"],"keyboardPassed":report["keyboard"]["passed"],
      "motionPassed":report["motion"]["passed"],"reducedMotionPassed":report["reducedMotion"]["passed"]}
    report["passed"]=all(report["summary"].values()); report["motionEvidence"]=write_motion_evidence(report["motion"])
    (EVIDENCE/"validation-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    (EVIDENCE/"motion-frames.json").write_text(json.dumps(report["motion"],ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report["summary"],ensure_ascii=False,indent=2)); return 0 if report["passed"] else 1


if __name__=="__main__": raise SystemExit(main())
