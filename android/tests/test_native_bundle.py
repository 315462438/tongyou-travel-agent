"""Validate the Android-only fallback routes against the actual Home source with Node."""
import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class NativeBundleTests(unittest.TestCase):
    def test_adapter_routes_and_failure_on_source_drift(self):
        subprocess.run(['node', '--input-type=module', '-e', r'''
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import config from './android/scripts/vite-native.mjs';
const transform = config.plugins[0].transform;
const source = readFileSync('./frontend/src/pages/Home.tsx', 'utf8');
const result = transform(source, '/src/pages/Home.tsx');
assert.ok(result.includes('isAndroidApp() || !target'));
assert.throws(() => transform('changed source', '/src/pages/Home.tsx'));
assert.equal(transform(source, '/src/pages/Other.tsx'), undefined);
const hook = result.match(/  useEffect\(\(\) => \{\n    const target = window.tongyouFallbackRoute([\s\S]*?)\n  \}, \[\]\)/)[0];
for (const [route, expected] of Object.entries({chat: 'selectConv', ledger: 'openLedger', account: 'openAccount', notifications: 'setShowNotifications', trips: 'setTripsBoard', createTrip: 'setCreateTrip', history: 'openMobileHistory'})) {
  const calls = [];
  const window = { tongyouFallbackRoute: { route, id: 'test-id' } };
  const actions = ['selectConv', 'openLedger', 'openAccount', 'setShowNotifications', 'openMobileTrips', 'setTripsBoard', 'setCreateTrip', 'openMobileHistory'];
  new Function('window', 'isAndroidApp', 'useEffect', ...actions, hook)(window, () => true, f => f(), ...actions.map(a => (...args) => calls.push([a, ...args])));
  assert.ok(calls.some(c => c[0] === expected), route);
  assert.equal(window.tongyouFallbackRoute, undefined);
}
'''], cwd=ROOT, check=True, capture_output=True, text=True)


if __name__ == '__main__':
    unittest.main()
