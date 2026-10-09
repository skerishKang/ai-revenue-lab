/* Source-profile adapter. QuoteCore remains the money/calculation authority. */
'use strict';
const fs = require('node:fs');
const Core = require('../quote-core.js');
const request = JSON.parse(fs.readFileSync(0, 'utf8'));
const draft = structuredClone(request.draft);
const change = request.changes || {};
function supplyAmount(raw) {
  if (typeof raw === 'number') return raw;
  const simple = Core.parseKoreanMoney(raw);
  if (simple !== null) return simple;
  const value=String(raw).replace(/[\s,]/g,'').replace(/원$/,'');
  const units={'억':100000000,'천만':10000000,'백만':1000000,'십만':100000,'만':10000,'천':1000,'백':100,'십':10};
  const tokens=[...value.matchAll(/(\d+)(억|천만|백만|십만|만|천|백|십)?/g)];
  if (!tokens.length || tokens.map(x=>x[0]).join('') !== value) return null;
  let total=0,previous=Infinity;
  for (const [,digits,unit] of tokens) {
    const multiplier=units[unit]||1;
    if (multiplier>=previous) return null;
    total+=Number(digits)*multiplier;previous=multiplier;
  }
  return Number.isSafeInteger(total)?total:null;
}
const allowed = new Set(['recipient', 'project', 'subtotal', 'issueDate', 'quoteNo', 'items']);
for (const key of Object.keys(change)) if (!allowed.has(key)) throw Error(`Unsupported field: ${key}`);
for (const key of ['recipient','project','issueDate','quoteNo']) {
  if (key in change && (typeof change[key] !== 'string' || !change[key].trim() || /[\r\n]/.test(change[key]))) {
    throw Error(`Invalid ${key}`);
  }
}
if ('recipient' in change) draft.recipient.company = change.recipient.trim();
if ('project' in change) draft.meta.projectName = change.project.trim();
if ('quoteNo' in change) draft.meta.quoteNo = change.quoteNo.trim();
if ('issueDate' in change) {
  const value = change.issueDate;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || new Date(value).toISOString().slice(0,10) !== value) throw Error('Invalid date');
  draft.meta.issueDate = value;
}
if ('items' in change) {
  if ('subtotal' in change) throw Error('Specify items or subtotal, not both');
  if (!Array.isArray(change.items) || change.items.length < 1 || change.items.length > 3) throw Error('This fixed-layout profile supports 1–3 item rows');
  draft.items = change.items.map((item,i) => {
    if (!item || typeof item !== 'object') throw Error('Invalid item');
    for (const k of Object.keys(item)) if (!['name','spec','unit','qty','unitPrice','note'].includes(k)) throw Error(`Unsupported item field: ${k}`);
    if (!Number.isFinite(item.qty) || item.qty < 0 || !Number.isSafeInteger(item.unitPrice) || item.unitPrice < 0 || !Number.isSafeInteger(Math.round(item.qty * item.unitPrice))) throw Error('Invalid item amount');
    for (const k of ['name','spec','unit','note']) if (k in item && (typeof item[k] !== 'string' || /[\r\n]/.test(item[k]))) throw Error(`Invalid item ${k}`);
    if (!item.name || !item.name.trim()) throw Error('Item name is required');
    return {id:`item-${i+1}`,name:item.name.trim(),spec:item.spec||'',unit:item.unit||'',qty:item.qty,unitPrice:item.unitPrice,note:item.note||''};
  });
}
if ('subtotal' in change) {
  const n = supplyAmount(change.subtotal);
  if (!Number.isSafeInteger(n) || n < 0) throw Error('Invalid supply amount');
  if (draft.items.length !== 1 || draft.items[0].qty !== 1) throw Error('Subtotal changes require the original one-item, quantity-one profile; otherwise supply explicit items');
  draft.items[0].unitPrice = n;
}
const normalized = Core.normalizeDraft(draft);
if (!normalized) throw Error('Invalid quote draft');
const totals = Core.computeDraftTotals(normalized);
if (!totals || !Number.isSafeInteger(totals.grand)) throw Error('Invalid totals');
const integer = n => Math.round(n).toLocaleString('ko-KR');
const money = Core.formatKoreanMoneyWords(totals.grand);
if (money === null) throw Error('Unsupported Korean money amount');
const slots = {
  recipient:normalized.recipient.company, project:normalized.meta.projectName,
  issueDate:normalized.meta.issueDate.replaceAll('-',''),quoteNo:normalized.meta.quoteNo,
  grandWrittenLine:` 합계금액 : 일금 ${money}원정 ( \\${integer(totals.grand)} )`,
  subtotal:integer(totals.subtotal),vat:integer(totals.vat),grand:integer(totals.grand)
};
for (let i=0;i<3;i++) {
  const it=normalized.items[i];
  for (const [k,val] of Object.entries({Name:it?.name||'',Spec:it?.spec||'',Unit:it?.unit||'',Qty:it?String(it.qty):'',UnitPrice:it?integer(it.unitPrice):'',Amount:it?integer(Core.itemAmount(it)):'-',Note:it?.note||''})) slots[`item${i}${k}`]=val;
}
process.stdout.write(JSON.stringify({draft:normalized,totals,slots}));
