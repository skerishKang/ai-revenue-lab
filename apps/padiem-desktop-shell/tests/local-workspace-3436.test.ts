import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, mkdtemp, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';

import {
  LocalWorkspaceController,
  MAX_WORKSPACE_ENTRIES,
} from '../src/workspace/local-workspace.js';

async function makeFixture(): Promise<string> {
  const root = await mkdtemp(path.join(tmpdir(), 'padiem-workspace-'));
  await mkdir(path.join(root, 'src'));
  await writeFile(path.join(root, 'README.md'), 'TOP SECRET CONTENT');
  await writeFile(path.join(root, 'src', 'index.ts'), 'export const value = 1;');
  return root;
}

test('#3436 picker cancellation and invalid selections fail closed', async (t) => {
  const root = await makeFixture();
  const notDirectory = path.join(root, 'README.md');
  t.after(async () => rm(root, { recursive: true, force: true }));

  const cancelled = new LocalWorkspaceController(async () => null);
  assert.deepEqual(await cancelled.chooseRoot(), {
    selected: false,
    rootName: null,
    rootPath: null,
    reason: 'cancelled',
  });

  const invalid = new LocalWorkspaceController(async () => notDirectory);
  assert.deepEqual(await invalid.chooseRoot(), {
    selected: false,
    rootName: null,
    rootPath: null,
    reason: 'invalid_selection',
  });
});

test('#3436 native-selected root projects bounded names, not file contents', async (t) => {
  const root = await makeFixture();
  t.after(async () => rm(root, { recursive: true, force: true }));

  const workspace = new LocalWorkspaceController(async () => root);
  const selected = await workspace.chooseRoot();
  assert.equal(selected.selected, true);
  assert.equal(selected.rootName, path.basename(root));
  assert.equal(selected.rootPath, path.resolve(root));

  const listing = await workspace.listDirectory({ relativePath: '' });
  assert.equal(listing.ok, true);
  assert.equal(listing.directory, '');
  assert.deepEqual(
    listing.entries.map((entry) => [entry.name, entry.kind]),
    [
      ['src', 'directory'],
      ['README.md', 'file'],
    ],
  );
  assert.doesNotMatch(JSON.stringify(listing), /TOP SECRET CONTENT/);
});

test('#3436 directory navigation stays relative to the selected root', async (t) => {
  const root = await makeFixture();
  t.after(async () => rm(root, { recursive: true, force: true }));

  const workspace = new LocalWorkspaceController(async () => root);
  await workspace.chooseRoot();

  const nested = await workspace.listDirectory({ relativePath: 'src' });
  assert.equal(nested.ok, true);
  assert.equal(nested.directory, 'src');
  assert.deepEqual(nested.entries.map((entry) => entry.relativePath), ['src/index.ts']);

  for (const hostile of [
    '.',
    './src',
    '..',
    '../outside',
    'src/../outside',
    'src/./child',
    'src//child',
    '/absolute',
    'C:/Windows',
    '\\\\server\\share',
    'src\\child',
    'src\0child',
  ]) {
    const rejected = await workspace.listDirectory({ relativePath: hostile });
    assert.equal(rejected.ok, false, hostile);
    assert.equal(rejected.errorCode, 'invalid_relative_path', hostile);
  }

  for (const hostileRequest of ['src', 1, true, []]) {
    const rejected = await workspace.listDirectory(hostileRequest);
    assert.equal(rejected.ok, false);
    assert.equal(rejected.errorCode, 'invalid_relative_path');
  }
});

