const { spawnSync } = require('node:child_process');

const candidates = process.platform === 'win32'
  ? [
      { command: 'python', prefix: [] },
      { command: 'py', prefix: ['-3'] },
    ]
  : [
      { command: 'python3', prefix: [] },
      { command: 'python', prefix: [] },
    ];

const unittestArgs = ['-m', 'unittest', 'discover', '-s', 'tests', '-v'];

for (const candidate of candidates) {
  const result = spawnSync(candidate.command, [...candidate.prefix, ...unittestArgs], {
    stdio: 'inherit',
  });

  if (!result.error) {
    process.exit(result.status ?? 1);
  }

  if (result.error.code !== 'ENOENT') {
    console.error(`Failed to launch ${candidate.command}:`, result.error.message);
    process.exit(1);
  }
}

console.error('No supported Python interpreter found (tried python/python3/py as appropriate).');
process.exit(1);
