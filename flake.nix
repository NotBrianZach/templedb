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

        # Default package
        packages.default = self.packages.${system}.templedb-tui;

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

            # Runtime tools your CLI shells out to
            sops
            age
            age-plugin-yubikey

            # Nice-to-haves
            git
            just
          ];

          # Environment variables useful for dev
          shellHook = ''
            export RUST_BACKTRACE=1
            echo "templedb dev shell loaded"
            echo "TUI available: python3 src/tui.py"
          '';
        };
      });
}
