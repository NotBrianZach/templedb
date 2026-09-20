"""
Nix Flake Validation Service
=============================

Validates Nix flakes and extracts metadata for TempleDB projects.
"""

import json
import subprocess
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of a flake validation"""
    success: bool
    error: Optional[str] = None
    error_log: Optional[str] = None
    duration_seconds: Optional[float] = None


@dataclass
class FlakeMetadata:
    """Metadata extracted from a Nix flake"""
    packages: List[str]
    apps: List[str]
    devShells: List[str]
    nixosModules: List[str]
    homeManagerModules: List[str]
    overlays: List[str]
    inputs: Dict[str, Any]
    nixpkgs_commit: Optional[str]
    flake_lock_hash: Optional[str]
    raw_outputs: Dict[str, Any]


class NixValidationService:
    """Service for validating and analyzing Nix flakes"""

    def __init__(self, db):
        self.db = db

    def check_flake_exists(self, project_path: Path) -> bool:
        """Check if flake.nix exists in project"""
        flake_path = project_path / "flake.nix"
        return flake_path.exists()

    def validate_flake(self, project_path: Path, quick: bool = False) -> ValidationResult:
        """
        Validate a Nix flake

        Args:
            project_path: Path to the project directory
            quick: If True, skip build check (just validate structure)

        Returns:
            ValidationResult with success status and any errors
        """
        import time

        start_time = time.time()

        try:
            # Test 1: nix flake check
            logger.info(f"Validating flake at {project_path}")
            result = subprocess.run(
                ["nix", "flake", "check", "--no-build"],
                cwd=project_path,
                capture_output=True,
                timeout=60,
                text=True
            )

            if result.returncode != 0:
                duration = time.time() - start_time
                return ValidationResult(
                    success=False,
                    error=f"nix flake check failed",
                    error_log=result.stderr,
                    duration_seconds=duration
                )

            logger.info("✓ Flake structure is valid")

            # Test 2: nix build --dry-run (optional, only if not quick)
            if not quick:
                logger.info("Testing build dependencies...")
                result = subprocess.run(
                    ["nix", "build", "--dry-run"],
                    cwd=project_path,
                    capture_output=True,
                    timeout=120,
                    text=True
                )

                if result.returncode != 0:
                    duration = time.time() - start_time
                    return ValidationResult(
                        success=False,
                        error="Build dry-run failed",
                        error_log=result.stderr,
                        duration_seconds=duration
                    )

                logger.info("✓ Build dependencies resolved")

            duration = time.time() - start_time
            return ValidationResult(
                success=True,
                duration_seconds=duration
            )

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            return ValidationResult(
                success=False,
                error="Validation timed out",
                duration_seconds=duration
            )
        except Exception as e:
            duration = time.time() - start_time
            return ValidationResult(
                success=False,
                error=f"Validation error: {str(e)}",
                duration_seconds=duration
            )

    def extract_flake_metadata(self, project_path: Path) -> Optional[FlakeMetadata]:
        """
        Extract metadata from a Nix flake

        Returns:
            FlakeMetadata object or None if extraction fails
        """
        try:
            # Get flake metadata
            result = subprocess.run(
                ["nix", "flake", "metadata", "--json"],
                cwd=project_path,
                capture_output=True,
                timeout=30,
                text=True
            )

            if result.returncode != 0:
                logger.error(f"Failed to get flake metadata: {result.stderr}")
                return None

            metadata_json = json.loads(result.stdout)

            # Get flake outputs
            result = subprocess.run(
                ["nix", "flake", "show", "--json"],
                cwd=project_path,
                capture_output=True,
                timeout=30,
                text=True
            )

            outputs_json = {}
            if result.returncode == 0:
                outputs_json = json.loads(result.stdout)
            else:
                logger.warning(f"Could not get flake outputs: {result.stderr}")

            # Extract packages for x86_64-linux (TODO: support other systems)
            system = "x86_64-linux"
            packages = list(outputs_json.get("packages", {}).get(system, {}).keys())
            apps = list(outputs_json.get("apps", {}).get(system, {}).keys())
            devShells = list(outputs_json.get("devShells", {}).get(system, {}).keys())
            nixosModules = list(outputs_json.get("nixosModules", {}).keys())
            homeManagerModules = list(outputs_json.get("homeManagerModules", {}).keys())
            overlays = list(outputs_json.get("overlays", {}).keys())

            # Extract input information
            inputs = metadata_json.get("locks", {}).get("nodes", {})

            # Try to find nixpkgs commit
            nixpkgs_commit = None
            for node_name, node_data in inputs.items():
                if "nixpkgs" in node_name.lower():
                    locked = node_data.get("locked", {})
                    nixpkgs_commit = locked.get("rev") or locked.get("narHash")
                    break

            # Compute flake.lock hash
            flake_lock_path = project_path / "flake.lock"
            flake_lock_hash = None
            if flake_lock_path.exists():
                with open(flake_lock_path, 'rb') as f:
                    flake_lock_hash = hashlib.sha256(f.read()).hexdigest()

            return FlakeMetadata(
                packages=packages,
                apps=apps,
                devShells=devShells,
                nixosModules=nixosModules,
                homeManagerModules=homeManagerModules,
                overlays=overlays,
                inputs=inputs,
                nixpkgs_commit=nixpkgs_commit,
                flake_lock_hash=flake_lock_hash,
                raw_outputs=outputs_json
            )

        except subprocess.TimeoutExpired:
            logger.error("Timeout while extracting flake metadata")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse flake metadata JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Error extracting flake metadata: {e}")
            return None

    def store_flake_metadata(self, project_id: int, metadata: FlakeMetadata):
        """
        Store flake metadata in database

        Args:
            project_id: The project ID
            metadata: FlakeMetadata object to store
        """
        cursor = self.db.cursor()

        try:
            # Check if metadata already exists
            cursor.execute(
                "SELECT id FROM nix_flake_metadata WHERE project_id = ?",
                (project_id,)
            )
            existing = cursor.fetchone()

            if existing:
                # Update existing metadata
                cursor.execute("""
                    UPDATE nix_flake_metadata
                    SET packages = ?,
                        apps = ?,
                        devShells = ?,
                        nixosModules = ?,
                        homeManagerModules = ?,
                        overlays = ?,
                        flake_inputs = ?,
                        nixpkgs_commit = ?,
                        flake_lock_hash = ?,
                        nix_outputs_raw = ?,
                        updated_at = datetime('now')
                    WHERE project_id = ?
                """, (
                    json.dumps(metadata.packages),
                    json.dumps(metadata.apps),
                    json.dumps(metadata.devShells),
                    json.dumps(metadata.nixosModules),
                    json.dumps(metadata.homeManagerModules),
                    json.dumps(metadata.overlays),
                    json.dumps(metadata.inputs),
                    metadata.nixpkgs_commit,
                    metadata.flake_lock_hash,
                    json.dumps(metadata.raw_outputs),
                    project_id
                ))
            else:
                # Insert new metadata
                cursor.execute("""
                    INSERT INTO nix_flake_metadata
                    (project_id, packages, apps, devShells, nixosModules,
                     homeManagerModules, overlays, flake_inputs,
                     nixpkgs_commit, flake_lock_hash, nix_outputs_raw)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    project_id,
                    json.dumps(metadata.packages),
                    json.dumps(metadata.apps),
                    json.dumps(metadata.devShells),
                    json.dumps(metadata.nixosModules),
                    json.dumps(metadata.homeManagerModules),
                    json.dumps(metadata.overlays),
                    json.dumps(metadata.inputs),
                    metadata.nixpkgs_commit,
                    metadata.flake_lock_hash,
                    json.dumps(metadata.raw_outputs)
                ))

            self.db.commit()
            logger.info(f"✓ Stored flake metadata for project {project_id}")

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to store flake metadata: {e}")
            raise

    def store_validation_result(self, project_id: int, validation_type: str,
                                result: ValidationResult, nix_version: Optional[str] = None):
        """
        Store validation result in history

        Args:
            project_id: The project ID
            validation_type: Type of validation ('flake-check', 'build', 'build-dry-run')
            result: ValidationResult object
            nix_version: Optional Nix version string
        """
        cursor = self.db.cursor()

        try:
            cursor.execute("""
                INSERT INTO nix_flake_validation_history
                (project_id, validation_type, succeeded, error_message,
                 error_log, nix_version, duration_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                project_id,
                validation_type,
                result.success,
                result.error,
                result.error_log,
                nix_version,
                result.duration_seconds
            ))

            self.db.commit()

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to store validation result: {e}")
            raise

    def get_nix_version(self) -> Optional[str]:
        """Get installed Nix version"""
        try:
            result = subprocess.run(
                ["nix", "--version"],
                capture_output=True,
                timeout=5,
                text=True
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def validate_and_store(self, project_id: int, project_path: Path,
                          quick: bool = False) -> ValidationResult:
        """
        Validate flake and store all metadata

        Convenience method that runs validation, extracts metadata, and stores everything.

        Args:
            project_id: The project ID
            project_path: Path to the project directory
            quick: If True, skip build check

        Returns:
            ValidationResult
        """
        # Run validation
        validation_result = self.validate_flake(project_path, quick=quick)

        # Store validation result
        nix_version = self.get_nix_version()
        validation_type = "flake-check" if quick else "build-dry-run"
        self.store_validation_result(
            project_id,
            validation_type,
            validation_result,
            nix_version
        )

        # If validation successful, extract and store metadata
        if validation_result.success:
            metadata = self.extract_flake_metadata(project_path)
            if metadata:
                self.store_flake_metadata(project_id, metadata)

                # Update project table
                cursor = self.db.cursor()
                cursor.execute("""
                    UPDATE projects
                    SET flake_validated_at = datetime('now'),
                        flake_check_status = 'valid',
                        nix_build_status = 'untested'
                    WHERE id = ?
                """, (project_id,))
                self.db.commit()
        else:
            # Update project with failed status
            cursor = self.db.cursor()
            cursor.execute("""
                UPDATE projects
                SET flake_check_status = 'invalid',
                    nix_build_status = 'fails'
                WHERE id = ?
            """, (project_id,))
            self.db.commit()

        return validation_result
