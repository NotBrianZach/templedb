#!/usr/bin/env python3
"""
App Store Deployment Service - Phase 2 Implementation

Handles deployment of CLI tools to:
- Homebrew (macOS package manager)
- Snap (Linux universal packages)
- macOS App Store (.app bundles with code signing)
- Windows Store (MSIX packages)
"""
import subprocess
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import tempfile
import shutil
import hashlib

from logger import get_logger

logger = get_logger(__name__)


@dataclass
class AppStoreDeploymentResult:
    """Result of an app store deployment operation"""
    success: bool
    message: str
    package_path: Optional[Path] = None
    formula_url: Optional[str] = None
    store_url: Optional[str] = None
    error: Optional[str] = None


class AppStoreDeploymentService:
    """
    Service for deploying CLI tools to app stores.

    Supported targets:
    - Homebrew (macOS/Linux package manager)
    - Snap (Linux universal packages)
    - macOS App Store (.app bundles)
    - Windows Store (MSIX packages)
    """

    def __init__(self, db_connection=None):
        self.db = db_connection
        self.temp_dir = Path(tempfile.gettempdir()) / "templedb-appstore"
        self.temp_dir.mkdir(exist_ok=True)

    # ========================================================================
    # HOMEBREW DEPLOYMENT
    # ========================================================================

    def generate_homebrew_formula(
        self,
        project_slug: str,
        project_name: str,
        description: str,
        homepage: str,
        version: str,
        tarball_url: str,
        tarball_sha256: str,
        dependencies: Optional[List[str]] = None,
        install_script: Optional[str] = None
    ) -> str:
        """
        Generate Homebrew formula (Ruby DSL).

        Args:
            project_slug: Project identifier (lowercase, no spaces)
            project_name: Display name
            description: Short description
            homepage: Project homepage URL
            version: Version string (e.g., "1.0.0")
            tarball_url: URL to source tarball
            tarball_sha256: SHA256 hash of tarball
            dependencies: List of Homebrew dependencies
            install_script: Custom install script (optional)

        Returns:
            Homebrew formula content (Ruby)
        """
        dependencies = dependencies or []

        # Generate dependency list
        deps_ruby = ""
        if dependencies:
            deps_lines = [f'  depends_on "{dep}"' for dep in dependencies]
            deps_ruby = "\n".join(deps_lines)

        # Default install script (for Python projects)
        if not install_script:
            install_script = "    virtualenv_install_with_resources"

        formula = f'''class {self._to_class_name(project_slug)} < Formula
  desc "{description}"
  homepage "{homepage}"
  url "{tarball_url}"
  sha256 "{tarball_sha256}"
  license "MIT"

{deps_ruby}

  def install
{install_script}
  end

  test do
    system "#{bin}/{project_slug}", "--version"
  end
end
'''

        return formula

    def _to_class_name(self, slug: str) -> str:
        """Convert slug to Ruby class name (CapitalizedCamelCase)"""
        parts = slug.replace('-', '_').split('_')
        return ''.join(word.capitalize() for word in parts)

    def create_homebrew_tap(
        self,
        project_slug: str,
        formula: str,
        tap_org: str,
        tap_repo: Optional[str] = None
    ) -> AppStoreDeploymentResult:
        """
        Create Homebrew tap repository structure.

        Args:
            project_slug: Project identifier
            formula: Formula content (Ruby)
            tap_org: GitHub organization (e.g., "yourorg")
            tap_repo: Tap repository name (default: "homebrew-tap")

        Returns:
            AppStoreDeploymentResult with tap info
        """
        tap_repo = tap_repo or "homebrew-tap"
        tap_dir = self.temp_dir / f"{tap_org}-{tap_repo}"
        tap_dir.mkdir(exist_ok=True)

        # Create Formula directory
        formula_dir = tap_dir / "Formula"
        formula_dir.mkdir(exist_ok=True)

        # Write formula
        formula_file = formula_dir / f"{project_slug}.rb"
        with open(formula_file, 'w') as f:
            f.write(formula)

        logger.info(f"Created Homebrew tap at {tap_dir}")

        # Create README
        readme_content = f'''# {tap_org}/{tap_repo}

Homebrew tap for {project_slug}

## Installation

```bash
brew tap {tap_org}/{tap_repo}
brew install {project_slug}
```

## Usage

```bash
{project_slug} --help
```
'''

        with open(tap_dir / "README.md", 'w') as f:
            f.write(readme_content)

        return AppStoreDeploymentResult(
            success=True,
            message=f"Homebrew tap created at {tap_dir}",
            package_path=tap_dir,
            formula_url=f"https://github.com/{tap_org}/{tap_repo}/blob/main/Formula/{project_slug}.rb"
        )

    def publish_homebrew_tap(
        self,
        tap_dir: Path,
        tap_org: str,
        tap_repo: str = "homebrew-tap"
    ) -> AppStoreDeploymentResult:
        """
        Publish Homebrew tap to GitHub.

        Assumes git and gh (GitHub CLI) are installed.

        Args:
            tap_dir: Path to tap directory
            tap_org: GitHub organization
            tap_repo: Tap repository name

        Returns:
            AppStoreDeploymentResult
        """
        try:
            # Initialize git repo if not already
            if not (tap_dir / ".git").exists():
                subprocess.run(["git", "init"], cwd=tap_dir, check=True)
                subprocess.run(["git", "add", "."], cwd=tap_dir, check=True)
                subprocess.run(
                    ["git", "commit", "-m", "Initial commit"],
                    cwd=tap_dir,
                    check=True
                )

            # Create GitHub repo (requires gh CLI)
            try:
                subprocess.run(
                    ["gh", "repo", "create", f"{tap_org}/{tap_repo}",
                     "--public", "--source=.", "--push"],
                    cwd=tap_dir,
                    check=True
                )
            except subprocess.CalledProcessError:
                # Repo might already exist, just push
                subprocess.run(
                    ["git", "remote", "add", "origin",
                     f"git@github.com:{tap_org}/{tap_repo}.git"],
                    cwd=tap_dir,
                    check=False  # Ignore if remote already exists
                )
                subprocess.run(
                    ["git", "push", "-u", "origin", "main"],
                    cwd=tap_dir,
                    check=True
                )

            logger.info(f"Homebrew tap published to GitHub")

            return AppStoreDeploymentResult(
                success=True,
                message=f"Tap published to https://github.com/{tap_org}/{tap_repo}",
                formula_url=f"https://github.com/{tap_org}/{tap_repo}"
            )

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to publish tap: {e}")
            return AppStoreDeploymentResult(
                success=False,
                message="Failed to publish Homebrew tap",
                error=str(e)
            )

    # ========================================================================
    # SNAP DEPLOYMENT (Linux)
    # ========================================================================

    def generate_snapcraft_yaml(
        self,
        project_slug: str,
        project_name: str,
        version: str,
        summary: str,
        description: str,
        confinement: str = "strict",
        base: str = "core22",
        python_packages: Optional[List[str]] = None
    ) -> str:
        """
        Generate snapcraft.yaml for Snap package.

        Args:
            project_slug: Project identifier
            project_name: Display name
            version: Version string
            summary: Short summary (max 79 chars)
            description: Long description
            confinement: 'strict', 'devmode', or 'classic'
            base: Snap base (core20, core22, etc.)
            python_packages: List of Python packages

        Returns:
            snapcraft.yaml content
        """
        python_packages = python_packages or []

        # Generate Python package list
        packages_yaml = "\n".join([f"      - {pkg}" for pkg in python_packages])

        yaml = f'''name: {project_slug}
version: '{version}'
summary: {summary}
description: |
  {description}

grade: stable
confinement: {confinement}
base: {base}

apps:
  {project_slug}:
    command: bin/{project_slug}
    plugs:
      - home
      - network
      - network-bind

parts:
  {project_slug}:
    plugin: python
    source: .
    python-packages:
{packages_yaml}
'''

        return yaml

    def build_snap(
        self,
        project_path: Path,
        snapcraft_yaml: str
    ) -> AppStoreDeploymentResult:
        """
        Build Snap package.

        Requires snapcraft to be installed.

        Args:
            project_path: Path to project directory
            snapcraft_yaml: snapcraft.yaml content

        Returns:
            AppStoreDeploymentResult with .snap file path
        """
        try:
            # Write snapcraft.yaml
            snapcraft_file = project_path / "snapcraft.yaml"
            with open(snapcraft_file, 'w') as f:
                f.write(snapcraft_yaml)

            logger.info(f"Building Snap package...")

            # Build snap
            result = subprocess.run(
                ["snapcraft"],
                cwd=project_path,
                capture_output=True,
                text=True,
                check=True
            )

            # Find generated .snap file
            snap_files = list(project_path.glob("*.snap"))
            if not snap_files:
                raise FileNotFoundError("No .snap file generated")

            snap_file = snap_files[0]

            logger.info(f"Snap package built: {snap_file}")

            return AppStoreDeploymentResult(
                success=True,
                message=f"Snap package built successfully",
                package_path=snap_file
            )

        except subprocess.CalledProcessError as e:
            logger.error(f"Snap build failed: {e.stderr}")
            return AppStoreDeploymentResult(
                success=False,
                message="Snap build failed",
                error=e.stderr
            )
        except FileNotFoundError as e:
            return AppStoreDeploymentResult(
                success=False,
                message="Snap build failed",
                error=str(e)
            )

    def publish_snap(
        self,
        snap_file: Path,
        channel: str = "stable"
    ) -> AppStoreDeploymentResult:
        """
        Publish Snap to Snap Store.

        Requires snapcraft login.

        Args:
            snap_file: Path to .snap file
            channel: Release channel (stable, candidate, beta, edge)

        Returns:
            AppStoreDeploymentResult
        """
        try:
            # Upload and release
            logger.info(f"Publishing Snap to {channel} channel...")

            subprocess.run(
                ["snapcraft", "upload", "--release", channel, str(snap_file)],
                check=True
            )

            logger.info("Snap published successfully")

            # Get snap name from filename
            snap_name = snap_file.stem.split('_')[0]

            return AppStoreDeploymentResult(
                success=True,
                message=f"Snap published to {channel} channel",
                store_url=f"https://snapcraft.io/{snap_name}"
            )

        except subprocess.CalledProcessError as e:
            logger.error(f"Snap publish failed: {e}")
            return AppStoreDeploymentResult(
                success=False,
                message="Snap publish failed",
                error=str(e)
            )

    # ========================================================================
    # MACOS APP STORE DEPLOYMENT
    # ========================================================================

    def create_macos_app_bundle(
        self,
        project_slug: str,
        project_name: str,
        version: str,
        executable_path: Path,
        icon_path: Optional[Path] = None,
        bundle_identifier: Optional[str] = None
    ) -> AppStoreDeploymentResult:
        """
        Create macOS .app bundle.

        Args:
            project_slug: Project identifier
            project_name: Display name
            version: Version string
            executable_path: Path to executable
            icon_path: Path to .icns icon file (optional)
            bundle_identifier: Bundle ID (e.g., com.yourcompany.app)

        Returns:
            AppStoreDeploymentResult with .app path
        """
        bundle_identifier = bundle_identifier or f"com.templedb.{project_slug}"

        # Create .app structure
        app_bundle = self.temp_dir / f"{project_name}.app"
        contents_dir = app_bundle / "Contents"
        macos_dir = contents_dir / "MacOS"
        resources_dir = contents_dir / "Resources"

        macos_dir.mkdir(parents=True, exist_ok=True)
        resources_dir.mkdir(exist_ok=True)

        # Copy executable
        shutil.copy(executable_path, macos_dir / project_slug)
        (macos_dir / project_slug).chmod(0o755)

        # Copy icon if provided
        if icon_path and icon_path.exists():
            shutil.copy(icon_path, resources_dir / "icon.icns")

        # Create Info.plist
        info_plist = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>{project_slug}</string>
    <key>CFBundleIdentifier</key>
    <string>{bundle_identifier}</string>
    <key>CFBundleName</key>
    <string>{project_name}</string>
    <key>CFBundleDisplayName</key>
    <string>{project_name}</string>
    <key>CFBundleVersion</key>
    <string>{version}</string>
    <key>CFBundleShortVersionString</key>
    <string>{version}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleIconFile</key>
    <string>icon</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.15</string>
