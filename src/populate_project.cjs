#!/usr/bin/env node
/**
 * Generic script to populate any project into templedb
 * Usage: node populate_project.cjs <project_root> <project_slug>
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const Database = require('better-sqlite3');

// Get arguments
const PROJECT_ROOT = process.argv[2];
const PROJECT_SLUG = process.argv[3];

if (!PROJECT_ROOT || !PROJECT_SLUG) {
    console.error('Usage: node populate_project.cjs <project_root> <project_slug>');
    process.exit(1);
}

const TEMPLEDB_PATH = process.env.TEMPLEDB_PATH || path.join(process.env.HOME, '.local/share/templedb/templedb.sqlite');
const DRY_RUN = process.argv.includes('--dry-run');

console.log('============================================================================');
console.log('Populating templedb with file information');
console.log('============================================================================');
console.log(`Project: ${PROJECT_SLUG}`);
console.log(`Project Root: ${PROJECT_ROOT}`);
console.log(`Database: ${TEMPLEDB_PATH}`);
console.log(`Dry Run: ${DRY_RUN}`);
console.log('');

// File type mappings (order matters - more specific patterns first)
const FILE_TYPE_PATTERNS = [
    { pattern: /\.sql$/, typeName: 'sql_migration', testFunc: isSqlMigration },
    { pattern: /\.sql$/, typeName: 'sql_file' },  // Catch all SQL files
    { pattern: /\.jsx$/, typeName: 'jsx_component' },
    { pattern: /\.tsx$/, typeName: 'tsx_component' },
    { pattern: /\.ts$/, typeName: 'typescript', testFunc: (p) => !p.includes('supabase/functions') },
    { pattern: /supabase\/functions\/.*\.(ts|js)$/, typeName: 'edge_function' },
    { pattern: /\.cjs$/, typeName: 'javascript' },  // CommonJS files
    { pattern: /\.mjs$/, typeName: 'javascript' },  // ES Module files
    { pattern: /\.js$/, typeName: 'javascript' },
    { pattern: /\.css$/, typeName: 'css' },
    { pattern: /\.scss$/, typeName: 'scss' },
    { pattern: /\.html$/, typeName: 'html' },
    { pattern: /\.htm$/, typeName: 'html' },
    { pattern: /Dockerfile$/, typeName: 'docker_file' },
    { pattern: /docker-compose\.ya?ml$/, typeName: 'docker_compose' },
    { pattern: /flake\.nix$/, typeName: 'nix_flake' },
    { pattern: /package\.json$/, typeName: 'package_json' },
    { pattern: /tsconfig\.json$/, typeName: 'tsconfig' },
    { pattern: /\.env/, typeName: 'env_file' },
    { pattern: /\.ya?ml$/, typeName: 'config_yaml' },
    { pattern: /\.json$/, typeName: 'config_json' },
    { pattern: /\.sh$/, typeName: 'shell_script' },
    { pattern: /\.py$/, typeName: 'python' },
    { pattern: /README\.md/i, typeName: 'markdown' },  // README files as markdown
    { pattern: /\.md$/, typeName: 'markdown' },
];

function isSqlMigration(filePath) {
    return filePath.includes('migrations/') || filePath.includes('migration');
}

function getFileType(filePath) {
    const relativePath = path.relative(PROJECT_ROOT, filePath);
    for (const { pattern, typeName, testFunc } of FILE_TYPE_PATTERNS) {
        if (pattern.test(relativePath)) {
            if (testFunc && !testFunc(relativePath)) continue;
            return typeName;
        }
    }
    return null;
}

function getComponentName(filePath, content) {
    const ext = path.extname(filePath);
    const fileName = path.basename(filePath, ext);

    if (['.jsx', '.tsx', '.ts', '.js'].includes(ext)) {
        const componentMatch = content.match(/(?:export\s+(?:default\s+)?(?:function|const)\s+)(\w+)|(?:function\s+)(\w+)/);
        if (componentMatch) {
            return componentMatch[1] || componentMatch[2];
        }
    }

    return fileName;
}

function getGitInfo(filePath) {
    try {
        const relPath = path.relative(PROJECT_ROOT, filePath);
        const hash = execSync(`cd "${PROJECT_ROOT}" && git log -1 --format=%H -- "${relPath}"`, { encoding: 'utf8' }).trim();
        const author = execSync(`cd "${PROJECT_ROOT}" && git log -1 --format=%an -- "${relPath}"`, { encoding: 'utf8' }).trim();
        const timestamp = execSync(`cd "${PROJECT_ROOT}" && git log -1 --format=%ai -- "${relPath}"`, { encoding: 'utf8' }).trim();

        return { hash, author, timestamp };
    } catch (e) {
        return { hash: null, author: null, timestamp: null };
    }
}

function countLines(content) {
    return content.split('\n').length;
}

function walkDir(dir, fileList = []) {
    const files = fs.readdirSync(dir);

    for (const file of files) {
        const filePath = path.join(dir, file);

        // Skip common ignore patterns
        if (file === 'node_modules' || file === '.git' || file === 'venv' ||
            file === '__pycache__' || file === 'dist' || file === 'build' ||
            file === '.direnv' || file === '.next' || file === 'target') {
            continue;
        }

        let stat;
        try {
            stat = fs.statSync(filePath);
        } catch (e) {
            // Skip broken symlinks or inaccessible files
            continue;
        }

        if (stat.isDirectory()) {
            walkDir(filePath, fileList);
        } else {
            fileList.push(filePath);
        }
    }

    return fileList;
}

// Main execution
const db = Database(TEMPLEDB_PATH);

// Get project ID
const project = db.prepare('SELECT id FROM projects WHERE slug = ?').get(PROJECT_SLUG);
if (!project) {
    console.error(`Error: Project '${PROJECT_SLUG}' not found in database`);
    process.exit(1);
}

const projectId = project.id;
console.log(`Found project ID: ${projectId}\n`);

// Get file type IDs
const fileTypes = {};
const fileTypeRows = db.prepare('SELECT id, type_name FROM file_types').all();
for (const row of fileTypeRows) {
    fileTypes[row.type_name] = row.id;
}

console.log('Scanning project files...');
const allFiles = walkDir(PROJECT_ROOT);
console.log(`Found ${allFiles.length} total files`);

console.log('Analyzing files...');
const filesToInsert = [];
const typeDistribution = {};

for (const filePath of allFiles) {
    const typeName = getFileType(filePath);
    if (!typeName || !fileTypes[typeName]) continue;

    try {
        const content = fs.readFileSync(filePath, 'utf8');
        const relativePath = path.relative(PROJECT_ROOT, filePath);
        const componentName = getComponentName(filePath, content);
        const lineCount = countLines(content);
        const gitInfo = getGitInfo(filePath);

        filesToInsert.push({
            projectId,
            fileTypeId: fileTypes[typeName],
            filePath: relativePath,
            fileName: path.basename(filePath),
            componentName,
            linesOfCode: lineCount,
            lastCommitHash: gitInfo.hash,
            typeName
        });

        typeDistribution[typeName] = (typeDistribution[typeName] || 0) + 1;
    } catch (e) {
        // Skip binary files or files that can't be read as text
    }
}

console.log(`Analyzed ${filesToInsert.length} trackable files\n`);

console.log('File type distribution:');
for (const [type, count] of Object.entries(typeDistribution).sort((a, b) => b[1] - a[1])) {
    console.log(`  ${type}: ${count}`);
}
console.log('');

if (DRY_RUN) {
    console.log('Dry run - no changes made');
    process.exit(0);
}

console.log('Inserting files into database...');

const insertStmt = db.prepare(`
    INSERT OR REPLACE INTO project_files
    (project_id, file_type_id, file_path, file_name, component_name, lines_of_code, last_commit_hash, status)
    VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
`);

const insertMany = db.transaction((files) => {
    for (const file of files) {
        insertStmt.run(
            file.projectId,
            file.fileTypeId,
            file.filePath,
            file.fileName,
            file.componentName,
            file.linesOfCode,
            file.lastCommitHash
        );
    }
});

insertMany(filesToInsert);

console.log(`Successfully inserted ${filesToInsert.length} files\n`);

db.close();

console.log('============================================================================');
console.log('Done!');
console.log('============================================================================');
