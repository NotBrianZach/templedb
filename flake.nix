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
            tree-sitter
            tree-sitter-python
            tree-sitter-javascript
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

            mount.enable = lib.mkOption {
              type = lib.types.bool;
              default = false;
              description = "Auto-mount TempleDB FUSE filesystem at ~/temple on login.";
            };

            sync.enable = lib.mkOption {
              type = lib.types.bool;
              default = false;
              description = "Run cr-sqlite sync server for machine-to-machine replication.";
            };

            sync.port = lib.mkOption {
              type = lib.types.int;
              default = 9420;
              description = "TCP port for sync server.";
            };

            claude.enable = lib.mkOption {
              type = lib.types.bool;
              default = false;
              description = "Generate Claude Code settings with TempleDB hooks.";
            };

            claude.hookCommand = lib.mkOption {
              type = lib.types.str;
              default = "${cfg.package}/bin/templedb ai claude hook";
              description = "Command to run as Claude Code hook.";
            };

            claude.mcp = lib.mkOption {
              type = lib.types.bool;
              default = true;
              description = "Register TempleDB MCP server globally so all Claude Code sessions can access TempleDB tools.";
            };
          };

          config = lib.mkIf cfg.enable (lib.mkMerge [
            {
              home.packages = [ cfg.package ];
            }

            (lib.mkIf cfg.mount.enable {
              home.activation.createTempleMount = lib.hm.dag.entryAfter ["writeBoundary"] ''
                mkdir -p $HOME/temple
              '';

              systemd.user.services.templedb-mount = {
                Unit = {
                  Description = "TempleDB FUSE Mount";
                  After = [ "default.target" ];
                };
                Service = {
                  Type = "simple";
                  ExecStart = "${cfg.package}/bin/templedb mount %h/temple --foreground";
                  ExecStop = "/run/wrappers/bin/fusermount -u %h/temple";
                  Restart = "on-failure";
                  RestartSec = 5;
                  Environment = [ "PYTHONUNBUFFERED=1" ];
                };
                Install.WantedBy = [ "default.target" ];
              };
            })

            (lib.mkIf cfg.claude.enable {
              # Generate ~/.claude/settings.json with templedb hooks + optional MCP
              home.file.".claude/settings.json".text = builtins.toJSON ({
                hooks = {
                  PreToolUse = [
                    {
                      matcher = "Bash";
                      hooks = [
                        {
                          type = "command";
                          command = cfg.claude.hookCommand;
                          arguments = ["pre-tool" "bash"];
                        }
                      ];
                    }
                  ];
                  PostToolUse = [
                    {
                      matcher = "Bash";
                      hooks = [
                        {
                          type = "command";
                          command = cfg.claude.hookCommand;
                          arguments = ["post-tool" "bash"];
                        }
                      ];
                    }
                  ];
                  Notification = [
                    {
                      matcher = "";
                      hooks = [
                        {
                          type = "command";
                          command = cfg.claude.hookCommand;
                          arguments = ["notify"];
                        }
                      ];
                    }
                  ];
                };
                permissions = {
                  allow = [
                    "Bash(templedb:*)"
                    "Bash(python3:*)"
                    "Bash(nix:*)"
                    "Bash(nix-shell:*)"
                    "Bash(npm:*)"
                    "Bash(ls:*)"
                    "Bash(fusermount:*)"
                    "Bash(systemctl:*)"
                    "Bash(journalctl:*)"
                    "Bash(gh:*)"
                    "Bash(jq:*)"
                    "Read(//home/**)"
                    "Read(//tmp/**)"
                    "Read(//etc/**)"
                    "Read(//nix/store/**)"
                    "WebSearch"
                  ];
                  deny = [];
                };
              });
            })

            (lib.mkIf (cfg.claude.enable && cfg.claude.mcp) {
              # Global ~/.mcp.json so TempleDB MCP tools are available in all projects
              home.file.".mcp.json".text = builtins.toJSON {
                mcpServers = {
                  templedb = {
                    command = "${cfg.package}/bin/templedb";
                    args = ["ai" "mcp" "serve"];
                  };
                };
              };
            })

            (lib.mkIf cfg.sync.enable {
              systemd.user.services.templedb-sync = {
                Unit = {
                  Description = "TempleDB Sync Server";
                  After = [ "network-online.target" ];
                  Wants = [ "network-online.target" ];
                };
                Service = {
                  Type = "simple";
                  ExecStart = "${cfg.package}/bin/templedb sync serve --port ${toString cfg.sync.port}";
                  Restart = "on-failure";
                  RestartSec = 10;
                  Environment = [ "PYTHONUNBUFFERED=1" ];
                };
                Install.WantedBy = [ "default.target" ];
              };
            })
          ]);
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
              tree-sitter tree-sitter-python tree-sitter-javascript
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
