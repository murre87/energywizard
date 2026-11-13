const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const source = fs.readFileSync('webdashboard/static/app.js', 'utf8');
let value = 'sensor.status_kompressor_43427';
const context = { document: { getElementById: () => ({ value }) }, esc: s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;') };
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function compressorPicker('), source.indexOf('async function runDiscovery(')), context);
const pump = { driver: 'ha_entities', entities: { outdoor_temp: 'sensor.bt1' } };
let html = context.compressorPicker({ heat_pump: pump, compressor_sensors: [{ entity: value, name: '<Status>', state: 'Kör' }] });
assert(html.includes('hp_compressor') && html.includes('Kör') && html.includes('&lt;Status>'));
const selected = context.selectedHeatPump(pump);
assert.equal(selected.entities.compressor, value);
assert.equal(selected.entities.outdoor_temp, 'sensor.bt1');
assert.equal(pump.entities.compressor, undefined); // preserve the discovery snapshot
html = context.compressorPicker({ heat_pump: selected });
assert(html.includes(' selected')); // configured but currently unavailable sensor survives
value = '';
assert.equal(context.selectedHeatPump(selected).entities.compressor, undefined);
assert.equal(context.compressorPicker({ heat_pump: { driver: 'generic_climate' } }), '');
assert(source.includes('sel.heat_pump = selectedHeatPump(_discovered.heat_pump)'));
assert(source.includes('"pm_second", "hp_compressor"'));
console.log('Compressor picker checks passed');
