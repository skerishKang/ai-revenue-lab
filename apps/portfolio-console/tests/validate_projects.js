const vm = require('vm');
const fs = require('fs');
const path = require('path');

const rootDir = path.resolve(__dirname, '..');

const ALLOWED_STAGES = ['live', 'demo', 'build', 'review', 'planned'];
const ALLOWED_MODES = ['active-development', 'needs-improvement', 'planning'];
const ALLOWED_MILESTONE_STATUS = ['defined', 'undefined'];
const EXPECTED_IDS = [
  'portfolio-console',
  'lovebud',
  'personal-edition',
  'living-travel',
  'living-fiction',
  'living-learning',
  'personal-video-archive',
  'lovetree-3',
  'korean-ai-platform',
  'ai-finder-bukgu',
  'love-matchmaking',
  'ai-finder-namgu',
  'ai-finder-seogu'
];

let errors = [];

function assert(cond, msg) {
  if (!cond) errors.push(msg);
}

function loadProjects() {
  const filePath = path.join(rootDir, 'projects.js');
  const source = fs.readFileSync(filePath, 'utf8');
  const wrapped = source + '\nglobalThis.__projects = window.ARL_PROJECTS;';
  const script = new vm.Script(wrapped, { filename: 'projects.js' });
  const ctx = vm.createContext({ window: {}, globalThis: {}, console, Array, Object, String, Number, Boolean, Math, JSON, Map, Set, RegExp, Date, Error, Symbol });
  script.runInContext(ctx);
  return ctx.globalThis.__projects;
}

function validate() {
  const projects = loadProjects();

  assert(projects.length === 13, `Expected 13 projects, got ${projects.length}`);

  const ids = projects.map(p => p.id);
  for (const expected of EXPECTED_IDS) {
    assert(ids.includes(expected), `Missing expected project id: ${expected}`);
  }
  const idSet = new Set(ids);
  assert(idSet.size === 13, 'Duplicate project IDs');

  let totalTasks = 0;
  let totalDone = 0;
  let definedCount = 0;

  for (const p of projects) {
    assert(typeof p.id === 'string', `${p.id}: id must be string`);
    assert(typeof p.name === 'string', `${p.id}: name must be string`);
    assert(typeof p.koreanName === 'string', `${p.id}: koreanName must be string`);
    assert(typeof p.purpose === 'string', `${p.id}: purpose must be string`);
    assert(typeof p.stage === 'string', `${p.id}: stage must be string`);
    assert(ALLOWED_STAGES.includes(p.stage), `${p.id}: invalid stage "${p.stage}"`);
    assert(typeof p.developmentMode === 'string', `${p.id}: developmentMode must be string`);
    assert(ALLOWED_MODES.includes(p.developmentMode), `${p.id}: invalid developmentMode "${p.developmentMode}"`);
    assert(typeof p.progressBasis === 'string', `${p.id}: progressBasis must be string`);
    assert(p.milestoneStatus === 'defined' || p.milestoneStatus === 'undefined', `${p.id}: invalid milestoneStatus "${p.milestoneStatus}"`);
    assert(Array.isArray(p.milestoneTasks), `${p.id}: milestoneTasks must be array`);
    assert(Array.isArray(p.currentMilestone), `${p.id}: currentMilestone must be array`);
    assert(Array.isArray(p.blockers), `${p.id}: blockers must be array`);
    assert(Array.isArray(p.futureRoadmap), `${p.id}: futureRoadmap must be array`);
    assert(typeof p.lastVerified === 'string', `${p.id}: lastVerified must be string`);

    const taskIds = new Set();
    for (const task of p.milestoneTasks) {
      assert(typeof task.id === 'string', `${p.id}/${task.id}: task id must be string`);
      assert(typeof task.name === 'string', `${p.id}/${task.id}: task name must be string`);
      assert(typeof task.done === 'boolean', `${p.id}/${task.id}: done must be boolean`);
      assert(typeof task.evidence === 'string', `${p.id}/${task.id}: evidence must be string`);
      if (task.done) {
        assert(task.evidence.length > 0, `${p.id}/${task.id}: done task must have non-empty evidence`);
      }
      assert(!taskIds.has(task.id), `${p.id}: duplicate task id "${task.id}"`);
      taskIds.add(task.id);
    }

    totalTasks += p.milestoneTasks.length;
    totalDone += p.milestoneTasks.filter(t => t.done).length;

    if (p.milestoneStatus === 'defined') {
      assert(p.milestoneTasks.length > 0, `${p.id}: defined milestone must have at least one task`);
      definedCount++;
    } else {
      assert(p.milestoneTasks.length === 0, `${p.id}: undefined milestone must have zero tasks`);
    }

    assert(p.repositoryLabel !== undefined, `${p.id}: repositoryLabel must exist`);
    assert(p.workspace !== undefined, `${p.id}: workspace must exist`);
    assert(p.pageUrl !== undefined, `${p.id}: pageUrl must exist (can be null)`);
    assert(p.progressNote !== undefined, `${p.id}: progressNote must exist`);
    assert(p.currentWork !== undefined, `${p.id}: currentWork must exist`);
    assert(p.nextAction !== undefined, `${p.id}: nextAction must exist`);

    if (p.pageUrl) {
      assert(p.pageUrl.startsWith('https://'), `${p.id}: pageUrl must use https`);
    }

    if (p.workspace && p.workspace !== '확인 필요' && p.workspace !== '—') {
      assert(!p.workspace.match(/^[A-Z]:\\/), `${p.id}: no Windows absolute paths in workspace`);
    }
  }

  if (errors.length > 0) {
    console.error(`VALIDATION FAILED: ${errors.length} error(s)`);
    errors.forEach(e => console.error(`  - ${e}`));
    process.exit(1);
  }

  const progressPct = totalTasks > 0 ? Math.round(totalDone / totalTasks * 100) : 0;
  console.log('=== Node vm Structured Validation ===');
  console.log(`Projects: ${projects.length} (defined: ${definedCount}, undefined: ${projects.length - definedCount})`);
  console.log(`Tasks: ${totalTasks} (done: ${totalDone}, remaining: ${totalTasks - totalDone})`);
  console.log(`Progress: ${totalDone}/${totalTasks} = ${progressPct}% (remaining: ${100 - progressPct}%)`);
  console.log('Errors: 0');
  console.log('All validations passed');
}

validate();
