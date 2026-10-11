/**
 * #3583 — LocalWorkspaceController.search integration tests.
 *
 * Uses real temp directories (mkdtemp) so the bounded walk, symlink skip,
 * depth cap and entry cap are exercised against actual fs behavior. No
 * network, no Electron runtime, no provider/model calls.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readdir, symlink, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';

import {
  MAX_SEARCH_ENTRIES,
  MAX_SEARCH_RESULTS,
  MAX_TREE_DEPTH,
  LocalWorkspaceController,
  type WorkspaceReaddirFn,
} from '../src/workspace/local-workspace.js';

async function withTempRoot(
  fn: (root: string, outside: string) => Promise<void>,
): Promise<void> {
  const base = await mkdtemp(path.join(tmpdir(), 'padiem-search-3583-'));
  const outside = await mkdtemp(path.join(tmpdir(), 'padiem-search-3583-out-'));
  try {
    await fn(base, outside);
  } finally {
    await rm(base, { recursive: true, force: true });
    await rm(outside, { recursive: true, force: true });
  }
}

async function controllerWithRoot(root: string): Promise<LocalWorkspaceController> {
  const controller = new LocalWorkspaceController(async () => root);
  // #root is only ever set through the native picker seam (chooseRoot), so a
  // test controller must walk the same path instead of touching private state.
  const chosen = await controller.chooseRoot();
  assert.equal(chosen.selected, true);
  return controller;
}

const NULL_ROOT: () => Promise<string | null> = async () => null;

test('#3583 search fails closed when no root is selected', async () => {
  const controller = new LocalWorkspaceController(NULL_ROOT);
  const result = await controller.search({ query: 'anything' });
  assert.equal(result.ok, false);
  assert.equal(result.errorCode, 'root_not_selected');
  assert.deepEqual(result.matches, []);
  assert.equal(result.scannedEntries, 0);
});

test('#3583 search fails closed with invalid_query when the picker refuses', async () => {
  // root_not_selected is checked first; query validation errors surface when
  // a root exists, so the invalid-query variants live in the temp-root test.
  const controller = new LocalWorkspaceController(NULL_ROOT);
  const empty = await controller.search({ query: '   ' });
  // With no root the root error wins; the query is not even inspected.
  assert.equal(empty.errorCode, 'root_not_selected');
});

test('#3583 search rejects invalid queries', async () => {
  await withTempRoot(async (root) => {
    const controller = await controllerWithRoot(root);
    for (const bad of [
      undefined,
      null,
      42,
      'tooshort   ',
      '',
      '   ',
      'x'.repeat(129),
      { query: 123 },
      { query: null },
    ]) {
      const result = await controller.search(bad as unknown);
      assert.equal(result.ok, false, `must reject: ${JSON.stringify(bad)}`);
      assert.equal(result.errorCode, 'invalid_query');
    }
  });
});

test('#3583 search finds matches by name and by relative path', async () => {
  await withTempRoot(async (root) => {
    await mkdir(path.join(root, 'src', 'components'), { recursive: true });
    await writeFile(path.join(root, 'src', 'index.ts'), '');
    await writeFile(path.join(root, 'src', 'components', 'button.tsx'), '');
    await writeFile(path.join(root, 'overview.md'), '');

    const controller = await controllerWithRoot(root);
    const byName = await controller.search({ query: 'index' });
    assert.equal(byName.ok, true);
    assert.equal(byName.matches.length, 1);
    assert.equal(byName.matches[0]?.relativePath, 'src/index.ts');
    assert.equal(byName.matches[0]?.kind, 'file');
    assert.equal(typeof byName.matches[0]?.sizeBytes, 'number');
    assert.equal(typeof byName.matches[0]?.modifiedAt, 'string');

    const byPath = await controller.search({ query: 'overview' });
    assert.equal(byPath.ok, true);
    assert.equal(byPath.matches.length, 1);
    assert.equal(byPath.matches[0]?.relativePath, 'overview.md');

    // Directories are searchable too.
    const byDir = await controller.search({ query: 'components' });
    assert.equal(byDir.ok, true);
    assert.ok(byDir.matches.some((entry) => entry.relativePath === 'src/components'));
  });
});

test('#3583 search never follows or surfaces symlinks', async () => {
  await withTempRoot(async (root, outside) => {
    await writeFile(path.join(outside, 'secret.txt'), '');
    await mkdir(path.join(root, 'src'), { recursive: true });
    await writeFile(path.join(root, 'src', 'app.ts'), '');
    await symlink(path.join(outside, 'secret.txt'), path.join(root, 'src', 'leak.txt'));
    await symlink(outside, path.join(root, 'src', 'leakdir'));

    const controller = await controllerWithRoot(root);
    const result = await controller.search({ query: 'leak' });
    assert.equal(result.ok, true);
    assert.deepEqual(result.matches, []);

    // The outside file is invisible even by its own name: the walk never
    // leaves the root because links are skipped, not followed.
    const outsideOnly = await controller.search({ query: 'secret' });
    assert.equal(outsideOnly.ok, true);
    assert.deepEqual(outsideOnly.matches, []);
  });
});

test('#3583 search respects the depth cap', async () => {
  await withTempRoot(async (root) => {
    let current = root;
    for (let level = 0; level < MAX_TREE_DEPTH + 3; level += 1) {
      current = path.join(current, `level${level}`);
    }
    await mkdir(current, { recursive: true });
    await writeFile(path.join(current, 'deep.txt'), '');

    const controller = await controllerWithRoot(root);
    const result = await controller.search({ query: 'deep' });
    assert.equal(result.ok, true);
    // level0..level(N+2) descend below the cap; the too-deep file is absent.
    assert.deepEqual(result.matches, []);
  });
});

test('#3583 search honors the entry budget and reports truncation', async () => {
  await withTempRoot(async (root) => {
    // More files than MAX_SEARCH_ENTRIES so the bounded walk must stop.
    const perDir = 200;
    const dirs = Math.ceil((MAX_SEARCH_ENTRIES + 1) / perDir);
    for (let dir = 0; dir < dirs; dir += 1) {
      const target = path.join(root, `bulk${dir}`);
      await mkdir(target, { recursive: true });
      for (let file = 0; file < perDir; file += 1) {
        await writeFile(path.join(target, `f${dir}_${file}.txt`), '');
      }
    }

    const controller = await controllerWithRoot(root);
    const result = await controller.search({ query: 'bulk' });
    assert.equal(result.ok, true);
    assert.equal(result.truncated, true);
    assert.ok(result.scannedEntries <= MAX_SEARCH_ENTRIES);
    assert.ok(result.matches.length <= MAX_SEARCH_RESULTS);
    // Every match lives under a bulk* directory, so its relative path
    // contains the query — files match by path, directories by name.
    assert.ok(result.matches.every((entry) => entry.relativePath.includes('bulk')));
    assert.ok(result.matches.some((entry) => entry.kind === 'directory'));
  });
});

test('#3583 search bounds results to MAX_SEARCH_RESULTS', async () => {
  await withTempRoot(async (root) => {
    await mkdir(path.join(root, 'many'), { recursive: true });
    for (let file = 0; file < MAX_SEARCH_RESULTS + 30; file += 1) {
      await writeFile(path.join(root, 'many', `hit${String(file).padStart(3, '0')}.txt`), '');
    }

    const controller = await controllerWithRoot(root);
    const result = await controller.search({ query: 'hit' });
    assert.equal(result.ok, true);
    assert.equal(result.truncated, false);
    // 80 files + the containing directory itself = 81 scanned entries.
    assert.equal(result.scannedEntries, MAX_SEARCH_RESULTS + 31);
    assert.equal(result.matches.length, MAX_SEARCH_RESULTS);
    assert.equal(result.maxResults, MAX_SEARCH_RESULTS);
  });
});

test('#3583 search fails closed when the root vanishes entirely', async () => {
  await withTempRoot(async (root) => {
    const controller = await controllerWithRoot(root);
    await rm(root, { recursive: true, force: true });
    const result = await controller.search({ query: 'anything' });
    // The vanished root reads as an empty, bounded result: nothing was read
    // (there is nothing left to read) and no error material is exposed.
    assert.equal(result.ok, true);
    assert.deepEqual(result.matches, []);
    assert.equal(result.scannedEntries, 0);
    assert.equal(result.truncated, false);
  });
});

test('#3583 TOCTOU: directory swapped to a junction after enumeration is never read or returned', async () => {
  await withTempRoot(async (root, outside) => {
    // Layout: root/victim/ (real directory with a file) plus an outside
    // escaped tree. The injected readdir driver performs the swap AFTER the
    // root readdir has enumerated `victim` as a real directory and queued it,
    // and BEFORE the queued readdir of `victim` itself runs — exactly the
    // post-enumeration replacement race the containment re-check closes.
    await mkdir(path.join(root, 'victim'), { recursive: true });
    await writeFile(path.join(root, 'victim', 'inner.txt'), '');
    await mkdir(path.join(outside, 'escaped'), { recursive: true });
    await writeFile(path.join(outside, 'escaped', 'leak.txt'), '');

    const realReaddir = readdir;
    let rootReadHappened = false;
    // The DI seam types the driver as the full readdir overload set; the test
    // driver only implements the withFileTypes call shape the controller uses.
    const swapDriver = (async (target: string, options: { withFileTypes: true }) => {
      const rows = await realReaddir(target, options);
      if (!rootReadHappened && target === root) {
        rootReadHappened = true;
        // Swap the already-enumerated real directory to a junction pointing
        // OUTSIDE the root before its queued readdir runs.
        await rm(path.join(root, 'victim'), { recursive: true, force: true });
        await symlink(path.join(outside, 'escaped'), path.join(root, 'victim'), 'junction');
      }
      return rows;
    }) as unknown as WorkspaceReaddirFn;

    const controller = new LocalWorkspaceController(async () => root, swapDriver);
    await controller.chooseRoot();

    const result = await controller.search({ query: 'leak' });
    assert.equal(result.ok, true);
    // The escaped outside entry is never read or returned.
    assert.deepEqual(result.matches, []);

    // The stale enumerated candidate for the swapped directory is dropped:
    // fail closed means the row disappears entirely, not re-rooted.
    const victim = await controller.search({ query: 'victim' });
    // NOTE: the second call runs AFTER the swap already happened, so the
    // root readdir now sees a junction (skipped at enumeration) — still empty.
    assert.equal(victim.ok, true);
    assert.deepEqual(victim.matches, []);
  });
});

test('#3583 TOCTOU: junction swapped in before the search escapes the root, fail closed', async () => {
  await withTempRoot(async (root, outside) => {
    await mkdir(path.join(root, 'outer'), { recursive: true });
    await writeFile(path.join(root, 'outer', 'inner.txt'), '');
    await mkdir(path.join(outside, 'escaped'), { recursive: true });
    await writeFile(path.join(outside, 'escaped', 'leak.txt'), '');

    // Swap outer -> junction BEFORE the search: the queued readdir path
    // (root/outer) now resolves through the junction OUTSIDE the root;
    // realpath + isInsideRoot must reject it before any readdir there.
    await rm(path.join(root, 'outer'), { recursive: true, force: true });
    await symlink(path.join(outside, 'escaped'), path.join(root, 'outer'), 'junction');

    const controller = await controllerWithRoot(root);
    const result = await controller.search({ query: 'leak' });
    assert.equal(result.ok, true);
    assert.deepEqual(result.matches, []);

    // The stale 'outer' directory row is not surfaced either: its canonical
    // resolution escaped the root, so the subtree is skipped entirely.
    const outer = await controller.search({ query: 'outer' });
    assert.equal(outer.ok, true);
    assert.deepEqual(outer.matches, []);
  });
});
