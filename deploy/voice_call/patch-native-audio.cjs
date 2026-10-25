'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');

const ORIGINAL_SHA256 = 'a41ecbbeb8a48ea0f0a2e650ca506343625adfd4dbff8d855eaf53f0d5c59c3c';
const PROFILE = 'qq-win32-9.9.36-53644-x64';
const legacyChanges = [
  ["  if (nativeProfile) for (const command of [4, 5, 8, 9, 10, 13]) ALLOWED_COMMANDS.add(command);",
   "  if (nativeProfile) for (const command of [4, 5, 8, 9, 10, 13]) ALLOWED_COMMANDS.add(command);\n  if (nativeProfile?.id === 'qq-win32-9.9.36-53644-x64') ALLOWED_COMMANDS.add(18);"],
  ['        if (!avWindow || !rendererState.ready || !rendererState.pluginFound || !rendererState.methods.includes(\'postMessage\')) {',
   "        if (command === 18 && (params.length !== 2 || !params.every(value => typeof value === 'boolean'))) {\n          return sendJson(res, 400, { code: -1, message: 'Audio start requires two booleans' });\n        }\n        if (!avWindow || !rendererState.ready || !rendererState.pluginFound || !rendererState.methods.includes('postMessage')) {"],
  ['          if (windowsRoute && [4, 5].includes(command)) await windowsRoute.ensure();',
   '          if (windowsRoute && [4, 5, 18].includes(command)) await windowsRoute.ensure();'],
  ['        if (windowsRoute && [4, 5].includes(command)) windowsRoute.setCallActive(true);',
   '        if (windowsRoute && [4, 5, 18].includes(command)) windowsRoute.setCallActive(true);'],
];
const audioChanges = [...legacyChanges,
  ['  lastInvocationAt: null,', '  lastInvocationAt: null,\n  nativeAudioStart: null,'],
  ['        requestByNativeId.set(invocationId, requestId);',
   "        requestByNativeId.set(invocationId, requestId);\n        if (command === 18 && nativeProfile?.id === 'qq-win32-9.9.36-53644-x64') {\n          rendererState = { ...rendererState, nativeAudioStart: { requestId, nativeId: invocationId, posted: false, resultCode: null, receivedAt: null } };\n        }"],
  ["        if (result?.posted !== true || result?.id !== invocationId) throw new Error('invalid native submission receipt');",
   "        if (result?.posted !== true || result?.id !== invocationId) throw new Error('invalid native submission receipt');\n        if (command === 18 && rendererState.nativeAudioStart?.nativeId === invocationId) {\n          rendererState = { ...rendererState, nativeAudioStart: { ...rendererState.nativeAudioStart, posted: true } };\n        }"],
  ['  void audioRouter?.onMessage(message);',
   "  const audioStart = rendererState.nativeAudioStart;\n  if (nativeProfile?.id === 'qq-win32-9.9.36-53644-x64' && message?.cmd === 18 && audioStart &&\n      message.id === audioStart.nativeId && requestByNativeId.get(message.id) === audioStart.requestId && audioStart.receivedAt === null &&\n      Array.isArray(message.value) && message.value.length === 2 && Number.isInteger(message.value[0]) && typeof message.value[1] === 'string') {\n    rendererState = { ...rendererState, nativeAudioStart: { ...audioStart, resultCode: message.value[0], receivedAt: new Date().toISOString() } };\n  }\n  void audioRouter?.onMessage(message);"],
];
const primeRenderer = async active => {
  const existing = window.__yuexuAudioPrime;
  if (!active) {
    if (existing) {
      clearTimeout(existing.timer);
      delete window.__yuexuAudioPrime;
      await existing.context.close();
    }
    return { active: false };
  }
  if (existing && existing.context.state !== 'closed') return { active: existing.context.state === 'running' };
  const context = new AudioContext(), prime = { context, timer: null };
  window.__yuexuAudioPrime = prime;
  try {
    const source = context.createConstantSource();
    source.offset.value = 0;
    source.connect(context.destination);
    source.start();
    await context.resume();
    if (context.state !== 'running') throw new Error('Audio session did not start');
    prime.timer = setTimeout(() => {
      void context.close().catch(() => {});
      if (window.__yuexuAudioPrime === prime) delete window.__yuexuAudioPrime;
    }, 30000);
    return { active: true };
  } catch (error) {
    if (window.__yuexuAudioPrime === prime) delete window.__yuexuAudioPrime;
    await context.close().catch(() => {});
    throw error;
  }
};
const primeAnchor = "    if (req.method === 'GET' && url.pathname === '/v1/audio/devices' && windowsRoute) {";
const changes = [...audioChanges, [primeAnchor,
  `    if (req.method === 'POST' && url.pathname === '/v1/audio/prime') {
      try {
        const body = await readJsonBody(req, 1024);
        if (!body || typeof body.active !== 'boolean' || Object.keys(body).some(key => key !== 'active')) {
          return sendJson(res, 400, { code: -1, message: 'Expected only an active boolean' });
        }
        if (nativeProfile?.id !== '${PROFILE}' || nativeFailure || !windowsRoute || windowsRoute.callActive !== false ||
            !avWindow || !rendererState.ready || !rendererState.pluginFound) {
          return sendJson(res, 409, { code: -1, message: 'Audio priming requires an idle audited Windows Host' });
        }
        const data = await avWindow.webContents.executeJavaScript(${JSON.stringify('(' + primeRenderer.toString() + ')')} + '(' + JSON.stringify(body.active) + ')', true);
        return sendJson(res, 200, { code: 0, data });
      } catch {
        return sendJson(res, 503, { code: -1, message: 'Audio session priming failed' });
      }
    }
${primeAnchor}`]];
const sha256 = value => createHash('sha256').update(value).digest('hex');
function replaceOnce(source, before, after) {
  if (source.split(before).length !== 2) throw new Error('Unknown native Host anchor; not patched');
  return source.replace(before, after);
}
function patchHost(source) {
  if (sha256(source) === ORIGINAL_SHA256) {
    return changes.reduce((value, [before, after]) => replaceOnce(value, before, after), source);
  }
  for (const applied of [changes, audioChanges, legacyChanges]) {
    try {
      const restored = applied.reduce((value, [before, after]) => replaceOnce(value, after, before), source);
      if (sha256(restored) === ORIGINAL_SHA256) return changes.reduce((value, [before, after]) => replaceOnce(value, before, after), restored);
    } catch { /* Only a complete known patch may be upgraded. */ }
  }
  throw new Error('Unknown native Host SHA256; not patched');
}
function applyPatch(settingsPath) {
  const settings = JSON.parse(fs.readFileSync(settingsPath, 'utf8'));
  const installDir = fs.realpathSync(settings.install_dir);
  const manifest = JSON.parse(fs.readFileSync(path.join(installDir, 'runtime/install-manifest.json'), 'utf8'));
  if (manifest.schemaVersion !== 1 || manifest.kind !== 'koishi-rtc-qq-windows' || manifest.profileId !== PROFILE ||
      fs.realpathSync(manifest.installDir) !== installDir) throw new Error('Unknown native Windows installation');
  const target = path.join(installDir, 'av-host/host.cjs');
  if (fs.realpathSync(target) !== target) throw new Error('Native Host must not redirect outside its installation');
  const source = fs.readFileSync(target, 'utf8'), patched = patchHost(source);
  const backup = target + '.before-yuexu-native-audio';
  if (fs.existsSync(backup)) {
    if (sha256(fs.readFileSync(backup)) !== ORIGINAL_SHA256) throw new Error('Unknown native Host backup');
  } else {
    if (sha256(source) !== ORIGINAL_SHA256) throw new Error('Original native Host backup is missing');
    fs.copyFileSync(target, backup, fs.constants.COPYFILE_EXCL);
  }
  const changed = source !== patched;
  const record = { profileId: PROFILE, target, backup, originalSHA256: ORIGINAL_SHA256, patchedSHA256: sha256(patched) };
  if (changed) {
    const pending = target + '.yuexu-native-audio.tmp';
    fs.writeFileSync(pending, patched, { encoding: 'utf8', flag: 'wx' });
    fs.renameSync(pending, target);
  }
  fs.writeFileSync(path.join(installDir, 'runtime/yuexu-native-audio-patch.json'), JSON.stringify(record, null, 2) + '\n');
  return { changed, ...record };
}
module.exports = { patchHost, applyPatch, sha256 };
if (require.main === module) {
  const settingsPath = process.argv[2] || path.join(__dirname, '../../data/voice_call/native-runtime.json');
  console.log(JSON.stringify(applyPatch(settingsPath)));
}
