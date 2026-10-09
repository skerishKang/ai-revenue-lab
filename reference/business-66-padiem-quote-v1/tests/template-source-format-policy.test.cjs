"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Intake = require("../file-intake.js");
const Cloner = require("../quote-template-cloner.js");
const Registration = require("../quote-template-registration.js");
const SkillWizard = require("../quote-registration-session.js");
const xlsxMime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const basedir = path.join(__dirname, "..");
const classify = (name, type = "", size = 2048) =>
  Intake.classifyTemplateSourceFile({name, type, size});
const code = (result, expected, label) => {
  assert.equal(result.ok, false, label);
  assert.equal(result.error || result.code, expected, label);
};
const valid = classify("견적양식.XLSX", xlsxMime);
assert.equal(valid.ok, true);
assert.equal(valid.value.extension, ".xlsx");
assert.deepEqual(Intake.TEMPLATE_SOURCE_EXTENSIONS, [".xlsx"]);
assert.equal(classify("quote.xlsx", "").ok, true);
assert.equal(classify("quote.xlsx", "application/octet-stream").ok, true);
assert.equal(classify("quote.xlsx", "application/zip").ok, true);
code(classify("quote.xlsx", "application/pdf"), "media_extension_mismatch", "XLSX MIME spoof");
code(classify("quote.xlsx", xlsxMime, 0), "empty_file", "empty");
code(classify("quote.xlsx", xlsxMime, 2 * 1024 * 1024 + 1), "document_too_large", "oversize");
code(classify("quote.xls"), "legacy_xls_unsupported", "legacy XLS");
code(classify("quote.hwp"), "legacy_hwp_unsupported", "legacy HWP");
code(classify("quote.hwpx"), "template_hwpx_not_available", "future HWPX");
for (const ext of ["pdf","docx","pptx","csv","jpg","jpeg","png","webp"]) {
  code(classify("quote."+ext), "template_source_format_not_allowed", "not template registration: "+ext);
}
code(classify("quote"), "template_source_format_not_allowed", "missing extension");
assert.match(Intake.errorMessage({error:"legacy_xls_unsupported"}), /\.xlsx/);
assert.match(Intake.errorMessage({error:"template_hwpx_not_available"}), /HWPX/);
assert.match(Intake.errorMessage({error:"template_source_format_not_allowed"}), /\.xlsx/);
// Existing quote-fact analysis intake MUST remain broad, not unintentionally blocked.
assert.equal(Intake.classifyFile({name:"example.pdf", type:"application/pdf", size:42}).ok,true);
assert.equal(Intake.classifyFile({name:"example.docx", type:"", size:42}).ok,true);
assert.equal(Intake.classifyFile({name:"example.hwpx", type:"", size:42}).ok,true);
assert.equal(Intake.classifyFile({name:"example.png", type:"image/png", size:42}).ok,true);
assert.equal(Intake.classifyFile({name:"example.xls", type:"", size:42}).ok,false);

