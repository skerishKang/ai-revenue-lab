/* Focus-scope repair tests.
 * Repository-local source + DOM-contract checks (no browser):
 * closed drawer excludes hidden drawer buttons; open drawer isolates roving
 * focus to drawer buttons with modal semantics and close-button focus.
 */
'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

let failures = 0;

function check(name, fn) {
  try {
    fn();
    console.log('PASS ' + name);
  } catch (error) {
    failures += 1;
    console.error('FAIL ' + name + ': ' + error.message);
  }
}

const root = path.join(__dirname, '..');
const appSrc = fs.readFileSync(path.join(root, 'scripts', 'app.js'), 'utf8');
const templatesSrc = fs.readFileSync(path.join(root, 'scripts', 'templates.js'), 'utf8');
const indexHtml = fs.readFileSync(path.join(root, 'index.html'), 'utf8');

check('closed drawer excludes drawer buttons from focusables', function () {
  const collect = appSrc.slice(appSrc.indexOf('function collectFocusables'), appSrc.indexOf('function syncDrawerAria'));
  assert.ok(
    collect.indexOf('const list = store.evidenceOpen ? drawerButtons : viewButtons;') !== -1,
    'focus scope must branch on drawer state'
  );
  assert.ok(
    collect.indexOf('focusables = list;') !== -1,
    'focusables must be assigned the single active scope'
  );
  assert.ok(
    collect.indexOf('viewButtons.concat(drawerButtons)') === -1,
    'unconditional concat must be removed'
  );
});

check('open drawer excludes view buttons from focusables', function () {
  const collect = appSrc.slice(appSrc.indexOf('function collectFocusables'), appSrc.indexOf('function syncDrawerAria'));
  assert.ok(
    collect.indexOf('store.evidenceOpen ? drawerButtons : viewButtons') !== -1,
    'open drawer must select drawerButtons only'
  );
  assert.ok(
    collect.indexOf("viewButtons.forEach(function (el) {\n        el.tabIndex = -1;") !== -1,
    'view buttons must leave the tab order while the drawer is open'
  );
});

check('open drawer close button has tabindex 0', function () {
  const collect = appSrc.slice(appSrc.indexOf('function collectFocusables'), appSrc.indexOf('function syncDrawerAria'));
  assert.ok(
    collect.indexOf('el.tabIndex = index === 0 ? 0 : -1;') !== -1,
    'roving focus must give the first drawer button tabindex 0'
  );
  const drawerHtml = templatesSrc.slice(
    templatesSrc.indexOf('evidence-drawer-content'),
    templatesSrc.indexOf('</section>', templatesSrc.indexOf('evidence-drawer-content'))
  );
  const buttons = (drawerHtml.match(/<button[^>]*>/g) || []).filter(function (b) {
    return b.indexOf('data-action') !== -1;
  });
  assert.ok(buttons.length >= 1, 'drawer must contain its close button');
  assert.ok(drawerHtml.indexOf('data-focus-key="drawer-close"') !== -1, 'close button focus key missing');
});

check('open drawer initial focus targets drawer-close', function () {
  const branch = appSrc.slice(appSrc.indexOf('meta.drawerOpened'), appSrc.indexOf('meta.drawerClosed'));
  assert.ok(
    branch.indexOf('[data-focus-key="drawer-close"]') !== -1,
    'drawer open must prefer the close button'
  );
  const order = branch.indexOf('drawer-close') < branch.indexOf('drawer-heading');
  assert.ok(order, 'drawer-close must precede drawer-heading in the focus branch');
});

check('closed drawer has zero focusable drawer controls', function () {
  const close = appSrc.slice(appSrc.indexOf('function closeDrawer'), appSrc.indexOf('function focusElement'));
  assert.ok(
    close.indexOf("drawerEl.innerHTML = '';") !== -1,
    'close must clear the drawer content'
  );
  assert.ok(close.indexOf("drawerEl.hidden = true;") !== -1, 'close must hide the drawer');
});

check('Escape closes drawer and returns focus to opener', function () {
  assert.ok(appSrc.indexOf("event.key === 'Escape'") !== -1, 'Escape handler missing');
  assert.ok(appSrc.indexOf('closeDrawer()') !== -1, 'Escape must call closeDrawer');
  const close = appSrc.slice(appSrc.indexOf('function closeDrawer'), appSrc.indexOf('function focusElement'));
  assert.ok(close.indexOf('drawerClosed') !== -1, 'close must request opener focus');
  assert.ok(appSrc.indexOf('[data-action="toggle-evidence"]') !== -1, 'opener focus target missing');
});

check('normal close button returns focus to opener', function () {
  assert.ok(
    templatesSrc.indexOf('data-action="toggle-evidence"') !== -1,
    'close button must share the toggle action'
  );
  assert.ok(
    templatesSrc.indexOf('data-focus-key="drawer-close"') !== -1,
    'close button focus key missing'
  );
});

check('hidden drawer button cannot become roving-focus target', function () {
  const collect = appSrc.slice(appSrc.indexOf('function collectFocusables'), appSrc.indexOf('function syncDrawerAria'));
  assert.ok(
    collect.indexOf('store.evidenceOpen ? drawerButtons : viewButtons') !== -1,
    'drawer buttons only enter focusables while open'
  );
  assert.ok(
    collect.indexOf('drawerEl.querySelectorAll') !== -1,
    'drawer buttons collected from the drawer only'
  );
});

check('aria-modal true while open', function () {
  const drawerTag = indexHtml.slice(indexHtml.indexOf('id="evidence-drawer"'), indexHtml.indexOf('</section>'));
  assert.ok(drawerTag.indexOf('aria-modal="true"') !== -1, 'drawer must declare aria-modal');
  assert.ok(drawerTag.indexOf('role="dialog"') !== -1, 'drawer must declare role dialog');
});

check('aria-expanded false after close', function () {
  assert.ok(
    appSrc.indexOf("setAttribute('aria-expanded', String(store.evidenceOpen))") !== -1,
    'opener aria-expanded must mirror drawer state'
  );
  const close = appSrc.slice(appSrc.indexOf('function closeDrawer'), appSrc.indexOf('function focusElement'));
  assert.ok(close.indexOf('store.evidenceOpen = false;') !== -1, 'close must clear the open flag');
  assert.ok(close.indexOf('syncDrawerAria()') !== -1, 'close must resync aria-expanded');
});

if (failures > 0) {
  console.error(failures + ' focus scope failure(s)');
  process.exit(1);
}
console.log('focus scope ok');
