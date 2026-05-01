{
  description = "TempleDB - Database-native project manager";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    nixops4.url = "github:nixops4/nixops4";
    nixops4.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = { self, nixpkgs, flake-utils, nixops4 }:
    let
      # Build the templedb package for a given pkgs
      mkPackage = pkgs:
        let
          python = pkgs.python3;
          pythonEnv = python.withPackages (ps: with ps; [
            pyyaml
            textual
            rich
            aiohttp
            watchdog
            websockets
            requests
            cryptography
          ]);
        in
        pkgs.stdenv.mkDerivation {
          pname = "templedb";
          version = "0.1.0";
          src = ./.;

          nativeBuildInputs = [ pkgs.makeWrapper ];
          dontBuild = true;

          installPhase = ''
            runHook preInstall

            SITE="$out/${python.sitePackages}"
            mkdir -p "$SITE" "$out/bin"

            # Install packages and modules from src/
            cp -r src/cli "$SITE/"
            cp -r src/importer "$SITE/" 2>/dev/null || true
            for f in src/*.py; do
              [ -f "$f" ] && cp "$f" "$SITE/"
            done

            # Install root-level Python modules (vibe_server, mcp_server, etc.)
            for f in *.py; do
              [ -f "$f" ] && cp "$f" "$SITE/" || true
            done

            # templedb entry point: python -m cli
            makeWrapper ${pythonEnv}/bin/python3 "$out/bin/templedb" \
              --add-flags "-m cli" \
              --set PYTHONPATH "$SITE"

            ln -s "$out/bin/templedb" "$out/bin/tdb"

            runHook postInstall
          '';

          meta = with pkgs.lib; {
            description = "Database-native development environment and project manager";
            license = licenses.mit;
          };
        };

      # Home-manager module providing programs.templedb
      homeManagerModule = { config, lib, pkgs, ... }:
        let
          cfg = config.programs.templedb;
        in {
          options.programs.templedb = {
            enable = lib.mkEnableOption "TempleDB";

            package = lib.mkOption {
              type = lib.types.package;
              description = "The templedb package to install.";
            };

            ageKeyFile = lib.mkOption {
              type = lib.types.str;
              default = "${config.home.homeDirectory}/.config/sops/age/keys.txt";
              description = "Path to the age key file used for secret decryption.";
            };
          };

          config = lib.mkIf cfg.enable {
            home.packages = [ cfg.package ];
          };
        };

    in
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
      in
      {
        packages = {
          templedb = mkPackage pkgs;
          default = mkPackage pkgs;
        };

        devShells.default = pkgs.mkShell {
          name = "projdb-dev";
          packages = with pkgs; [
            sqlite
            pkg-config
            sops
            age
            git
            just
            google-cloud-sdk  # gcloud CLI for GCS management

            # NixOps4 for deployment orchestration
            nixops4.packages.${system}.default
          ];
          shellHook = ''
            export RUST_BACKTRACE=1
            echo "templedb dev shell loaded"
            echo "TUI available: python3 src/tui.py"
          '';
        };
      }
    ) // {
      # homeManagerModules is a system-independent output
      homeManagerModules.default = homeManagerModule;
    };
}
