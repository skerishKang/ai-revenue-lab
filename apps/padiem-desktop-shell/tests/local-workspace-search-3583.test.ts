/**
 * #3583 — LocalWorkspaceController.search integration tests.
 *
 * Uses real temp directories (mkdtemp) so the bounded walk, symlink skip,
 * depth cap and entry cap are exercised against actual fs behavior. No
 * network, no Electron runtime, no provider/model calls.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, symlink, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';

import {
  MAX_SEARCH_ENTRIES,
  MAX_SEARCH_RESULTS,
  MAX_TREE_DEPTH,
  LocalWorkspaceController,
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

test('#3583 search reports workspace_unavailable when the root vanishes', async () => {
  await withTempRoot(async (root) => {
    const controller = await controllerWithRoot(root);
    await rm(root, { recursive: true, force: true });
    const result = await controller.search({ query: 'anything' });
    assert.equal(result.ok, false);
    assert.equal(result.errorCode, 'workspace_unavailable');
  });
});
