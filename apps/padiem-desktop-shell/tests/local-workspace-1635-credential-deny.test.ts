/**
 * #1635 — system/credential directories are deny-by-default in the Desktop
 * local resource layer (LocalWorkspaceController): listing, search and root
 * selection all consult the same shared segment policy.
 *
 * Every credential-shaped directory here is a synthetic temp fixture holding
 * dummy bytes. No test reads a real user HOME, ~/.ssh or ~/.aws.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readdir, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';

import {
  LocalWorkspaceController,
  SYSTEM_CREDENTIAL_DIRECTORY_SEGMENTS,
  isSystemCredentialRelativePath,
  isSystemCredentialSegment,
  type WorkspaceReaddirFn,
} from '../src/workspace/local-workspace.js';

const DENIED = [
  '.ssh',
  '.aws',
  '.gnupg',
  '.azure',
  '.kube',
  '.docker',
  '.mozilla',
] as const;

/** Ordinary entries that must stay visible: hidden is not the same as credential. */
const ORDINARY_VISIBLE = ['normal.txt', '.hidden', '.npmrc', '.git', 'my.ssh.backup', 'work'];

async function withTempRoot(
  fn: (root: string) => Promise<void>,
): Promise<void> {
  const root = await mkdtemp(path.join(tmpdir(), 'padiem-1635-deny-'));
  try {
    await fn(root);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

async function controllerAt(root: string): Promise<LocalWorkspaceController> {
  const controller = new LocalWorkspaceController(async () => root);
  const chosen = await controller.chooseRoot();
  assert.equal(chosen.selected, true, 'an ordinary workspace root stays selectable');
  return controller;
}

async function buildSyntheticWorkspace(root: string): Promise<void> {
  for (const name of DENIED) {
    await mkdir(path.join(root, name), { recursive: true });
    await writeFile(path.join(root, name, 'id_dummy'), 'synthetic fixture', 'utf8');
  }
  await writeFile(path.join(root, 'normal.txt'), 'normal', 'utf8');
  await writeFile(path.join(root, '.hidden'), 'ordinary hidden file', 'utf8');
  await writeFile(path.join(root, '.npmrc'), 'ordinary dotfile', 'utf8');
  await mkdir(path.join(root, '.git'), { recursive: true });
  await writeFile(path.join(root, '.git', 'config'), 'repository bookkeeping', 'utf8');
  // Whole-segment matching: a name that merely CONTAINS the token is not a
  // credential directory and must stay browsable.
  await mkdir(path.join(root, 'my.ssh.backup'), { recursive: true });
  await writeFile(path.join(root, 'my.ssh.backup', 'notes.txt'), 'notes', 'utf8');
  // A credential directory nested under an ordinary one.
  await mkdir(path.join(root, 'work', '.kube'), { recursive: true });
  await writeFile(path.join(root, 'work', '.kube', 'config'), 'synthetic fixture', 'utf8');
  await writeFile(path.join(root, 'work', 'id_dummy.txt'), 'ordinary lookalike', 'utf8');
}

function relativeSegments(relativePath: string): string[] {
  return relativePath.toLowerCase().split(/[\\/]+/);
}

function assertNoCredentialSegment(entries: readonly { relativePath: string }[]): void {
  for (const entry of entries) {
    const segments = relativeSegments(entry.relativePath);
    for (const denied of DENIED) {
      assert.ok(
        !segments.includes(denied),
        `credential directory leaked into a projection: ${entry.relativePath}`,
      );
    }
  }
}

test('#1635 the deny set is credential-scoped and matches whole segments', () => {
  for (const name of DENIED) {
    assert.ok(SYSTEM_CREDENTIAL_DIRECTORY_SEGMENTS.has(name), name);
  }
  // Deliberately excluded: repository bookkeeping, generic hidden entries and
  // OS application directories. This is not a blanket hidden-file policy.
  for (const kept of ['.git', '.npmrc', '.hidden', '.DS_Store', 'AppData', '.config']) {
    assert.equal(SYSTEM_CREDENTIAL_DIRECTORY_SEGMENTS.has(kept), false, kept);
  }
  assert.equal(isSystemCredentialSegment('.SSH'), true);
  assert.equal(isSystemCredentialSegment('my.ssh.backup'), false);
  assert.equal(isSystemCredentialSegment('.sshbackup'), false);
  assert.equal(isSystemCredentialRelativePath('work/holder/.kube/config'), true);
  assert.equal(isSystemCredentialRelativePath('work/my.kube.backup/config'), false);
});

test('#1635 root listing never surfaces credential directories but keeps ordinary entries', async () => {
  await withTempRoot(async (root) => {
    await buildSyntheticWorkspace(root);
    const controller = await controllerAt(root);

    const listing = await controller.listDirectory({ relativePath: '' });
    assert.equal(listing.ok, true);
    const names = listing.entries.map((entry) => entry.name);
    for (const denied of DENIED) {
      assert.ok(!names.includes(denied), `must not surface: ${denied}`);
    }
    for (const kept of ORDINARY_VISIBLE) {
      assert.ok(names.includes(kept), `must stay visible: ${kept}`);
    }
    assertNoCredentialSegment(listing.entries);
  });
});

test('#1635 listing into or under a credential directory is refused with path_denied', async () => {
  await withTempRoot(async (root) => {
    await buildSyntheticWorkspace(root);
    const controller = await controllerAt(root);

    for (const target of ['.ssh', '.aws', 'work/.kube', 'work/.azure/config']) {
      const refused = await controller.listDirectory({ relativePath: target });
      assert.equal(refused.ok, false, target);
      assert.equal(refused.errorCode, 'path_denied', target);
      assert.equal(refused.entries.length, 0, target);
      assert.doesNotMatch(JSON.stringify(refused), /id_dummy/, target);
    }

    // The nested credential directory is invisible from its ordinary parent,
    // so the renderer cannot even navigate to it.
    const work = await controller.listDirectory({ relativePath: 'work' });
    assert.equal(work.ok, true);
    const workNames = work.entries.map((entry) => entry.name);
    assert.ok(!workNames.includes('.kube'));
    assert.ok(workNames.includes('id_dummy.txt'));
  });
});

test('#1635 a near-miss name that contains a credential token stays browsable', async () => {
  await withTempRoot(async (root) => {
    await buildSyntheticWorkspace(root);
    const controller = await controllerAt(root);

    const listing = await controller.listDirectory({ relativePath: 'my.ssh.backup' });
    assert.equal(listing.ok, true);
    assert.deepEqual(
      listing.entries.map((entry) => entry.relativePath),
      ['my.ssh.backup/notes.txt'],
    );
  });
});

test('#1635 search shares the deny policy: credential trees are never walked or returned', async () => {
  await withTempRoot(async (root) => {
    await buildSyntheticWorkspace(root);
    const controller = await controllerAt(root);

    for (const denied of DENIED) {
      const byDirName = await controller.search({ query: denied });
      assert.equal(byDirName.ok, true, denied);
      assert.ok(
        !byDirName.matches.some(
          (match) => match.relativePath === denied || relativeSegments(match.relativePath).includes(denied),
        ),
        `search must not surface: ${denied}`,
      );
    }

    // Dummy key/credential files live only inside credential directories.
    const byKeyName = await controller.search({ query: 'id_dummy' });
    assert.equal(byKeyName.ok, true);
    assert.deepEqual(
      byKeyName.matches.map((match) => match.relativePath),
      ['work/id_dummy.txt'],
    );
    const byNestedName = await controller.search({ query: 'kube' });
    assert.equal(byNestedName.ok, true);
    assertNoCredentialSegment(byNestedName.matches);
    assert.ok(!byNestedName.matches.some((match) => match.relativePath === 'work/.kube'));

    // Ordinary hidden, repository and dotfile entries stay searchable: the
    // policy is credential-scoped, not a hidden-entry policy.
    for (const [query, expected] of [
      ['normal', 'normal.txt'],
      ['hidden', '.hidden'],
      ['npmrc', '.npmrc'],
      ['git', '.git'],
      ['config', '.git/config'],
    ] as const) {
      const found = await controller.search({ query });
      assert.equal(found.ok, true, query);
      assert.ok(
        found.matches.some((match) => match.relativePath === expected),
        `${query} must still find ${expected}`,
      );
    }
    assertNoCredentialSegment(
      (await controller.search({ query: 'dummy' })).matches,
    );
  });
});

test('#1635 the segment match is case-insensitive', async () => {
  await withTempRoot(async (root) => {
    await mkdir(path.join(root, 'case', '.SSH'), { recursive: true });
    await writeFile(path.join(root, 'case', '.SSH', 'id_dummy'), 'synthetic fixture', 'utf8');
    await mkdir(path.join(root, 'case', '.AWS'), { recursive: true });
    await writeFile(path.join(root, 'case', '.AWS', 'keys'), 'synthetic fixture', 'utf8');
    await writeFile(path.join(root, 'normal.txt'), 'normal', 'utf8');

    const controller = await controllerAt(root);

    const upper = await controller.listDirectory({ relativePath: '.SSH' });
    assert.equal(upper.ok, false);
    assert.equal(upper.errorCode, 'path_denied');
    const nested = await controller.listDirectory({ relativePath: 'case/.AWS/keys' });
    assert.equal(nested.ok, false);
    assert.equal(nested.errorCode, 'path_denied');

    const caseDir = await controller.listDirectory({ relativePath: 'case' });
    assert.equal(caseDir.ok, true);
    assert.deepEqual(caseDir.entries.map((entry) => entry.name), []);

    for (const query of ['SSH', 'ssh', 'AWS', 'aws', 'id_dummy', 'keys']) {
      const found = await controller.search({ query });
      assert.equal(found.ok, true, query);
      assert.deepEqual(found.matches, [], `query must find nothing: ${query}`);
    }

    const control = await controller.search({ query: 'normal' });
    assert.deepEqual(
      control.matches.map((match) => match.relativePath),
      ['normal.txt'],
    );
  });
});

test('#1635 a credential directory can never become the workspace root', async () => {
  await withTempRoot(async (root) => {
    await buildSyntheticWorkspace(root);

    for (const denied of [...DENIED, path.join('.ssh', 'keys')]) {
      const controller = new LocalWorkspaceController(async () => path.join(root, denied));
      const chosen = await controller.chooseRoot();
      assert.equal(chosen.selected, false, denied);
      assert.equal(chosen.reason, 'invalid_selection', denied);
      assert.equal(chosen.rootPath, null, denied);
      // Refusing the selection must not establish any authority at all.
      const listing = await controller.listDirectory({ relativePath: '' });
      assert.equal(listing.errorCode, 'root_not_selected', denied);
      const search = await controller.search({ query: 'id_dummy' });
      assert.equal(search.errorCode, 'root_not_selected', denied);
    }
  });
});

test('#1635 a refused root selection keeps the previously granted authority', async () => {
  await withTempRoot(async (root) => {
    await buildSyntheticWorkspace(root);
    let picked = root;
    const controller = new LocalWorkspaceController(async () => picked);
    const chosen = await controller.chooseRoot();
    assert.equal(chosen.selected, true);

    picked = path.join(root, '.ssh');
    const refused = await controller.chooseRoot();
    // The response reports the CURRENT authority with the refusal reason: the
    // denied pick neither grants nor clobbers a root.
    assert.equal(refused.reason, 'invalid_selection');
    assert.equal(refused.selected, true);
    assert.equal(refused.rootPath, chosen.rootPath);
    assert.equal(refused.rootName, chosen.rootName);

    const listing = await controller.listDirectory({ relativePath: '' });
    assert.equal(listing.ok, true);
    assertNoCredentialSegment(listing.entries);
  });
});

test('#1635 a root that canonicalizes into a credential directory is refused', async () => {
  await withTempRoot(async (root) => {
    await mkdir(path.join(root, 'holder', '.ssh'), { recursive: true });
    await writeFile(path.join(root, 'holder', '.ssh', 'id_dummy'), 'synthetic fixture', 'utf8');
    await symlink(
      path.join(root, 'holder', '.ssh'),
      path.join(root, 'link'),
      process.platform === 'win32' ? 'junction' : 'dir',
    );

    const controller = new LocalWorkspaceController(async () => path.join(root, 'link'));
    const chosen = await controller.chooseRoot();
    assert.equal(chosen.selected, false);
    assert.equal(chosen.reason, 'invalid_selection');
    const listing = await controller.listDirectory({ relativePath: '' });
    assert.equal(listing.errorCode, 'root_not_selected');
  });
});

test('#1635 TOCTOU: a directory swapped into credential shape after enumeration is not read', async () => {
  await withTempRoot(async (root) => {
    await mkdir(path.join(root, 'holder', '.ssh'), { recursive: true });
    await writeFile(path.join(root, 'holder', '.ssh', 'id_dummy'), 'synthetic fixture', 'utf8');
    await mkdir(path.join(root, 'victim'), { recursive: true });
    await writeFile(path.join(root, 'victim', 'inner.txt'), 'inner', 'utf8');
    await writeFile(path.join(root, 'normal.txt'), 'normal', 'utf8');

    const realReaddir = readdir;
    let swapped = false;
    // The driver swaps the already-enumerated real directory into a link whose
    // canonical target is a credential directory INSIDE the root, so root
    // containment alone cannot catch it — only the credential re-check can.
    const swapDriver = (async (target: string, options: { withFileTypes: true }) => {
      const rows = await realReaddir(target, options);
      if (!swapped) {
        swapped = true;
        await rm(path.join(root, 'victim'), { recursive: true, force: true });
        await symlink(
          path.join(root, 'holder', '.ssh'),
          path.join(root, 'victim'),
          process.platform === 'win32' ? 'junction' : 'dir',
        );
      }
      return rows;
    }) as unknown as WorkspaceReaddirFn;

    const controller = new LocalWorkspaceController(async () => root, swapDriver);
    const chosen = await controller.chooseRoot();
    assert.equal(chosen.selected, true);

    const leaked = await controller.search({ query: 'id_dummy' });
    assert.equal(leaked.ok, true);
    assert.deepEqual(leaked.matches, []);
    assertNoCredentialSegment(leaked.matches);

    // The stale enumerated candidate disappears instead of being re-rooted.
    const victim = await controller.search({ query: 'victim' });
    assert.deepEqual(victim.matches, []);

    // The walk is not broken: sibling trees are still scanned.
    const control = await controller.search({ query: 'normal' });
    assert.deepEqual(
      control.matches.map((match) => match.relativePath),
      ['normal.txt'],
    );
    const holder = await controller.search({ query: 'holder' });
    assert.ok(holder.matches.some((match) => match.relativePath === 'holder'));
  });
});

test('#1635 listing a link that resolves into a credential directory stays fail-closed', async () => {
  await withTempRoot(async (root) => {
    await mkdir(path.join(root, 'holder', '.ssh'), { recursive: true });
    await writeFile(path.join(root, 'holder', '.ssh', 'id_dummy'), 'synthetic fixture', 'utf8');
    await symlink(
      path.join(root, 'holder', '.ssh'),
      path.join(root, 'victim'),
      process.platform === 'win32' ? 'junction' : 'dir',
    );
    await writeFile(path.join(root, 'normal.txt'), 'normal', 'utf8');

    const controller = await controllerAt(root);

    const refused = await controller.listDirectory({ relativePath: 'victim' });
    assert.equal(refused.ok, false);
    // Pre-existing #3436 posture: a link segment is refused before any read, so
    // the credential re-check is defence-in-depth behind it. Either refusal is
    // fail-closed; nothing inside the credential directory may be projected.
    assert.equal(refused.errorCode, 'invalid_relative_path');
    assert.equal(refused.entries.length, 0);
    assert.doesNotMatch(JSON.stringify(refused), /id_dummy/);

    const listing = await controller.listDirectory({ relativePath: '' });
    const victim = listing.entries.find((entry) => entry.name === 'victim');
    // Pre-existing #3436 posture: a link stays visible as a non-navigable
    // 'link' row. It never becomes a directory the renderer can walk into.
    assert.equal(victim?.kind, 'link');
    // The credential directory it points at is never surfaced as a row either.
    const holder = await controller.listDirectory({ relativePath: 'holder' });
    assert.equal(holder.ok, true);
    assert.deepEqual(holder.entries.map((entry) => entry.name), []);
  });
});
