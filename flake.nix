{
  description = "templedb - SQLite-backed project config + sops secrets manager";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
        };

        # Rust toolchain
        # rust = pkgs.rustup;
      in
      {
        # TUI package
        packages.templedb-tui = pkgs.callPackage ./default.nix {};

        # CLI package
        packages.templedb = pkgs.callPackage ./templedb.nix {};

        # Default package (CLI)
        packages.default = self.packages.${system}.templedb;

        devShells.default = pkgs.mkShell {
          name = "templedb-dev";

          packages = with pkgs; [
            # rust
            # cargo
            # rust-analyzer

            # Native deps
            sqlite
            pkg-config

            # Python for TUI and CLI
            python311
            python311Packages.textual
            python311Packages.rich
            python311Packages.pyyaml  # For secret management
            python311Packages.cryptography  # For RSA encryption
            python311Packages.requests  # For DNS provider APIs

            # Google Drive backup dependencies
            python311Packages.google-api-python-client
            python311Packages.google-auth
            python311Packages.google-auth-oauthlib
            python311Packages.google-auth-httplib2

            # Google Cloud Storage backup dependencies
            python311Packages.google-cloud-storage

            # Vibe coding real-time dependencies
            python311Packages.aiohttp  # Async web server
            python311Packages.watchdog  # File system monitoring
            python311Packages.websockets  # WebSocket support
            python311Packages.anthropic  # Claude API for AI question generation

            # Runtime tools your CLI shells out to
            sops
            age
            age-plugin-yubikey

            # Nice-to-haves
            git
            just
            google-cloud-sdk  # gcloud CLI for GCS management
          ];

          # Environment variables useful for dev
          shellHook = ''
            export RUST_BACKTRACE=1
            echo "templedb dev shell loaded"
            echo "TUI available: python3 src/tui.py"
          '';
        };

        # Apps for running directly with nix run
        apps = {
          default = {
            type = "app";
            program = "${self.packages.${system}.templedb}/bin/templedb";
          };
          templedb = {
            type = "app";
            program = "${self.packages.${system}.templedb}/bin/templedb";
          };
          tdb = {
            type = "app";
            program = "${self.packages.${system}.templedb}/bin/tdb";
          };
        };
      }
    ) // {
      # NixOS module - enables system-wide TempleDB installation
      nixosModules.default = { config, lib, pkgs, ... }:
        with lib;
        let
          cfg = config.services.templedb;
        in {
          options.services.templedb = {
            enable = mkEnableOption "TempleDB service";

            package = mkOption {
              type = types.package;
              default = self.packages.${pkgs.system}.templedb;
              description = "TempleDB package to use";
            };

            dataDir = mkOption {
              type = types.str;
              default = "/var/lib/templedb";
              description = "Data directory for TempleDB";
            };

            user = mkOption {
              type = types.str;
              default = "templedb";
              description = "User to run TempleDB as";
            };

            group = mkOption {
              type = types.str;
              default = "templedb";
              description = "Group for TempleDB user";
            };
          };

          config = mkIf cfg.enable {
            users.users.${cfg.user} = {
              isSystemUser = true;
              group = cfg.group;
              home = cfg.dataDir;
              createHome = true;
            };

            users.groups.${cfg.group} = {};

            environment.systemPackages = [ cfg.package ];

            # Make templedb available system-wide
            environment.variables = {
              TEMPLEDB_PATH = "${cfg.dataDir}/templedb.sqlite";
            };
          };
        };

      # Home Manager module - per-user TempleDB installation
      homeManagerModules.default = { config, lib, pkgs, ... }:
        with lib;
        let
          cfg = config.programs.templedb;
        in {
          options.programs.templedb = {
            enable = mkEnableOption "TempleDB";

            package = mkOption {
              type = types.package;
              default = self.packages.${pkgs.system}.templedb;
              description = "TempleDB package to use";
            };

            dataDir = mkOption {
              type = types.str;
              default = "${config.home.homeDirectory}/.local/share/templedb";
              description = "Data directory for TempleDB";
            };

            ageKeyFile = mkOption {
              type = types.nullOr types.str;
              default = "${config.home.homeDirectory}/.config/sops/age/keys.txt";
              description = "Path to age key file for secret management";
            };
          };

          config = mkIf cfg.enable {
            home.packages = [ cfg.package ];

            home.sessionVariables = {
              TEMPLEDB_PATH = "${cfg.dataDir}/templedb.sqlite";
            } // (optionalAttrs (cfg.ageKeyFile != null) {
              TEMPLEDB_AGE_KEY_FILE = cfg.ageKeyFile;
            });

            # Note: Shell aliases not set here to avoid conflicts with existing aliases

            # Create data directory
            home.activation.templedbSetup = lib.hm.dag.entryAfter ["writeBoundary"] ''
              mkdir -p ${cfg.dataDir}
            '';
          };
        };
    };
}
