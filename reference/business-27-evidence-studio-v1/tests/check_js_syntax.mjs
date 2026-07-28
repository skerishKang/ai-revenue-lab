import {readFileSync} from 'node:fs';
import {Script} from 'node:vm';
const source=readFileSync(new URL('../scripts/app.js',import.meta.url),'utf8');
new Script(source);
console.log(JSON.stringify({status:'pass',file:'scripts/app.js'}));
