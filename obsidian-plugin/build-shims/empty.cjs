// Empty module shim for build-time aliasing.
//
// transformers.js statically imports optional native deps (e.g. `sharp` for
// image processing) that we never use for audio transcription. Aliasing those
// imports to this empty module lets the bundle resolve them without pulling in
// native binaries or producing failing runtime `require()` calls.
module.exports = {};
module.exports.default = {};
