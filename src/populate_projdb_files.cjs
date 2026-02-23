#!/usr/bin/env node
/**
 * ============================================================================
 * Populate projdb with woofs_projects file information
 * ============================================================================
 *
 * This script scans the woofs_projects directory and populates the projdb
 * database with information about all project files, their types, and metadata.
 *
 * Usage: node populate_projdb_files.js [--dry-run]
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const Database = require('better-sqlite3');

// Configuration
const PROJECT_ROOT = __dirname;
const PROJECT_SLUG = 'woofs_projects';
const TEMPLEDB_PATH = process.env.TEMPLEDB_PATH || path.join(process.env.HOME, '.local/share/templedb/templedb.sqlite');
const DRY_RUN = process.argv.includes('--dry-run');

console.log('============================================================================');
console.log('Populating projdb with file information');
console.log('============================================================================');
console.log(`Project: ${PROJECT_SLUG}`);
console.log(`Project Root: ${PROJECT_ROOT}`);
console.log(`Database: ${TEMPLEDB_PATH}`);
console.log(`Dry Run: ${DRY_RUN}`);
console.log('');

// File type mappings
const FILE_TYPE_PATTERNS = [
    { pattern: /\.sql$/, typeName: 'sql_migration', testFunc: isSqlMigration },
    { pattern: /\.jsx$/, typeName: 'jsx_component' },
    { pattern: /\.tsx$/, typeName: 'tsx_component' },
    { pattern: /\.ts$/, typeName: 'typescript', testFunc: (p) => !p.includes('supabase/functions') },
    { pattern: /supabase\/functions\/.*\.(ts|js)$/, typeName: 'edge_function' },
    { pattern: /\.js$/, typeName: 'javascript' },
    { pattern: /\.css$/, typeName: 'css' },
    { pattern: /\.scss$/, typeName: 'scss' },
    { pattern: /Dockerfile$/, typeName: 'docker_file' },
    { pattern: /docker-compose\.ya?ml$/, typeName: 'docker_compose' },
    { pattern: /flake\.nix$/, typeName: 'nix_flake' },
    { pattern: /package\.json$/, typeName: 'package_json' },
    { pattern: /tsconfig\.json$/, typeName: 'tsconfig' },
    { pattern: /\.env/, typeName: 'env_file' },
    { pattern: /\.ya?ml$/, typeName: 'config_yaml' },
    { pattern: /\.json$/, typeName: 'config_json' },
    { pattern: /\.sh$/, typeName: 'shell_script' },
];

function isSqlMigration(filePath) {
    return filePath.includes('migration') || /^\d{3}_/.test(path.basename(filePath));
}

function getFileType(filePath) {
    const relativePath = path.relative(PROJECT_ROOT, filePath);

    for (const { pattern, typeName, testFunc } of FILE_TYPE_PATTERNS) {
        if (pattern.test(relativePath)) {
            if (testFunc && !testFunc(relativePath)) {
                continue;
            }
            return typeName;
        }
    }

    return null;
}

function getComponentName(filePath, content) {
    const ext = path.extname(filePath);
    const fileName = path.basename(filePath, ext);

    // Try to extract component/function name from content
    if (['.jsx', '.tsx', '.ts', '.js'].includes(ext)) {
        // React component
        const componentMatch = content.match(/(?:export\s+(?:default\s+)?(?:function|const)\s+)(\w+)|(?:function\s+)(\w+)/);
        if (componentMatch) {
            return componentMatch[1] || componentMatch[2];
        }
    }

    return fileName;
}

function getGitLastModified(filePath) {
    try {
        const result = execSync(
            `git log -1 --format=%ci "${filePath}"`,
            { cwd: PROJECT_ROOT, encoding: 'utf8' }
        ).trim();
        return result || null;
    } catch (e) {
        return null;
    }
}

function getGitLastCommit(filePath) {
    try {
        const result = execSync(
            `git log -1 --format=%H "${filePath}"`,
            { cwd: PROJECT_ROOT, encoding: 'utf8' }
        ).trim();
        return result || null;
    } catch (e) {
        return null;
    }
}

function getLinesOfCode(content) {
    return content.split('\n').length;
}

function scanDirectory(dir, excludePatterns = []) {
    const files = [];
    const defaultExcludes = [
        /node_modules/,
        /\.git\//,
        /dist\//,
        /build\//,
        /\.next\//,
        /coverage\//,
        /venv\//,
    ];

    const allExcludes = [...defaultExcludes, ...excludePatterns];

    function walk(currentPath) {
        const entries = fs.readdirSync(currentPath, { withFileTypes: true });

        for (const entry of entries) {
            const fullPath = path.join(currentPath, entry.name);
            const relativePath = path.relative(PROJECT_ROOT, fullPath);

            // Check exclusions
            if (allExcludes.some(pattern => pattern.test(relativePath))) {
                continue;
            }

            if (entry.isDirectory()) {
                walk(fullPath);
            } else if (entry.isFile()) {
                files.push(fullPath);
            }
        }
    }

    walk(dir);
    return files;
}

function analyzeFile(filePath) {
    const relativePath = path.relative(PROJECT_ROOT, filePath);
    const fileType = getFileType(filePath);

    if (!fileType) {
        return null; // Skip files we don't track
    }

    const stats = fs.statSync(filePath);
    const content = fs.readFileSync(filePath, 'utf8');

    return {
        filePath: relativePath,
        fileName: path.basename(filePath),
        fileType,
        componentName: getComponentName(filePath, content),
        lastModified: getGitLastModified(filePath) || stats.mtime.toISOString(),
        lastCommitHash: getGitLastCommit(filePath),
        linesOfCode: getLinesOfCode(content),
        status: 'active',
    };
}

async function main() {
    // Connect to database
    if (!fs.existsSync(TEMPLEDB_PATH)) {
        console.error(`ERROR: projdb database not found at ${TEMPLEDB_PATH}`);
        process.exit(1);
    }

    const db = new Database(TEMPLEDB_PATH);

    // Get project ID
    const project = db.prepare('SELECT id FROM projects WHERE slug = ?').get(PROJECT_SLUG);
    if (!project) {
        console.error(`ERROR: Project '${PROJECT_SLUG}' not found in database`);
        db.close();
        process.exit(1);
    }

    const projectId = project.id;
    console.log(`Found project ID: ${projectId}`);
    console.log('');

    // Scan files
    console.log('Scanning project files...');
    const allFiles = scanDirectory(PROJECT_ROOT);
    console.log(`Found ${allFiles.length} total files`);

    // Analyze and filter files
    console.log('Analyzing files...');
    const fileAnalyses = allFiles
        .map(analyzeFile)
        .filter(analysis => analysis !== null);

    console.log(`Analyzed ${fileAnalyses.length} trackable files`);
    console.log('');

    // Group by file type
    const byType = {};
    fileAnalyses.forEach(file => {
        byType[file.fileType] = (byType[file.fileType] || 0) + 1;
    });

    console.log('File type distribution:');
    Object.entries(byType).sort((a, b) => b[1] - a[1]).forEach(([type, count]) => {
        console.log(`  ${type}: ${count}`);
    });
    console.log('');

    if (DRY_RUN) {
        console.log('DRY RUN - No changes made to database');
        db.close();
        return;
    }

    // Prepare statements
    const getFileTypeId = db.prepare('SELECT id FROM file_types WHERE type_name = ?');
    const insertFile = db.prepare(`
        INSERT OR REPLACE INTO project_files (
            project_id, file_type_id, file_path, file_name, component_name,
            status, last_modified, last_commit_hash, lines_of_code
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);

    // Insert files
    console.log('Inserting files into database...');
    let inserted = 0;

    db.prepare('BEGIN').run();

    try {
        for (const file of fileAnalyses) {
            const fileTypeRow = getFileTypeId.get(file.fileType);
            if (!fileTypeRow) {
                console.warn(`Warning: Unknown file type '${file.fileType}' for ${file.filePath}`);
                continue;
            }

            insertFile.run(
                projectId,
                fileTypeRow.id,
                file.filePath,
                file.fileName,
                file.componentName,
                file.status,
                file.lastModified,
                file.lastCommitHash,
                file.linesOfCode
            );

            inserted++;
        }

        db.prepare('COMMIT').run();
        console.log(`Successfully inserted ${inserted} files`);
    } catch (error) {
        db.prepare('ROLLBACK').run();
        console.error('ERROR during insertion:', error.message);
        throw error;
    } finally {
        db.close();
    }

    console.log('');
    console.log('============================================================================');
    console.log('Done!');
    console.log('============================================================================');
}

// Run
main().catch(error => {
    console.error('Fatal error:', error);
    process.exit(1);
});
