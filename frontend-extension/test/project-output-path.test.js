import test from 'node:test';
import assert from 'node:assert/strict';
import { isProjectOutputPath } from '../../frontend/utils/projectOutputPath.js';

test('only root-relative outputs paths are promotable', () => {
  assert.equal(isProjectOutputPath('outputs/report.pdf'), true);
  assert.equal(isProjectOutputPath('./outputs/report.pdf'), true);
  assert.equal(isProjectOutputPath('uploads/outputs/report.pdf'), false);
  assert.equal(isProjectOutputPath('nested/outputs/report.pdf'), false);
});

test('absolute Agent paths inside an outputs segment remain supported', () => {
  assert.equal(
    isProjectOutputPath('/data/workspaces/session-a/outputs/report.pdf', 'session-a'),
    true,
  );
  assert.equal(isProjectOutputPath('/tmp/outputs/report.pdf', 'session-a'), false);
  assert.equal(
    isProjectOutputPath('/data/workspaces/session-b/outputs/report.pdf', 'session-a'),
    false,
  );
  assert.equal(isProjectOutputPath('../outputs/report.pdf'), false);
});
