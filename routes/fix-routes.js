const fs = require('fs');
const path = require('path');

const file = path.join(__dirname, 'routes', 'certificados.js');
let content = fs.readFileSync(file, 'utf8');

// Find where auditoria handler is
const auditStart = content.indexOf("router.get('/:id/auditoria'");
if (auditStart === -1) {
  console.log('ERROR: Could not find auditoria handler');
  process.exit(1);
}

// Find the closing }); after auditoria
let braceCount = 0;
let foundStart = false;
let auditEnd = -1;

for (let i = auditStart; i < content.length; i++) {
  if (!foundStart && content[i] === '{') {
    foundStart = true;
    braceCount = 1;
    continue;
  }
  if (foundStart) {
    if (content[i] === '{') braceCount++;
    if (content[i] === '}') braceCount--;
    if (braceCount === 0) {
      // Find the ;
      auditEnd = content.indexOf(';', i) + 1;
      break;
    }
  }
}

if (auditEnd === -1) {
  console.log('ERROR: Could not find closing of auditoria handler');
  process.exit(1);
}

console.log('Auditoria handler ends at position:', auditEnd);

// Keep everything up to and including auditoria handler + module.exports
const kept = content.substring(0, auditEnd);
const newContent = kept + '\n\nmodule.exports = router;\n';

// Write back
fs.writeFileSync(file, newContent, 'utf8');
console.log('✓ File fixed! Removed duplicate stats endpoints.');
console.log('File size before:', content.length);
console.log('File size after:', newContent.length);
console.log('Removed:', content.length - newContent.length, 'bytes');
