#!/usr/bin/env node
/**
 * ============================================================================
 * Extract SQL Objects from woofs.sql and populate sql_objects table
 * ============================================================================
 *
 * This script parses the woofs.sql file to extract information about:
 * - Tables
 * - Views
 * - Functions (PL/pgSQL, SQL, etc.)
 * - Triggers
 * - Types
 *
 * Usage: node populate_sql_objects.js [--dry-run]
 */

const fs = require('fs');
const path = require('path');
const Database = require('better-sqlite3');

const PROJECT_ROOT = __dirname;
const PROJECT_SLUG = 'woofs_projects';
const WOOFS_SQL_PATH = path.join(PROJECT_ROOT, 'woofsDB', 'woofs.sql');
const TEMPLEDB_PATH = process.env.TEMPLEDB_PATH || path.join(process.env.HOME, '.local/share/templedb/templedb.sqlite');
const DRY_RUN = process.argv.includes('--dry-run');

console.log('============================================================================');
console.log('Extracting SQL Objects from woofs.sql');
console.log('============================================================================');
console.log(`SQL File: ${WOOFS_SQL_PATH}`);
console.log(`Database: ${TEMPLEDB_PATH}`);
console.log(`Dry Run: ${DRY_RUN}`);
console.log('');

// SQL object patterns
const PATTERNS = {
    table: /CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+([\w.]+)\s*\(/gi,
    view: /CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+([\w.]+)\s+AS/gi,
    materializedView: /CREATE\s+MATERIALIZED\s+VIEW\s+([\w.]+)/gi,
    function: /CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+([\w.]+)\s*\(([\s\S]*?)\)\s+RETURNS\s+([\w\s\[\]]+)/gi,
    trigger: /CREATE\s+TRIGGER\s+([\w.]+)/gi,
    type: /CREATE\s+TYPE\s+([\w.]+)\s+AS\s+ENUM/gi,
};

function parseSchemaAndName(fullName) {
    const parts = fullName.split('.');
    if (parts.length === 2) {
        return { schema: parts[0], name: parts[1] };
    }
    return { schema: 'public', name: fullName };
}

function extractFunctionLanguage(sqlBlock) {
    const match = sqlBlock.match(/LANGUAGE\s+(\w+)/i);
    return match ? match[1].toLowerCase() : 'sql';
}

function extractParameters(paramString) {
    if (!paramString || paramString.trim() === '') {
        return [];
    }

    // Simple parameter parsing - can be improved
    const params = [];
    const paramMatches = paramString.match(/(\w+)\s+([\w\[\]]+(?:\s+DEFAULT\s+[^,]+)?)/gi);

    if (paramMatches) {
        paramMatches.forEach(param => {
            const [, name, type] = param.match(/(\w+)\s+([\w\[\]]+)/i) || [];
            if (name && type) {
                params.push({ name, type });
            }
        });
    }

    return params;
}

function hasRLS(tableName, sqlContent) {
    const rlsPattern = new RegExp(`ALTER\\s+TABLE\\s+${tableName.replace('.', '\\.')}\\s+ENABLE\\s+ROW\\s+LEVEL\\s+SECURITY`, 'i');
    return rlsPattern.test(sqlContent);
}

function extractRLSPolicies(tableName, sqlContent) {
    const policies = [];
    const policyPattern = new RegExp(
        `CREATE\\s+POLICY\\s+(\\w+)\\s+ON\\s+${tableName.replace('.', '\\.')}`,
        'gi'
    );

    let match;
    while ((match = policyPattern.exec(sqlContent)) !== null) {
        policies.push(match[1]);
    }

    return policies;
}

function hasForeignKeys(tableName, sqlContent) {
    const fkPattern = new RegExp(`REFERENCES\\s+\\w+`, 'i');

    // Find the CREATE TABLE block for this table
    const tableBlockPattern = new RegExp(
        `CREATE\\s+TABLE[^;]*?${tableName.replace('.', '\\.')}[\\s\\S]*?\\);`,
        'i'
    );
    const tableBlock = sqlContent.match(tableBlockPattern);

    if (tableBlock) {
        return fkPattern.test(tableBlock[0]);
    }

    return false;
}

function extractSqlObjects(sqlContent) {
    const objects = [];

    // Extract tables
    let match;
    const tablePattern = new RegExp(PATTERNS.table.source, PATTERNS.table.flags);
    while ((match = tablePattern.exec(sqlContent)) !== null) {
        const fullName = match[1];
        const { schema, name } = parseSchemaAndName(fullName);

        objects.push({
            objectType: 'table',
            schemaName: schema,
            objectName: name,
            fullName,
            hasRlsEnabled: hasRLS(fullName, sqlContent),
            rlsPolicies: extractRLSPolicies(fullName, sqlContent),
            hasForeignKeys: hasForeignKeys(fullName, sqlContent),
        });
    }

    // Extract views
    const viewPattern = new RegExp(PATTERNS.view.source, PATTERNS.view.flags);
    while ((match = viewPattern.exec(sqlContent)) !== null) {
        const fullName = match[1];
        const { schema, name } = parseSchemaAndName(fullName);

        objects.push({
            objectType: 'view',
            schemaName: schema,
            objectName: name,
            fullName,
        });
    }

    // Extract materialized views
    const matViewPattern = new RegExp(PATTERNS.materializedView.source, PATTERNS.materializedView.flags);
    while ((match = matViewPattern.exec(sqlContent)) !== null) {
        const fullName = match[1];
        const { schema, name } = parseSchemaAndName(fullName);

        objects.push({
            objectType: 'materialized_view',
            schemaName: schema,
            objectName: name,
            fullName,
            tableType: 'materialized_view',
        });
    }

    // Extract functions
    const functionPattern = new RegExp(PATTERNS.function.source, PATTERNS.function.flags);
    while ((match = functionPattern.exec(sqlContent)) !== null) {
        const fullName = match[1];
        const paramString = match[2];
        const returnType = match[3].trim();
        const { schema, name } = parseSchemaAndName(fullName);

        // Find the full function block to extract language
        const functionBlockStart = match.index;
        const functionBlockEnd = sqlContent.indexOf('$$;', functionBlockStart) + 3;
        const functionBlock = sqlContent.substring(functionBlockStart, functionBlockEnd);

        objects.push({
            objectType: 'function',
            schemaName: schema,
            objectName: name,
            fullName,
            functionLanguage: extractFunctionLanguage(functionBlock),
            returnType,
            parameters: extractParameters(paramString),
        });
    }

    // Extract triggers
    const triggerPattern = new RegExp(PATTERNS.trigger.source, PATTERNS.trigger.flags);
    while ((match = triggerPattern.exec(sqlContent)) !== null) {
        const fullName = match[1];
        const { schema, name } = parseSchemaAndName(fullName);

        objects.push({
            objectType: 'trigger',
            schemaName: schema,
            objectName: name,
            fullName,
        });
    }

    // Extract types (enums)
    const typePattern = new RegExp(PATTERNS.type.source, PATTERNS.type.flags);
    while ((match = typePattern.exec(sqlContent)) !== null) {
        const fullName = match[1];
        const { schema, name } = parseSchemaAndName(fullName);

        objects.push({
            objectType: 'type',
            schemaName: schema,
            objectName: name,
            fullName,
        });
    }

    return objects;
}

async function main() {
    // Read SQL file
    if (!fs.existsSync(WOOFS_SQL_PATH)) {
        console.error(`ERROR: SQL file not found at ${WOOFS_SQL_PATH}`);
        process.exit(1);
    }

    console.log('Reading SQL file...');
    const sqlContent = fs.readFileSync(WOOFS_SQL_PATH, 'utf8');
    console.log(`File size: ${(sqlContent.length / 1024).toFixed(2)} KB`);
    console.log('');

    // Extract objects
    console.log('Extracting SQL objects...');
    const objects = extractSqlObjects(sqlContent);
    console.log(`Found ${objects.length} SQL objects`);
    console.log('');

    // Group by type
    const byType = {};
    objects.forEach(obj => {
        byType[obj.objectType] = (byType[obj.objectType] || 0) + 1;
    });

    console.log('Object type distribution:');
    Object.entries(byType).sort((a, b) => b[1] - a[1]).forEach(([type, count]) => {
        console.log(`  ${type}: ${count}`);
    });
    console.log('');

    // Show some examples
    console.log('Sample objects:');
    const samples = {
        table: objects.find(o => o.objectType === 'table'),
        function: objects.find(o => o.objectType === 'function'),
        view: objects.find(o => o.objectType === 'view'),
    };

    Object.entries(samples).forEach(([type, obj]) => {
        if (obj) {
            console.log(`  ${type}: ${obj.fullName}`);
            if (obj.hasRlsEnabled) console.log(`    - RLS enabled`);
            if (obj.rlsPolicies?.length) console.log(`    - Policies: ${obj.rlsPolicies.join(', ')}`);
            if (obj.functionLanguage) console.log(`    - Language: ${obj.functionLanguage}`);
            if (obj.returnType) console.log(`    - Returns: ${obj.returnType}`);
        }
    });
    console.log('');

    if (DRY_RUN) {
        console.log('DRY RUN - No changes made to database');
        return;
    }

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

    // Get or create file entry for woofs.sql
    const sqlFileTypeId = db.prepare('SELECT id FROM file_types WHERE type_name = ?').get('sql_migration')?.id;

    let woofsFileId = db.prepare(
        'SELECT id FROM project_files WHERE project_id = ? AND file_path = ?'
    ).get(projectId, 'woofsDB/woofs.sql')?.id;

    if (!woofsFileId && sqlFileTypeId) {
        const result = db.prepare(`
            INSERT INTO project_files (project_id, file_type_id, file_path, file_name, component_name, status)
            VALUES (?, ?, ?, ?, ?, ?)
        `).run(projectId, sqlFileTypeId, 'woofsDB/woofs.sql', 'woofs.sql', 'woofs_schema', 'active');

        woofsFileId = result.lastInsertRowid;
        console.log(`Created file entry for woofs.sql (ID: ${woofsFileId})`);
    }

    if (!woofsFileId) {
        console.error('ERROR: Could not find or create file entry for woofs.sql');
        db.close();
        process.exit(1);
    }

    // Prepare insert statement
    const insertSqlObject = db.prepare(`
        INSERT OR REPLACE INTO sql_objects (
            file_id, object_type, schema_name, object_name,
            function_language, return_type, parameters,
            has_rls_enabled, rls_policies, has_foreign_keys
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);

    // Insert objects
    console.log('Inserting SQL objects into database...');
    let inserted = 0;

    db.prepare('BEGIN').run();

    try {
        for (const obj of objects) {
            insertSqlObject.run(
                woofsFileId,
                obj.objectType,
                obj.schemaName,
                obj.objectName,
                obj.functionLanguage || null,
                obj.returnType || null,
                obj.parameters ? JSON.stringify(obj.parameters) : null,
                obj.hasRlsEnabled ? 1 : 0,
                obj.rlsPolicies?.length ? JSON.stringify(obj.rlsPolicies) : null,
                obj.hasForeignKeys ? 1 : 0
            );

            inserted++;
        }

        db.prepare('COMMIT').run();
        console.log(`Successfully inserted ${inserted} SQL objects`);
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
    console.log('');
    console.log('Try these queries:');
    console.log('  # List all tables with RLS:');
    console.log(`  sqlite3 ${TEMPLEDB_PATH} "SELECT schema_name, object_name FROM sql_objects WHERE object_type='table' AND has_rls_enabled=1"`);
    console.log('');
    console.log('  # List all PL/pgSQL functions:');
    console.log(`  sqlite3 ${TEMPLEDB_PATH} "SELECT schema_name, object_name, return_type FROM sql_objects WHERE object_type='function' AND function_language='plpgsql'"`);
}

// Run
main().catch(error => {
    console.error('Fatal error:', error);
    process.exit(1);
});
