{
  description = "templedb - SQLite-backed project config + sops secrets manager";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    nixops4.url = "github:nixops4/nixops4";
    nixops4.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = { self, nixpkgs, flake-utils, nixops4 }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config = {
            # Allow unfree packages if needed
            allowUnfree = true;
          };
          overlays = [
            # Fix broken Python packages and reduce dependency bloat
            (final: prev: {
              python311Packages = prev.python311Packages.overrideScope (pyFinal: pyPrev: {
                # Skip tests for pytest-doctestplus which is failing due to numpy incompatibility
                pytest-doctestplus = pyPrev.pytest-doctestplus.overridePythonAttrs (old: {
                  doCheck = false;
                });
                # Skip tests for astropy which depends on pytest-doctestplus
                astropy = pyPrev.astropy.overridePythonAttrs (old: {
                  doCheck = false;
                });
                # Remove optional plotly dependency from igraph to avoid massive opencv build chain
                # (igraph → plotly → scikit-image → imageio → pillow-heif → opencv)
                igraph = pyPrev.igraph.overridePythonAttrs (old: {
                  # Remove plotly and other optional heavy dependencies
                  propagatedBuildInputs = prev.lib.filter
                    (dep:
                      let name = dep.pname or (builtins.parseDrvName dep.name).name or "";
                      in !(builtins.elem name ["plotly"]))
                    (old.propagatedBuildInputs or []);
                  # Skip tests since we're modifying dependencies
                  doCheck = false;
                });
                # Fix Sphinx - use older version compatible with Python 3.11
                sphinx = pyPrev.buildPythonPackage rec {
                  pname = "sphinx";
                  version = "7.4.7";
                  format = "pyproject";

                  src = prev.fetchPypi {
                    inherit pname version;
                    sha256 = "sha256-bsImMH+V/hNkaHGu8OKr/+xmKdIDDJkvN8MONNLQaMc=";
                  };

                  nativeBuildInputs = with pyPrev; [ flit-core ];
                  propagatedBuildInputs = with pyPrev; [
                    sphinxcontrib-applehelp
                    sphinxcontrib-devhelp
                    sphinxcontrib-jsmath
                    sphinxcontrib-htmlhelp
                    sphinxcontrib-serializinghtml
                    sphinxcontrib-qthelp
                    jinja2
                    pygments
                    docutils
                    snowballstemmer
                    babel
                    alabaster
                    imagesize
                    requests
                    packaging
                    importlib-metadata
                  ];

                  doCheck = false;
                  pythonImportsCheck = [ "sphinx" ];
                };
              });
            })
          ];
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
            python312
            python312Packages.textual
            python312Packages.rich
            python312Packages.pyyaml  # For secret management
            python312Packages.cryptography  # For RSA encryption
            python312Packages.requests  # For DNS provider APIs

            # Google Drive backup dependencies
            python312Packages.google-api-python-client
            python312Packages.google-auth
            python312Packages.google-auth-oauthlib
            python312Packages.google-auth-httplib2

            # Google Cloud Storage backup dependencies
            python312Packages.google-cloud-storage

            # Vibe coding real-time dependencies
            python312Packages.aiohttp  # Async web server
            python312Packages.watchdog  # File system monitoring
            python312Packages.websockets  # WebSocket support
            python312Packages.anthropic  # Claude API for AI question generation

            # Git server dependencies
            python312Packages.dulwich  # Pure Python git implementation

            # Code intelligence dependencies (symbol extraction, dependency analysis)
            python312Packages.tree-sitter  # AST parsing engine
            python312Packages.tree-sitter-grammars.tree-sitter-python
            python312Packages.tree-sitter-grammars.tree-sitter-javascript
            python312Packages.tree-sitter-grammars.tree-sitter-typescript

            # Graph analysis dependencies (community detection, clustering)
            python312Packages.networkx  # Graph data structures
            python312Packages.igraph  # Fast graph library
            python312Packages.leidenalg  # Leiden algorithm

            # Runtime tools your CLI shells out to
            sops
            age
            age-plugin-yubikey

            # Nice-to-haves
            git
            just
            google-cloud-sdk  # gcloud CLI for GCS management

            # NixOps4 for deployment orchestration
            nixops4.packages.${system}.default
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

            environment.systemPackages = [
              cfg.package
              nixops4.packages.${pkgs.system}.default
            ];

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
