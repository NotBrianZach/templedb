# TempleDB Nix Package
# Self-contained package definition for TempleDB
# Can be used in NixOS configurations or imported as a flake

{ pkgs ? import <nixpkgs> {}, lib ? pkgs.lib }:

pkgs.python3Packages.buildPythonApplication rec {
  pname = "templedb";
  version = "0.1.0";

  pyproject = true;
  build-system = with pkgs.python3Packages; [ setuptools ];

  # Filter source to only include files needed for build
  # This prevents unnecessary rebuilds when non-source files change
  src = lib.sourceFilesBySuffices (lib.cleanSource ./.) [
    ".py"
    ".toml"
    ".md"
    ".sql"
    "tdb"  # Include the tdb wrapper script
  ];

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

  # Install the tdb wrapper script
  postInstall = ''
    # Copy tdb wrapper (templedb entry point is created automatically by setuptools)
    cp ${./tdb} $out/bin/tdb
    chmod +x $out/bin/tdb

    # Fix tdb to use installed templedb instead of relative path
    substituteInPlace $out/bin/tdb \
      --replace './templedb' 'templedb'
  '';

  nativeBuildInputs = [ pkgs.makeWrapper ];

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
