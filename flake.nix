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
      # cr-sqlite pre-built extension, patched for NixOS
      mkCrsqlite = pkgs: pkgs.stdenv.mkDerivation {
        pname = "crsqlite";
        version = "0.16.3";

        src = pkgs.fetchzip {
          url = "https://github.com/vlcn-io/cr-sqlite/releases/download/v0.16.3/crsqlite-linux-x86_64.zip";
          hash = "sha256-F9uTWLanDAjL4btdEHtmNnc1SdHAzbAOYBTPCa4BqJI=";
          stripRoot = false;
        };

        nativeBuildInputs = [ pkgs.autoPatchelfHook ];
        buildInputs = [ pkgs.stdenv.cc.cc.lib ];

        installPhase = ''
          mkdir -p $out/lib
          cp crsqlite.so $out/lib/
        '';
      };

      # Build the templedb package for a given pkgs
      mkPackage = pkgs:
        let
          python = pkgs.python3;
          crsqlite = mkCrsqlite pkgs;
          pythonEnv = python.withPackages (ps: with ps; [
            pyyaml
            rich
            requests
            cryptography
            fastapi
            uvicorn
            python-multipart
            fusepy
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
            mkdir -p "$SITE" "$out/bin" "$out/lib"

            # Install all Python packages and modules from src/.
            cp -r src/. "$SITE/"

            # Install root-level Python modules (gui, mcp_server, etc.)
            for f in *.py; do
              [ -f "$f" ] && cp "$f" "$SITE/" || true
            done

            # Install cr-sqlite extension
            cp ${crsqlite}/lib/crsqlite.so "$out/lib/"

            # templedb entry point: python -m cli
            makeWrapper ${pythonEnv}/bin/python3 "$out/bin/templedb" \
              --add-flags "-m cli" \
              --set PYTHONPATH "$SITE" \
              --set TEMPLEDB_CRSQLITE_PATH "$out/lib/crsqlite"

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
          crsqlite = mkCrsqlite pkgs;
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
            google-cloud-sdk

            # NixOps4 for deployment orchestration
            nixops4.packages.${system}.default

            # Python env with all templedb dependencies
            (python3.withPackages (ps: with ps; [
              pyyaml rich requests cryptography fastapi uvicorn python-multipart fusepy
            ]))
          ];
          shellHook = ''
            export RUST_BACKTRACE=1
            export TEMPLEDB_CRSQLITE_PATH="${(mkCrsqlite pkgs)}/lib/crsqlite"
            echo "templedb dev shell loaded"
            echo "GUI available: templedb gui"
          '';
        };
      }
    ) // {
      # homeManagerModules is a system-independent output
      homeManagerModules.default = homeManagerModule;
    };
}
