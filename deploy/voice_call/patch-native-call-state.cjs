'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');

const ORIGINAL_SHA256 = '85f9eb8f4c18fe57c789c0fdd44c761dd73954c220fa5acae40341f484dfd14b';
const PROFILE = 'qq-win32-9.9.36-53644-x64';
const changes = [
  ['    const { command, value, requestId } = body ?? {};',
   "    const { command, value, requestId } = body ?? {};\n    const needsPeerAccept = host?.nativeProfile?.id === 'qq-win32-9.9.36-53644-x64' &&\n      state.call?.kind === 'private' && state.call.direction === 'outgoing' && state.call.media === 'audio';"],
  ['    } else if (command === NATIVE.ENTER_ROOM) {',
   '    } else if (command === NATIVE.ENTER_ROOM || (needsPeerAccept && command === 20020)) {'],
  ["      if (!Array.isArray(value) || !Number.isInteger(value[0])) throw new BridgeError('INVALID_OUTPUT', 'Unknown room result shape');\n      state.call.phase = value[0] === 0 ? 'connected' : 'error';\n      if (value[0] === 0) state.call.nativeConnectedAt ??= now();",
   "      if (!Array.isArray(value) || (command === 20020 ? value.length !== 0 : !Number.isInteger(value[0]))) throw new BridgeError('INVALID_OUTPUT', 'Unknown room result shape');\n      const roomResult = command === 20020 ? 0 : value[0];\n      if (needsPeerAccept) {\n        if (concurrentInviteSeen) return;\n        if (roomResult === 0) {\n          if (command === 20020) state.call.nativePeerAcceptedAt ??= now();\n          else state.call.nativeRoomEnteredAt ??= now();\n          // Local room entry does not prove that the outgoing peer answered.\n          if (!state.call.nativeRoomEnteredAt || !state.call.nativePeerAcceptedAt) { callEvent(); return; }\n        }\n      }\n      state.call.phase = roomResult === 0 ? 'connected' : 'error';\n      if (roomResult === 0) state.call.nativeConnectedAt ??= now();"],
  ["      if (value[0] === 0 && state.call.kind === 'private' && state.call.nativeSceneId === 1 &&",
   "      if (roomResult === 0 && state.call.kind === 'private' && state.call.nativeSceneId === 1 &&"],
  ["      if (value[0] === 0 && profileById(host?.nativeProfile?.id)?.participants && state.call.nativeRoom) {",
   "      if (roomResult === 0 && profileById(host?.nativeProfile?.id)?.participants && state.call.nativeRoom) {"],
];
const sha256 = value => createHash('sha256').update(value).digest('hex');
function replaceOnce(source, before, after) {
  if (source.split(before).length !== 2) throw new Error('Unknown native controller anchor; not patched');
  return source.replace(before, after);
}
function patchController(source) {
  const replacements = changes.map(pair => pair.map(value => value.replaceAll('\n', '\r\n')));
  if (sha256(source) === ORIGINAL_SHA256) return replacements.reduce((value, [before, after]) => replaceOnce(value, before, after), source);
  const restored = replacements.reduce((value, [before, after]) => replaceOnce(value, after, before), source);
  if (sha256(restored) !== ORIGINAL_SHA256) throw new Error('Unknown native controller SHA256; not patched');
  return source;
}
function applyPatch(settingsPath) {
  const settings = JSON.parse(fs.readFileSync(settingsPath, 'utf8'));
  const installDir = fs.realpathSync(settings.install_dir);
  const manifest = JSON.parse(fs.readFileSync(path.join(installDir, 'runtime/install-manifest.json'), 'utf8'));
  if (manifest.schemaVersion !== 1 || manifest.kind !== 'koishi-rtc-qq-windows' || manifest.profileId !== PROFILE ||
      fs.realpathSync(manifest.installDir) !== installDir) throw new Error('Unknown native Windows installation');
  const files = ['napcat-plugin/controller.mjs', 'NapCat/plugins/napcat-plugin-koishi-rtc-qq/controller.mjs'].map(relative => {
    const target = path.join(installDir, relative);
    if (fs.realpathSync(target) !== target) throw new Error('Native controller must not redirect outside its installation');
    const source = fs.readFileSync(target, 'utf8'), patched = patchController(source);
    const backup = target + '.before-yuexu-call-state';
    if (fs.existsSync(backup)) {
      if (sha256(fs.readFileSync(backup)) !== ORIGINAL_SHA256) throw new Error('Unknown native controller backup');
    } else if (sha256(source) !== ORIGINAL_SHA256) throw new Error('Original native controller backup is missing');
    return { target, backup, patched, changed: source !== patched };
  });
  for (const file of files) {
    if (!fs.existsSync(file.backup)) fs.copyFileSync(file.target, file.backup, fs.constants.COPYFILE_EXCL);
    if (file.changed) {
      const pending = file.target + '.yuexu-call-state.tmp';
      fs.writeFileSync(pending, file.patched, { encoding: 'utf8', flag: 'wx' });
      fs.renameSync(pending, file.target);
    }
  }
  const record = { profileId: PROFILE, originalSHA256: ORIGINAL_SHA256,
    files: files.map(({ target, backup, patched, changed }) => ({ target, backup, changed, patchedSHA256: sha256(patched) })) };
  fs.writeFileSync(path.join(installDir, 'runtime/yuexu-call-state-patch.json'), JSON.stringify(record, null, 2) + '\n');
  return record;
}
module.exports = { patchController, applyPatch, sha256 };
if (require.main === module) {
  const settingsPath = process.argv[2] || path.join(__dirname, '../../data/voice_call/native-runtime.json');
  console.log(JSON.stringify(applyPatch(settingsPath)));
}
