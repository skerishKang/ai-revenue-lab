(() => {
  const FIELD_EVENT = {
    price: 'PRICE_CHANGED',
    freeLabel: 'FREE_TIER_CHANGED',
    dealType: 'FREE_TIER_CHANGED',
    access: 'ACCESS_CHANGED',
    expiresAt: 'EXPIRES_AT_CHANGED',
    expiryVerification: 'EXPIRES_AT_CHANGED',
    model: 'MODEL_CHANGED',
    context: 'MODEL_CHANGED',
    verification: 'VERIFICATION_CHANGED'
  };

  const TRACKED_FIELDS = Object.keys(FIELD_EVENT);
  const stable = value => Array.isArray(value) ? [...value].sort().join('|') : (value ?? null);
  const snapshotMap = snapshot => new Map((snapshot?.records || []).map(record => [record.id, record]));

  function verified(record){
    return record?.verification === 'VERIFIED_OFFICIAL_WEB';
  }

  function compareSnapshots(previous, current){
    if (!previous || !current) return { previous: previous?.date || null, current: current?.date || null, events: [], summary: emptySummary() };

    const before = snapshotMap(previous);
    const after = snapshotMap(current);
    const events = [];

    for (const [id, record] of after) {
      if (!before.has(id)) {
        events.push({ type:'NEW', id, date:current.date, verified:verified(record), before:null, after:record });
        continue;
      }

      const old = before.get(id);
      const changedTypes = new Map();
      for (const field of TRACKED_FIELDS) {
        if (stable(old[field]) === stable(record[field])) continue;
        const type = FIELD_EVENT[field];
        if (!changedTypes.has(type)) changedTypes.set(type, []);
        changedTypes.get(type).push({ field, before:old[field] ?? null, after:record[field] ?? null });
      }

      for (const [type, changes] of changedTypes) {
        events.push({
          type,
          id,
          date:current.date,
          verified:verified(old) && verified(record),
          before:old,
          after:record,
          changes
        });
      }
    }

    for (const [id, record] of before) {
      if (!after.has(id)) events.push({ type:'REMOVED', id, date:current.date, verified:verified(record), before:record, after:null });
    }

    return { previous:previous.date, current:current.date, events, summary:summarize(events) };
  }

  function emptySummary(){
    return { total:0, verified:0, new:0, removed:0, changed:0, endingSoon:0 };
  }

  function summarize(events){
    const summary = emptySummary();
    summary.total = events.length;
    summary.verified = events.filter(event => event.verified).length;
    summary.new = events.filter(event => event.type === 'NEW').length;
    summary.removed = events.filter(event => event.type === 'REMOVED').length;
    summary.changed = events.filter(event => !['NEW','REMOVED'].includes(event.type)).length;
    return summary;
  }

  function endingSoon(snapshot, now = new Date(), horizonDays = 7){
    const end = new Date(now.getTime() + horizonDays * 86400000);
    return (snapshot?.records || []).filter(record => {
      if (!record.expiresAt || record.expiryVerification !== 'VERIFIED_OFFICIAL_WEB') return false;
      const expiry = new Date(`${record.expiresAt}T23:59:59`);
      return Number.isFinite(expiry.getTime()) && expiry >= now && expiry <= end;
    });
  }

  function newToday(history, date){
    return (history || []).filter(item => item.firstSeen === date).map(item => item.id);
  }

  const api = { compareSnapshots, endingSoon, newToday, TRACKED_FIELDS };
  window.B60_DIFF_ENGINE = api;

  const snapshots = window.B60_SNAPSHOTS || [];
  window.B60_SNAPSHOT_DIFF = snapshots.length >= 2
    ? compareSnapshots(snapshots[snapshots.length - 2], snapshots[snapshots.length - 1])
    : { previous:null, current:snapshots.at(-1)?.date || null, events:[], summary:emptySummary() };
})();