test('#3436 links are classified but can never become navigable workspace directories', async (t) => {
  const root = await makeFixture();
  const outside = await mkdtemp(path.join(tmpdir(), 'padiem-workspace-outside-'));
  const linkPath = path.join(root, 'linked-outside');
  t.after(async () => {
    await rm(root, { recursive: true, force: true });
    await rm(outside, { recursive: true, force: true });
  });
  await writeFile(path.join(outside, 'outside-secret.txt'), 'MUST NOT PROJECT');
  await symlink(outside, linkPath, process.platform === 'win32' ? 'junction' : 'dir');

  const workspace = new LocalWorkspaceController(async () => root);
  await workspace.chooseRoot();

  const rootListing = await workspace.listDirectory({ relativePath: '' });
  const link = rootListing.entries.find((entry) => entry.name === 'linked-outside');
  assert.equal(link?.kind, 'link');

  const rejected = await workspace.listDirectory({ relativePath: 'linked-outside' });
  assert.equal(rejected.ok, false);
  assert.equal(rejected.errorCode, 'invalid_relative_path');
  assert.equal(rejected.entries.length, 0);
  assert.doesNotMatch(JSON.stringify(rejected), /outside-secret/);
});

test('#3436 renderer-shaped caller data cannot replace the main-owned root', async (t) => {
  const root = await makeFixture();
  t.after(async () => rm(root, { recursive: true, force: true }));

  const workspace = new LocalWorkspaceController(async () => root);
  await workspace.chooseRoot();

  const listing = await workspace.listDirectory({
    relativePath: '',
    rootPath: 'C:/',
    absolutePath: 'C:/Windows',
  } as unknown);
  assert.equal(listing.ok, true);
  assert.equal(listing.root.rootPath, path.resolve(root));
  assert.equal(listing.entries.some((entry) => entry.name === 'README.md'), true);
});

test('#3436 no root and cleared root fail closed without filesystem projection', async (t) => {
  const root = await makeFixture();
  t.after(async () => rm(root, { recursive: true, force: true }));

  const workspace = new LocalWorkspaceController(async () => root);
  const before = await workspace.listDirectory({ relativePath: '' });
  assert.equal(before.ok, false);
  assert.equal(before.errorCode, 'root_not_selected');

  await workspace.chooseRoot();
  const cleared = workspace.clearRoot();
  assert.equal(cleared.selected, false);
  const after = await workspace.listDirectory({ relativePath: '' });
  assert.equal(after.ok, false);
  assert.equal(after.errorCode, 'root_not_selected');
});

test('#3436 ordering is deterministic: directories first, then code-point name order', async (t) => {
  const root = await mkdtemp(path.join(tmpdir(), 'padiem-workspace-sort-'));
  t.after(async () => rm(root, { recursive: true, force: true }));
  await mkdir(path.join(root, 'b-dir'));
  await mkdir(path.join(root, 'A-dir'));
  await writeFile(path.join(root, 'z.txt'), 'z');
  await writeFile(path.join(root, 'B.txt'), 'b');

  const workspace = new LocalWorkspaceController(async () => root);
  await workspace.chooseRoot();
  const listing = await workspace.listDirectory({ relativePath: '' });

  assert.deepEqual(
    listing.entries.map((entry) => [entry.name, entry.kind]),
    [
      ['A-dir', 'directory'],
      ['b-dir', 'directory'],
      ['B.txt', 'file'],
      ['z.txt', 'file'],
    ],
  );
});

test('#3436 listing is capped even for a large selected directory', async (t) => {
  const root = await mkdtemp(path.join(tmpdir(), 'padiem-workspace-many-'));
  t.after(async () => rm(root, { recursive: true, force: true }));
  await Promise.all(
    Array.from({ length: MAX_WORKSPACE_ENTRIES + 5 }, (_, index) =>
      writeFile(path.join(root, `f-${String(index).padStart(3, '0')}.txt`), 'x'),
    ),
  );

  const workspace = new LocalWorkspaceController(async () => root);
  await workspace.chooseRoot();
  const listing = await workspace.listDirectory({ relativePath: '' });

  assert.equal(listing.ok, true);
  assert.equal(listing.entries.length, MAX_WORKSPACE_ENTRIES);
  assert.equal(listing.truncated, true);
  assert.equal(listing.maxEntries, MAX_WORKSPACE_ENTRIES);
});
