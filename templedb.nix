# TempleDB Nix Package
# Self-contained package definition for TempleDB
# Can be used in NixOS configurations or imported as a flake

{ pkgs ? import <nixpkgs> {}, lib ? pkgs.lib }:

pkgs.python3Packages.buildPythonApplication rec {
  pname = "templedb";
  version = "0.1.0";

  pyproject = true;
  build-system = with pkgs.python3Packages; [ setuptools ];

  src = ./.;

  propagatedBuildInputs = with pkgs.python3Packages; [
    # Core dependencies
    pyyaml
    textual
    rich

    # Optional dependencies
    # tqdm  # Progress bars for large operations
  ];

  # System dependencies
  buildInputs = with pkgs; [
    sqlite
    git
    age  # For secret management
  ];

  # Don't run tests during build (for now)
  doCheck = false;

  # Install the CLI entry point
  postInstall = ''
    # Create wrapper scripts
    mkdir -p $out/bin

    # Main templedb CLI
    cat > $out/bin/templedb <<'EOF'
#!/usr/bin/env bash
export PYTHONPATH="${pkgs.python3Packages.makePythonPath propagatedBuildInputs}:$PYTHONPATH"
exec ${pkgs.python3}/bin/python3 $out/lib/python*/site-packages/templedb/main.py "$@"
EOF
    chmod +x $out/bin/templedb

    # tdb wrapper
    cp ${./tdb} $out/bin/tdb
    chmod +x $out/bin/tdb
  '';

  meta = with lib; {
    description = "Database-native development environment and project manager";
    longDescription = ''
      TempleDB is a database-native approach to managing development projects,
      environments, secrets, and deployments. It provides version control,
      dependency tracking, and reproducible environments backed by SQLite.

      Features:
      - Project management with Git integration
      - Cathedral package format for portable project distribution
      - Nix environment generation
      - Age-encrypted secret management
      - Deployment orchestration
      - NixOS integration
    '';
    homepage = "https://github.com/yourusername/templedb";
    license = licenses.mit;
    maintainers = [];
    platforms = platforms.unix;
  };
}
