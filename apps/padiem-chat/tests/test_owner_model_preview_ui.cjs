"use strict";
/* #6828: the removed public model preview must not come back through a browser
 * asset. The old spec drove the preview script and its payload; the subject is
 * gone, so this spec now fails if the asset, its loader or its markup reappears. */
const test=require("node:test"), assert=require("node:assert/strict");
const fs=require("node:fs"),path=require("node:path");
const staticDir=path.join(__dirname,"..","static");
const asset=path.join(staticDir,"owner-model-preview.js");
const html=fs.readFileSync(path.join(staticDir,"index.html"),"utf8");
const locale=fs.readFileSync(path.join(staticDir,"locale.js"),"utf8");

test("the preview script is not shipped and not loaded",()=>{
  assert.equal(fs.existsSync(asset),false,"owner-model-preview.js must stay removed");
  assert.equal(html.includes("owner-model-preview.js"),false);
});

test("the preview dialog markup is not in the page",()=>{
  for(const id of ["ownerModelPreviewDialog","ownerModelPreviewTitle","ownerModelPreviewScope",
    "ownerModelPreviewStatus","ownerModelPreviewList","ownerModelPreviewClose","ownerModelPreviewOpen"]){
    assert.equal(html.includes(`id="${id}"`),false,id);
  }
});

test("the preview copy is gone from both locales",()=>{
  assert.equal(locale.includes("owner-model-preview"),false);
  assert.equal(locale.includes("모델 현황"),false);
  assert.equal(locale.includes("model status"),false);
});

test("the composer layout is retained without the preview sheet",()=>{
  assert.equal(html.includes('owner-model-preview.css'),false);
  assert.equal(fs.existsSync(path.join(staticDir,"owner-model-preview.css")),false);
  const css=fs.readFileSync(path.join(staticDir,"attachments.css"),"utf8");
  assert.equal(css.includes("width: 116px"),true);
});
