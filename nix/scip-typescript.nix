# scip-typescript packaging for TempleDB's SCIP ingest adapter.
#
# Ships @sourcegraph/scip-typescript pinned at v0.4.0 as a nix
# derivation. Imported by flake.nix and added to the templedb
# wrapper's PATH prefix.
#
# Implementation: `writeShellApplication` that shells out to
# `npx --yes @sourcegraph/scip-typescript@0.4.0 "$@"`. Not fully
# hermetic — first run fetches the package into `~/.npm` cache;
# subsequent runs are offline. Chose this over `buildNpmPackage`
# (needs package-lock.json which upstream doesn't ship — uses yarn)
# and over `mkYarnPackage` (works but adds two more hashes to hunt).
#
# If hermetic packaging matters, migrate to `mkYarnPackage` later —
# see https://github.com/sourcegraph/scip-typescript for the yarn.lock.
# The upstream `src.hash` for v0.4.0 is:
#   sha256-VKzNiazF+TtlvmXNCIEJbhsuNfnL2c8FslnVFvydXs8=
# (already resolved via nix-build hash mismatch, kept here for reuse).

{ lib, writeShellApplication, nodejs }:

writeShellApplication {
  name = "scip-typescript";
  runtimeInputs = [ nodejs ];
  text = ''
    # Pin to v0.4.0 so behavior is deterministic even though the
    # fetch itself is impure. `npx --yes` suppresses the interactive
    # install prompt; the package is cached under ~/.npm after the
    # first successful invocation.
    exec npx --yes @sourcegraph/scip-typescript@0.4.0 "$@"
  '';

  meta = with lib; {
    description = "SCIP indexer for TypeScript / JavaScript (npx wrapper)";
    homepage = "https://github.com/sourcegraph/scip-typescript";
    license = licenses.asl20;
    mainProgram = "scip-typescript";
  };
}