</dict>
</plist>
'''

        with open(contents_dir / "Info.plist", 'w') as f:
            f.write(info_plist)

        logger.info(f"macOS app bundle created at {app_bundle}")

        return AppStoreDeploymentResult(
            success=True,
            message=f"macOS app bundle created",
            package_path=app_bundle
        )

    def sign_macos_app(
        self,
        app_bundle: Path,
        signing_identity: str,
        entitlements_path: Optional[Path] = None
    ) -> AppStoreDeploymentResult:
        """
        Code sign macOS app bundle.

        Requires:
        - macOS
        - Xcode Command Line Tools
        - Valid Developer ID certificate in Keychain

        Args:
            app_bundle: Path to .app bundle
            signing_identity: Signing identity (e.g., "Developer ID Application: Your Name")
            entitlements_path: Path to entitlements file (optional)

        Returns:
            AppStoreDeploymentResult
        """
        try:
            cmd = [
                "codesign",
                "--deep",
                "--force",
                "--verify",
                "--verbose",
                "--sign", signing_identity,
                "--options", "runtime"
            ]

            if entitlements_path:
                cmd.extend(["--entitlements", str(entitlements_path)])

            cmd.append(str(app_bundle))

            logger.info(f"Signing app bundle with {signing_identity}")

            subprocess.run(cmd, check=True)

            logger.info("App bundle signed successfully")

            return AppStoreDeploymentResult(
                success=True,
                message="App bundle signed successfully"
            )

        except subprocess.CalledProcessError as e:
            logger.error(f"Code signing failed: {e}")
            return AppStoreDeploymentResult(
                success=False,
                message="Code signing failed",
                error=str(e)
            )

    def notarize_macos_app(
        self,
        app_bundle: Path,
        apple_id: str,
        team_id: str,
        password: str
    ) -> AppStoreDeploymentResult:
        """
        Notarize macOS app with Apple.

        Args:
            app_bundle: Path to signed .app bundle
            apple_id: Apple ID email
            team_id: Team ID
            password: App-specific password

        Returns:
            AppStoreDeploymentResult
        """
        try:
            # Create ZIP for notarization
            zip_path = app_bundle.parent / f"{app_bundle.stem}.zip"

            subprocess.run(
                ["ditto", "-c", "-k", "--keepParent", str(app_bundle), str(zip_path)],
                check=True
            )

            logger.info(f"Submitting for notarization...")

            # Submit to Apple
            result = subprocess.run(
                [
                    "xcrun", "notarytool", "submit", str(zip_path),
                    "--apple-id", apple_id,
                    "--team-id", team_id,
                    "--password", password,
                    "--wait"
                ],
                capture_output=True,
                text=True,
                check=True
            )

            logger.info("Notarization successful")

            # Staple notarization ticket
            subprocess.run(
                ["xcrun", "stapler", "staple", str(app_bundle)],
                check=True
            )

            logger.info("Notarization ticket stapled")

            return AppStoreDeploymentResult(
                success=True,
                message="App notarized and stapled successfully"
            )

        except subprocess.CalledProcessError as e:
            logger.error(f"Notarization failed: {e.stderr}")
            return AppStoreDeploymentResult(
                success=False,
                message="Notarization failed",
                error=e.stderr
            )

    # ========================================================================
    # UTILITY FUNCTIONS
    # ========================================================================

    def calculate_sha256(self, file_path: Path) -> str:
        """Calculate SHA256 hash of file"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def create_tarball(
        self,
        source_dir: Path,
        output_path: Path,
        version: str
    ) -> Path:
        """
        Create source tarball for distribution.

        Args:
            source_dir: Source directory
            output_path: Output path (without extension)
            version: Version string

        Returns:
            Path to created tarball
        """
        tarball_name = f"{output_path.name}-{version}.tar.gz"
        tarball_path = output_path.parent / tarball_name

        subprocess.run(
            ["tar", "-czf", str(tarball_path), "-C", str(source_dir.parent), source_dir.name],
            check=True
        )

        logger.info(f"Tarball created: {tarball_path}")

        return tarball_path
