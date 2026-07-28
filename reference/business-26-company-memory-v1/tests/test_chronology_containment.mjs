// Chronology event containment regression test
// Validates that all chronology event labels fit within their boxes
// without overflow, clipping, or collisions across 3 viewports.

import { chromium } from 'playwright';

const VIEWPORTS = [
  { width: 1440, height: 1100, label: '1440x1100' },
  { width: 768, height: 1024, label: '768x1024' },
  { width: 390, height: 844, label: '390x844' },
];

const FAILING_LABEL = '04.19 현장 접촉 사고';

async function run() {
  const browser = await chromium.launch({ headless: true });
  let allPass = true;

  for (const vp of VIEWPORTS) {
    const page = await browser.newPage();
    await page.setViewportSize({ width: vp.width, height: vp.height });
    await page.goto('http://127.0.0.1:8000/?state=chronology', { waitUntil: 'networkidle' });
    await page.waitForSelector('[data-state="chronology"]');
    await page.waitForTimeout(500);

    console.log(`\n--- ${vp.label} ---`);

    // 1. Every chronology event: text contained
    const eventResults = await page.evaluate((failingLabel) => {
      const events = document.querySelectorAll('.chronology-bands .event');
      const fails = [];

      events.forEach((el, idx) => {
        const text = el.textContent.trim();
        const isFailing = text.includes(failingLabel);

        // Text node range containment
        const range = document.createRange();
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null, false);
        let textNode;
        let textRects = [];
        while (textNode = walker.nextNode()) {
          if (textNode.textContent.trim()) {
            range.selectNodeContents(textNode);
            textRects.push(range.getBoundingClientRect());
          }
        }

        const elRect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        const padL = parseFloat(style.paddingLeft) || 0;
        const padR = parseFloat(style.paddingRight) || 0;
        const innerLeft = elRect.left + padL;
        const innerRight = elRect.right - padR;

        // Check text rects fit within inner bounds (1px tolerance)
        let textOverflow = false;
        for (const tr of textRects) {
          if (tr.right > innerRight + 1 || tr.left < innerLeft - 1) {
            textOverflow = true;
            break;
          }
        }

        // Check scrollWidth vs clientWidth (<= 2px tolerance)
        const scrollOverflow = el.scrollWidth > el.clientWidth + 2;

        // Check no ellipsis
        const hasEllipsis = style.textOverflow === 'ellipsis';

        if (textOverflow || scrollOverflow || hasEllipsis) {
          fails.push({
            index: idx,
            text: text.slice(0, 40),
            scrollWidth: el.scrollWidth,
            clientWidth: el.clientWidth,
            textOverflow,
            scrollOverflow,
            hasEllipsis,
            isFailing,
          });
        }
      });

      return fails;
    }, FAILING_LABEL);

    // 2. Failing label specific check
    const specificResult = await page.evaluate((label) => {
      const events = Array.from(document.querySelectorAll('.chronology-bands .event'));
      const ev = events.find(e => e.textContent.trim().includes(label));
      if (!ev) return { found: false };

      const rect = ev.getBoundingClientRect();
      const style = window.getComputedStyle(ev);
      const range = document.createRange();
      const walker = document.createTreeWalker(ev, NodeFilter.SHOW_TEXT, null, false);
      let textNode;
      let textRects = [];
      while (textNode = walker.nextNode()) {
        if (textNode.textContent.trim()) {
          range.selectNodeContents(textNode);
          textRects.push(range.getBoundingClientRect());
        }
      }

      const padL = parseFloat(style.paddingLeft) || 0;
      const padR = parseFloat(style.paddingRight) || 0;
      const innerLeft = rect.left + padL;
      const innerRight = rect.right - padR;

      let textContained = true;
      for (const tr of textRects) {
        if (tr.right > innerRight + 1 || tr.left < innerLeft - 1) {
          textContained = false;
          break;
        }
      }

      return {
        found: true,
        text: ev.textContent.trim(),
        eventWidth: Math.round(rect.width),
        clientWidth: ev.clientWidth,
        scrollWidth: ev.scrollWidth,
        innerLeft, innerRight,
        textRects: textRects.map(t => ({ left: t.left, right: t.right, width: t.width })),
        textContained,
        scrollFit: ev.scrollWidth <= ev.clientWidth + 2,
      };
    }, FAILING_LABEL);

    // 3. Event track containment check at ALL viewports
    const trackResults = [];
    const tr = await page.evaluate(() => {
      const results = [];
      const tracks = document.querySelectorAll('.chronology-bands .track');
      tracks.forEach((track, ti) => {
        const trackRect = track.getBoundingClientRect();
        const events = track.querySelectorAll('.event');
        events.forEach((el) => {
          const rect = el.getBoundingClientRect();
          const text = el.textContent.trim().slice(0, 30);
          const exceeds = rect.right > trackRect.right + 2 || rect.left < trackRect.left - 2;
          if (exceeds) results.push({ track: ti, text, eventRight: rect.right, trackRight: trackRect.right });
        });
      });
      return results;
    });
    trackResults.push(...tr);

    // 4. Event collision check — at ALL viewports
    const collisionResults = [];
    const cr = await page.evaluate(() => {
      const collisions = [];
      const tracks = document.querySelectorAll('.chronology-bands .track');
      tracks.forEach((track) => {
        const events = Array.from(track.querySelectorAll('.event'));
        for (let i = 0; i < events.length; i++) {
          for (let j = i + 1; j < events.length; j++) {
            const a = events[i].getBoundingClientRect();
            const b = events[j].getBoundingClientRect();
            const textA = events[i].textContent.trim().slice(0, 30);
            const textB = events[j].textContent.trim().slice(0, 30);
            const hOverlap = a.right > b.left + 1 && b.right > a.left + 1;
            const vOverlap = a.bottom > b.top + 1 && b.bottom > a.top + 1;
            if (hOverlap && vOverlap) {
              collisions.push({ a: textA, b: textB, aRect: { l: a.left, r: a.right }, bRect: { l: b.left, r: b.right } });
            }
          }
        }
      });
      return collisions;
    });
    collisionResults.push(...cr);

    // 5. Visible year context check
    const yearResults = await page.evaluate(() => {
      const events = document.querySelectorAll('.chronology-bands .event');
      const missing = [];
      events.forEach((el) => {
        const timeEl = el.querySelector('time');
        if (!timeEl) {
          missing.push(el.textContent.trim().slice(0, 30));
        }
      });
      return missing;
    });

    // 6. Same-year event pair check (04.19 현장 접촉 사고 and 06.02 제한 운행 재개)
    const sameYearResults = await page.evaluate(() => {
      const events = Array.from(document.querySelectorAll('.chronology-bands .event'));
      const accident = events.find(e => e.textContent.includes('04.19 현장 접촉 사고'));
      const resume = events.find(e => e.textContent.includes('06.02 제한 운행 재개'));
      if (!accident || !resume) return { found: false };
      const a = accident.getBoundingClientRect();
      const b = resume.getBoundingClientRect();
      const hOverlap = a.right > b.left + 1 && b.right > a.left + 1;
      const vOverlap = a.bottom > b.top + 1 && b.bottom > a.top + 1;
      return {
        found: true,
        collision: hOverlap && vOverlap,
        aRect: { l: a.left, r: a.right, t: a.top, b: a.bottom },
        bRect: { l: b.left, r: b.right, t: b.top, b: b.bottom },
      };
    });

    // 7. Right-edge event check (2026 events)
    const rightEdgeResults = await page.evaluate(() => {
      const events = Array.from(document.querySelectorAll('.chronology-bands .event'));
      const tracks = document.querySelectorAll('.chronology-bands .track');
      const results = [];
      events.forEach((el) => {
        const rect = el.getBoundingClientRect();
        const track = el.closest('.track');
        if (!track) return;
        const trackRect = track.getBoundingClientRect();
        const text = el.textContent.trim().slice(0, 30);
        const exceeds = rect.right > trackRect.right + 2 || rect.left < trackRect.left - 2;
        if (exceeds) results.push({ text, eventRight: rect.right, trackRight: trackRect.right });
      });
      return results;
    });

    // Summary
    const textContained = eventResults.length === 0;
    const specificPass = specificResult?.found ? specificResult.textContained && specificResult.scrollFit : false;
    const trackContained = trackResults.length === 0;
    const noCollisions = collisionResults.length === 0;
    const yearContext = yearResults.length === 0;
    const sameYearNoCollision = sameYearResults.found ? !sameYearResults.collision : false;
    const rightEdgeContained = rightEdgeResults.length === 0;
    const pass = textContained && specificPass && trackContained && noCollisions && yearContext && sameYearNoCollision && rightEdgeContained;

    console.log(`text containment:  ${textContained ? 'PASS' : 'FAIL'} (${eventResults.length} issues)`);
    console.log(`failing label:     ${specificPass ? 'PASS' : 'FAIL'}`);
    if (specificResult?.found) {
      console.log(`  text: "${specificResult.text}"`);
      console.log(`  eventWidth=${specificResult.eventWidth} clientWidth=${specificResult.clientWidth} scrollWidth=${specificResult.scrollWidth}`);
      console.log(`  textContained=${specificResult.textContained} scrollFit=${specificResult.scrollFit}`);
    }
    console.log(`track containment: ${trackContained ? 'PASS' : 'FAIL'} (${trackResults.length} exceed)`);
    console.log(`collisions:        ${noCollisions ? 'PASS' : 'FAIL'} (${collisionResults.length} found)`);
    console.log(`year context:      ${yearContext ? 'PASS' : 'FAIL'} (${yearResults.length} missing)`);
    console.log(`same-year pair:    ${sameYearNoCollision ? 'PASS' : 'FAIL'}`);
    if (sameYearResults.found && sameYearResults.collision) {
      console.log(`  aRect: ${JSON.stringify(sameYearResults.aRect)}`);
      console.log(`  bRect: ${JSON.stringify(sameYearResults.bRect)}`);
    }
    console.log(`right-edge events: ${rightEdgeContained ? 'PASS' : 'FAIL'} (${rightEdgeResults.length} exceed)`);
    console.log(`OVERALL:           ${pass ? 'PASS' : 'FAIL'}`);

    if (eventResults.length) {
      console.log('  text overflow details:', JSON.stringify(eventResults));
    }
    if (trackResults.length) {
      console.log('  track overflow details:', JSON.stringify(trackResults));
    }
    if (collisionResults.length) {
      console.log('  collision details:', JSON.stringify(collisionResults));
    }

    if (!pass) allPass = false;
    await page.close();
  }

  await browser.close();
  console.log(`\n=== ${allPass ? 'ALL PASS' : 'SOME FAILURES'} ===`);
  process.exit(allPass ? 0 : 1);
}

run().catch(e => { console.error(e); process.exit(1); });
