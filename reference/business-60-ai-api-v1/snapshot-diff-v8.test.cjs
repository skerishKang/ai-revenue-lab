const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadEngine(snapshots = []) {
  const source = fs.readFileSync(path.join(__dirname, 'snapshot-diff-v8.js'), 'utf8');
  const context = { window: { B60_SNAPSHOTS: snapshots }, Date };
  vm.createContext(context);
  vm.runInContext(source, context, { filename: 'snapshot-diff-v8.js' });
  return context.window.B60_DIFF_ENGINE;
}

const record = (overrides = {}) => ({
  id: 'a', provider: 'Provider', title: 'A', dealType: 'PERMANENT_FREE',
  verification: 'VERIFIED_OFFICIAL_WEB', freeLabel: 'Free', model: 'm1',
  context: '100K', price: '$0', access: ['API'], expiresAt: null,
  expiryVerification: null, ...overrides
});

test('classifies new, removed and grouped field changes', () => {
  const engine = loadEngine();
  const previous = { date:'2026-08-23', records:[record(), record({id:'removed'})] };
  const current = { date:'2026-08-24', records:[
    record({price:'$1', freeLabel:'100 calls/day', access:['API','PLAYGROUND']}),
    record({id:'new'})
  ] };

  const result = engine.compareSnapshots(previous, current);
  const types = result.events.map(e=>e.type).sort();
  assert.deepEqual(types, ['ACCESS_CHANGED','FREE_TIER_CHANGED','NEW','PRICE_CHANGED','REMOVED'].sort());
  assert.equal(result.summary.new, 1);
  assert.equal(result.summary.removed, 1);
  assert.equal(result.summary.changed, 3);
});

test('requires official expiry verification for ending soon', () => {
  const engine = loadEngine();
  const snapshot = { date:'2026-08-23', records:[
    record({id:'verified', expiresAt:'2026-08-27', expiryVerification:'VERIFIED_OFFICIAL_WEB'}),
    record({id:'pending', expiresAt:'2026-08-26', expiryVerification:'PENDING_WEB_VERIFICATION'}),
    record({id:'later', expiresAt:'2026-09-30', expiryVerification:'VERIFIED_OFFICIAL_WEB'})
  ] };
  const ending = engine.endingSoon(snapshot, new Date('2026-08-23T00:00:00Z'), 7);
  assert.deepEqual(ending.map(x=>x.id), ['verified']);
});

test('newToday is based only on firstSeen', () => {
  const engine = loadEngine();
  const history = [
    { id:'a', firstSeen:'2026-08-23' },
    { id:'b', firstSeen:'2026-08-22' }
  ];
  assert.deepEqual(engine.newToday(history, '2026-08-23'), ['a']);
});
