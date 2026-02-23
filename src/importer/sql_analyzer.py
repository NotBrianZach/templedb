#!/usr/bin/env python3
"""
SQL schema analyzer - extracts database objects from SQL files
"""
import re
import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict


@dataclass
class SqlObject:
    """Represents a SQL database object"""
    object_type: str
    schema_name: str
    object_name: str
    full_name: str
    function_language: Optional[str] = None
    return_type: Optional[str] = None
    parameters: Optional[List[Dict]] = None
    has_rls_enabled: bool = False
    rls_policies: Optional[List[str]] = None
    has_foreign_keys: bool = False
    table_type: Optional[str] = None


class SqlAnalyzer:
    """Analyzes SQL files to extract database objects"""

    # Regex patterns for SQL objects
    PATTERNS = {
        'table': re.compile(r'CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+([\w.]+)\s*\(', re.IGNORECASE),
        'view': re.compile(r'CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+([\w.]+)\s+AS', re.IGNORECASE),
        'materialized_view': re.compile(r'CREATE\s+MATERIALIZED\s+VIEW\s+([\w.]+)', re.IGNORECASE),
        'function': re.compile(
            r'CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+([\w.]+)\s*\(([\s\S]*?)\)\s+RETURNS\s+([\w\s\[\]]+)',
            re.IGNORECASE
        ),
        'trigger': re.compile(r'CREATE\s+TRIGGER\s+([\w.]+)', re.IGNORECASE),
        'type': re.compile(r'CREATE\s+TYPE\s+([\w.]+)\s+AS\s+ENUM', re.IGNORECASE),
    }

    @staticmethod
    def parse_schema_and_name(full_name: str) -> Tuple[str, str]:
        """Parse schema and object name from full name"""
        parts = full_name.split('.')
        if len(parts) == 2:
            return parts[0], parts[1]
        return 'public', full_name

    @staticmethod
    def extract_function_language(sql_block: str) -> str:
        """Extract function language from SQL block"""
        match = re.search(r'LANGUAGE\s+(\w+)', sql_block, re.IGNORECASE)
        return match.group(1).lower() if match else 'sql'

    @staticmethod
    def extract_parameters(param_string: str) -> List[Dict]:
        """Extract function parameters"""
        if not param_string or not param_string.strip():
            return []

        params = []
        # Simple parameter parsing
        param_matches = re.findall(r'(\w+)\s+([\w\[\]]+)', param_string, re.IGNORECASE)

        for name, type_name in param_matches:
            params.append({'name': name, 'type': type_name})

        return params

    @staticmethod
    def has_rls(table_name: str, sql_content: str) -> bool:
        """Check if table has RLS enabled"""
        pattern = re.compile(
            rf'ALTER\s+TABLE\s+{re.escape(table_name)}\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY',
            re.IGNORECASE
        )
        return bool(pattern.search(sql_content))

    @staticmethod
    def extract_rls_policies(table_name: str, sql_content: str) -> List[str]:
        """Extract RLS policy names for a table"""
        policies = []
        pattern = re.compile(
            rf'CREATE\s+POLICY\s+(\w+)\s+ON\s+{re.escape(table_name)}',
            re.IGNORECASE
        )

        for match in pattern.finditer(sql_content):
            policies.append(match.group(1))

        return policies

    @staticmethod
    def has_foreign_keys(table_name: str, sql_content: str) -> bool:
        """Check if table has foreign keys"""
        # Find the CREATE TABLE block for this table
        table_pattern = re.compile(
            rf'CREATE\s+TABLE[^;]*?{re.escape(table_name)}[\s\S]*?\);',
            re.IGNORECASE
        )
        table_match = table_pattern.search(sql_content)

        if table_match:
            table_block = table_match.group(0)
            return bool(re.search(r'REFERENCES\s+\w+', table_block, re.IGNORECASE))

        return False

    @classmethod
    def analyze_sql_file(cls, file_path: Path) -> List[SqlObject]:
        """Analyze SQL file and extract all database objects"""
        sql_content = file_path.read_text(encoding='utf-8')
        objects = []

        # Extract tables
        for match in cls.PATTERNS['table'].finditer(sql_content):
            full_name = match.group(1)
            schema, name = cls.parse_schema_and_name(full_name)

            objects.append(SqlObject(
                object_type='table',
                schema_name=schema,
                object_name=name,
                full_name=full_name,
                has_rls_enabled=cls.has_rls(full_name, sql_content),
                rls_policies=cls.extract_rls_policies(full_name, sql_content),
                has_foreign_keys=cls.has_foreign_keys(full_name, sql_content)
            ))

        # Extract views
        for match in cls.PATTERNS['view'].finditer(sql_content):
            full_name = match.group(1)
            schema, name = cls.parse_schema_and_name(full_name)

            objects.append(SqlObject(
                object_type='view',
                schema_name=schema,
                object_name=name,
                full_name=full_name
            ))

        # Extract materialized views
        for match in cls.PATTERNS['materialized_view'].finditer(sql_content):
            full_name = match.group(1)
            schema, name = cls.parse_schema_and_name(full_name)

            objects.append(SqlObject(
                object_type='materialized_view',
                schema_name=schema,
                object_name=name,
                full_name=full_name,
                table_type='materialized_view'
            ))

        # Extract functions
        for match in cls.PATTERNS['function'].finditer(sql_content):
            full_name = match.group(1)
            param_string = match.group(2)
            return_type = match.group(3).strip()
            schema, name = cls.parse_schema_and_name(full_name)

            # Find full function block to extract language
            function_start = match.start()
            function_end_match = sql_content.find('$$;', function_start)
            if function_end_match == -1:
                function_end_match = sql_content.find(';', function_start)
            function_block = sql_content[function_start:function_end_match + 3]

            objects.append(SqlObject(
                object_type='function',
                schema_name=schema,
                object_name=name,
                full_name=full_name,
                function_language=cls.extract_function_language(function_block),
                return_type=return_type,
                parameters=cls.extract_parameters(param_string)
            ))

        # Extract triggers
        for match in cls.PATTERNS['trigger'].finditer(sql_content):
            full_name = match.group(1)
            schema, name = cls.parse_schema_and_name(full_name)

            objects.append(SqlObject(
                object_type='trigger',
                schema_name=schema,
                object_name=name,
                full_name=full_name
            ))

        # Extract types (enums)
        for match in cls.PATTERNS['type'].finditer(sql_content):
            full_name = match.group(1)
            schema, name = cls.parse_schema_and_name(full_name)

            objects.append(SqlObject(
                object_type='type',
                schema_name=schema,
                object_name=name,
                full_name=full_name
            ))

        return objects

    @staticmethod
    def get_type_distribution(objects: List[SqlObject]) -> Dict[str, int]:
        """Get distribution of SQL object types"""
        distribution = {}
        for obj in objects:
            distribution[obj.object_type] = distribution.get(obj.object_type, 0) + 1
        return dict(sorted(distribution.items(), key=lambda x: x[1], reverse=True))
