#!/usr/bin/env node
/**
 * ============================================================================
 * Store File Contents in Database
 * ============================================================================
 *
 * Reads files from the project and stores their contents in the database
 * with version control.
 *
 * Usage: node populate_file_contents.cjs [--dry-run] [--project PROJECT_SLUG]
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { execSync } = require('child_process');
const Database = require('better-sqlite3');

// Configuration
const PROJECT_ROOT = process.env.PROJECT_ROOT || process.cwd();
const PROJECT_SLUG = process.env.PROJECT_SLUG || 'woofs_projects';
const TEMPLEDB_PATH = process.env.TEMPLEDB_PATH || path.join(process.env.HOME, '.local/share/templedb/templedb.sqlite');
const DRY_RUN = process.argv.includes('--dry-run');
const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB limit

console.log('============================================================================');
console.log('Storing File Contents in Database');
console.log('============================================================================');
console.log(`Project: ${PROJECT_SLUG}`);
console.log(`Project Root: ${PROJECT_ROOT}`);
console.log(`Database: ${TEMPLEDB_PATH}`);
console.log(`Dry Run: ${DRY_RUN}`);
console.log('');

// Binary file extensions
const BINARY_EXTENSIONS = new Set([
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.svg',
    '.pdf', '.zip', '.tar', '.gz', '.bz2', '.xz',
    '.exe', '.dll', '.so', '.dylib',
    '.woff', '.woff2', '.ttf', '.eot',
    '.mp3', '.mp4', '.avi', '.mov',
    '.db', '.sqlite', '.sqlite3'
]);

function isBinaryFile(filePath) {
    const ext = path.extname(filePath).toLowerCase();
    return BINARY_EXTENSIONS.has(ext);
}

function calculateHash(content) {
    return crypto.createHash('sha256').update(content).digest('hex');
}

function getGitAuthor() {
    try {
        const name = execSync('git config user.name', { encoding: 'utf8', cwd: PROJECT_ROOT }).trim();
        const email = execSync('git config user.email', { encoding: 'utf8', cwd: PROJECT_ROOT }).trim();
        return { name, email };
    } catch (e) {
        return { name: 'unknown', email: 'unknown@localhost' };
    }
}

function getGitCommitInfo(filePath) {
    try {
        const hash = execSync(
            `git log -1 --format=%H "${filePath}"`,
            { cwd: PROJECT_ROOT, encoding: 'utf8' }
        ).trim();

        const branch = execSync(
            'git rev-parse --abbrev-ref HEAD',
            { cwd: PROJECT_ROOT, encoding: 'utf8' }
        ).trim();

        return { hash, branch };
    } catch (e) {
        return { hash: null, branch: null };
    }
}

function readFileContent(filePath) {
    const stats = fs.statSync(filePath);

    if (stats.size > MAX_FILE_SIZE) {
        console.warn(`Skipping large file (${(stats.size / 1024 / 1024).toFixed(2)}MB): ${filePath}`);
        return null;
    }

    const isBinary = isBinaryFile(filePath);

    if (isBinary) {
        const content = fs.readFileSync(filePath);
        return {
            contentType: 'binary',
            content: content,
            encoding: null,
            size: content.length,
            lineCount: null,
            hash: calculateHash(content)
        };
    } else {
        try {
            const content = fs.readFileSync(filePath, 'utf8');
            const lineCount = content.split('\n').length;

            return {
                contentType: 'text',
                content: content,
                encoding: 'utf-8',
                size: Buffer.byteLength(content, 'utf8'),
                lineCount: lineCount,
                hash: calculateHash(content)
            };
        } catch (e) {
            // If UTF-8 fails, treat as binary
            const content = fs.readFileSync(filePath);
            return {
                contentType: 'binary',
                content: content,
                encoding: null,
                size: content.length,
                lineCount: null,
                hash: calculateHash(content)
            };
        }
    }
}

async function main() {
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

    // Get all tracked files
    const files = db.prepare(`
        SELECT id, file_path, file_name
        FROM project_files
        WHERE project_id = ?
    `).all(projectId);

    console.log(`Found ${files.length} tracked files`);
    console.log('');

    if (DRY_RUN) {
        console.log('DRY RUN - Would process:');
        files.slice(0, 10).forEach(file => {
            console.log(`  - ${file.file_path}`);
        });
        if (files.length > 10) {
            console.log(`  ... and ${files.length - 10} more`);
        }
        db.close();
        return;
    }

    // Prepare statements
    const insertContent = db.prepare(`
        INSERT OR REPLACE INTO file_contents (
            file_id, content_text, content_blob, content_type, encoding,
            file_size_bytes, line_count, hash_sha256, is_current
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
    `);

    // Note: Version history is now managed by VCS system (vcs_commits + vcs_file_states)
    // This script only populates file_contents with current state

    const getLatestHash = db.prepare(`
        SELECT hash_sha256 FROM file_contents WHERE file_id = ?
    `);

    // Get git author info
    const gitAuthor = getGitAuthor();
    const author = gitAuthor.name;

    let processed = 0;
    let skipped = 0;
    let errors = 0;

    console.log('Processing files...');

    db.prepare('BEGIN').run();

    try {
        for (const file of files) {
            const fullPath = path.join(PROJECT_ROOT, file.file_path);

            if (!fs.existsSync(fullPath)) {
                skipped++;
                continue;
            }

            try {
                const fileContent = readFileContent(fullPath);

                if (!fileContent) {
                    skipped++;
                    continue;
                }

                // Check if content has changed
                const existing = getLatestHash.get(file.id);
                const hasChanged = !existing || existing.hash_sha256 !== fileContent.hash;

                if (hasChanged) {
                    // Store current content
                    if (fileContent.contentType === 'text') {
                        insertContent.run(
                            file.id,
                            fileContent.content,
                            null,
                            fileContent.contentType,
                            fileContent.encoding,
                            fileContent.size,
                            fileContent.lineCount,
                            fileContent.hash
                        );
                    } else {
                        insertContent.run(
                            file.id,
                            null,
                            fileContent.content,
                            fileContent.contentType,
                            fileContent.encoding,
                            fileContent.size,
                            fileContent.lineCount,
                            fileContent.hash
                        );
                    }

                    // Version history is now managed by VCS system
                    // No need to create file_versions entries here
                }

                processed++;

                if (processed % 50 === 0) {
                    console.log(`  Processed ${processed}/${files.length} files...`);
                }

            } catch (err) {
                console.error(`Error processing ${file.file_path}:`, err.message);
                errors++;
            }
        }

        db.prepare('COMMIT').run();

        console.log('');
        console.log('============================================================================');
        console.log('Summary');
        console.log('============================================================================');
        console.log(`Total files: ${files.length}`);
        console.log(`Processed: ${processed}`);
        console.log('Note: Version history managed by VCS system');
        console.log(`Skipped: ${skipped}`);
        console.log(`Errors: ${errors}`);
        console.log('');

    } catch (error) {
        db.prepare('ROLLBACK').run();
        console.error('ERROR during processing:', error);
        throw error;
    } finally {
        db.close();
    }

    console.log('Done!');
}

main().catch(error => {
    console.error('Fatal error:', error);
    process.exit(1);
});