const v = Intake.validateTemplateSourcePreflight(valid);
assert.equal(v.ok,true);
assert.equal(v.name,"견적양식.XLSX");
assert.equal(v.extension,".xlsx");
assert.equal(v.size,2048);
assert.equal(v.media,xlsxMime);
assert.equal(Intake.validateTemplateSourcePreflight({
  ok:true, name:"legacy.xlsx", extension:".xlsx", media:xlsxMime, size:1
}).ok,true);
code(Intake.validateTemplateSourcePreflight({ok:true}),"template_source_format_not_allowed","missing metadata refused");
code(Intake.validateTemplateSourcePreflight({
  ok:true, name:"fake.pdf", extension:".xlsx", media:xlsxMime, size:512
}),"template_source_extension_mismatch","forged extension refused");
code(Intake.validateTemplateSourcePreflight({
  ok:true, name:"wrong.xls", extension:".xls", media:xlsxMime, size:512
}),"legacy_xls_unsupported","forged preflight XLS refused");
code(Intake.validateTemplateSourcePreflight({
  ok:true, name:"wrong.xlsx", extension:".xlsx", media:"application/pdf", size:512
}),"media_extension_mismatch","forged mime refused");
code(Intake.validateTemplateSourcePreflight({
  ok:true, value:{name:"missing-size.xlsx",extension:".xlsx",mediaType:xlsxMime}
}),"invalid_file_size","metadata with missing size refused");
const blank = Cloner.createSession({sessionId:"format-policy-test"});
const started = Cloner.startFromFile(blank, valid);
assert.equal(started.ok,true,"Cloner receives actual FileIntake wrapper");
assert.equal(started.session.source.name,"견적양식.XLSX");
assert.equal(started.session.source.preflight.extension,".xlsx");
assert.equal(started.session.source.preflight.size,2048);
for(const file of ["legacy.xls","sample.pdf","sample.hwpx"]) {
  const bad = Cloner.startFromFile(blank, {
    ok:true,name:file,extension: "."+file.split(".").pop(),media:"",size:2048
  });
  assert.equal(bad.ok,false,"Cloner rejects "+file);
  assert.equal(bad.session.status,Cloner.STATUS_FAILED);
  assert.equal(bad.session.source,null,"Rejected source creates no candidate");
  assert.equal(blank.source,null,"Caller session unchanged");
}
const registrationOK = Registration.buildTemplateCandidateFromSource({
  filename:"company.xlsx", mediaType:xlsxMime, byteSize:2048
},{now:"2026-10-10T00:00:00Z"});
assert.equal(registrationOK.ok,true,"Registration accepts xlsx metadata");
for(const [name,mime,expected] of [
  ["company.xls","application/vnd.ms-excel","legacy_xls_unsupported"],
  ["company.hwp","","legacy_hwp_unsupported"],
  ["company.hwpx","application/hwp+zip","template_hwpx_not_available"],
  ["company.pdf","application/pdf","template_source_format_not_allowed"],
  ["company.docx","","template_source_format_not_allowed"]
]) {
  const bad = Registration.buildTemplateCandidateFromSource({
    filename:name,mediaType:mime,byteSize:1000
  });
  assert.equal(bad.ok,false,name);
  assert.equal(bad.code,expected,name);
  assert.equal(bad.candidate,null,name+" produces no candidate");
}
const reference = Registration.buildTemplateCandidateFromSource({
  filename:"reference.pdf",mediaType:"application/pdf",byteSize:1024
},{sourceMode:"fact_reference"});
assert.equal(reference.ok,true,"explicit fact-only wizard may use a PDF reference");
assert.ok(reference.candidate.review.warnings.some(w=>w.code==="manual_layout_review_required"));
assert.equal(Registration.buildTemplateCandidateFromSource({
  filename:"reference.pdf",mediaType:"application/pdf",byteSize:1024
}).ok,false,"PDF cannot enter reusable-template registration");
assert.equal(SkillWizard.start({
  filename:"reference.pdf",mediaType:"application/pdf",byteSize:1024
},{sourceMode:"fact_reference"}).ok,true);
const html = fs.readFileSync(path.join(basedir,"index.html"),"utf8");
const chooser = html.match(/id="templateCloneFile"[\s\S]*?accept="([^"]+)"/);
assert.ok(chooser,"registration chooser exists");
assert.equal(chooser[1],".xlsx,"+xlsxMime);
assert.match(html, /id="easyFileInput"/,"general fact upload still present");
assert.ok((html.match(/accept="\.pdf,\.docx/g) || []).length >= 2,"generic fact and skill source chooser remain broad");
const skillUI = fs.readFileSync(path.join(basedir,"quote-skill-ui.js"),"utf8");
assert.match(skillUI,/sourceMode: "fact_reference"/);
const app = fs.readFileSync(path.join(basedir,"app.js"),"utf8");
assert.match(app,/FileIntake\.classifyTemplateSourceFile\(file\)/);
assert.match(app,/TemplateCloner\.startFromFile\(session, preflight\)/);
const source = fs.readFileSync(path.join(basedir,"quote-template-registration.js"),"utf8");
assert.match(source,/FileIntake\.validateTemplateSourcePreflight/);
console.log("B66_TEMPLATE_SOURCE_POLICY=PASS");
console.log("TEMPLATE_REGISTRATION_ALLOWED=XLSX_ONLY");
console.log("XLS_HWP_REJECTED=YES");
console.log("HWPX_FUTURE_ONLY=YES");
console.log("GENERIC_FILE_INTAKE_PRESERVED=YES");
console.log("DIRECT_REGISTRATION_BYPASS_DENIED=YES");
console.log("NO_SOURCE_CANDIDATE_FROM_DISALLOWED_FORMAT=YES");
console.log("NO_NETWORK_OR_MODEL_CALLS=YES");
