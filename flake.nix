{
  description = "TempleDB - Database-native project manager";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    let


      # Build the templedb package for a given pkgs
      mkPackage = pkgs:
        let
          python = pkgs.python3;
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
            mkdir -p "$SITE" "$out/bin"

            # Install all Python packages and modules from src/.
            cp -r src/. "$SITE/"

            # Install root-level Python modules (gui, mcp_server, etc.)
            for f in *.py; do
              [ -f "$f" ] && cp "$f" "$SITE/" || true
            done

            # templedb entry point: python -m cli
            makeWrapper ${pythonEnv}/bin/python3 "$out/bin/templedb" \
              --add-flags "-m cli" \
              --set PYTHONPATH "$SITE" \
              --prefix PATH : "${pkgs.swi-prolog}/bin"

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
              description = "Auto-mount TempleDB FUSE filesystem on login.";
            };

            mount.path = lib.mkOption {
              type = lib.types.str;
              default = "${config.home.homeDirectory}/temple";
              description = "FUSE mount point for TempleDB filesystem.";
            };

            sync.enable = lib.mkOption {
              type = lib.types.bool;
              default = false;
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

            devWrapper = lib.mkOption {
              type = lib.types.nullOr lib.types.str;
              default = null;
              description = ''
                Path to the dev wrapper script (e.g. "/home/zach/templeDB/templedb").
                When set, systemd services, MCP, and hooks use this instead of the
                nix-profile binary. The dev wrapper handles its own python/PYTHONPATH
                resolution and has fallback logic for missing ./result symlinks.
              '';
            };
          };

          config = let
            templedb-bin = if cfg.devWrapper != null
              then cfg.devWrapper
              else "${cfg.package}/bin/templedb";
          in lib.mkIf cfg.enable (lib.mkMerge [
            {
              home.packages = [ cfg.package ];
            }

            # When devWrapper is set, override hookCommand to use it
            (lib.mkIf (cfg.devWrapper != null) {
              programs.templedb.claude.hookCommand = lib.mkDefault "${templedb-bin} ai claude hook";
            })

            (lib.mkIf cfg.mount.enable {
              home.activation.createTempleMount = lib.hm.dag.entryAfter ["writeBoundary"] ''
                mkdir -p ${cfg.mount.path}
              '';

              systemd.user.services.templedb-mount = {
                Unit = {
                  Description = "TempleDB FUSE Mount";
                  After = [ "default.target" ];
                };
                Service = {
                  Type = "simple";
                  ExecStart = "${templedb-bin} mount ${cfg.mount.path} --foreground";
                  ExecStop = "/run/wrappers/bin/fusermount -u ${cfg.mount.path}";
                  Restart = "on-failure";
                  RestartSec = 5;
                  Environment = [ "PYTHONUNBUFFERED=1" ]
                    ++ lib.optionals (cfg.devWrapper != null) [
                      "PATH=/run/current-system/sw/bin:/nix/var/nix/profiles/default/bin:/usr/bin:/bin"
                    ];
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
                    command = "${templedb-bin}";
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
                  ExecStart = "${templedb-bin} sync serve --port ${toString cfg.sync.port}";
                  Restart = "on-failure";
                  RestartSec = 10;
                  Environment = [ "PYTHONUNBUFFERED=1" ]
                    ++ lib.optionals (cfg.devWrapper != null) [
                      "PATH=/run/current-system/sw/bin:/nix/var/nix/profiles/default/bin:/usr/bin:/bin"
                    ];
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

            # Python env with all templedb dependencies
            (python3.withPackages (ps: with ps; [
              pyyaml rich requests cryptography fastapi uvicorn python-multipart fusepy
              tree-sitter tree-sitter-python tree-sitter-javascript
            ]))
          ];
          shellHook = ''
            export RUST_BACKTRACE=1
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
