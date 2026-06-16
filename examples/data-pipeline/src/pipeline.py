#!/usr/bin/env python3
"""
Data Pipeline - Main Orchestrator
Example project for TempleDB
"""

import os
import sys
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

# Configure logging
logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DataPipeline:
    """Data pipeline orchestrator"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.warehouse_path = config.get('warehouse_path', 'data/warehouse.db')
        self.run_id = datetime.now().strftime('%Y%m%d_%H%M%S')

        logger.info(f"Initializing pipeline run: {self.run_id}")

    def extract(self) -> List[Dict[str, Any]]:
        """Extract data from sources"""
        logger.info("🔍 Extract stage started")

        # Simulated extraction
        data = [
            {'id': 1, 'name': 'Alice', 'value': 100},
            {'id': 2, 'name': 'Bob', 'value': 200},
            {'id': 3, 'name': 'Charlie', 'value': 150},
        ]

        logger.info(f"✅ Extracted {len(data)} records")
        return data

    def transform(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Transform and clean data"""
        logger.info("🔄 Transform stage started")

        # Simulated transformation
        transformed = []
        for record in data:
            transformed_record = {
                'id': record['id'],
                'name': record['name'].upper(),
                'value': record['value'] * 1.1,  # Apply 10% increase
                'category': 'HIGH' if record['value'] > 150 else 'NORMAL',
                'processed_at': datetime.now().isoformat()
            }
            transformed.append(transformed_record)

        logger.info(f"✅ Transformed {len(transformed)} records")
        return transformed

    def load(self, data: List[Dict[str, Any]]):
        """Load data into warehouse"""
        logger.info("💾 Load stage started")

        # Create warehouse database
        Path(self.warehouse_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.warehouse_path)
        cursor = conn.cursor()

        # Create table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS processed_data (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                value REAL NOT NULL,
                category TEXT NOT NULL,
                processed_at TIMESTAMP NOT NULL,
                run_id TEXT NOT NULL
            )
        """)

        # Insert data
        for record in data:
            cursor.execute("""
                INSERT INTO processed_data (id, name, value, category, processed_at, run_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                record['id'],
                record['name'],
                record['value'],
                record['category'],
                record['processed_at'],
                self.run_id
            ))

        conn.commit()
        conn.close()

        logger.info(f"✅ Loaded {len(data)} records to warehouse")

    def log_metrics(self, records_count: int, duration_sec: float):
        """Log pipeline metrics"""
        logger.info(f"📊 Pipeline Metrics:")
        logger.info(f"   Run ID: {self.run_id}")
        logger.info(f"   Records: {records_count}")
        logger.info(f"   Duration: {duration_sec:.2f}s")
        logger.info(f"   Records/sec: {records_count / duration_sec:.2f}")

    def run(self):
        """Run the complete pipeline"""
        logger.info(f"\n🏛️  TempleDB Data Pipeline")
        logger.info(f"📁 Run ID: {self.run_id}")
        logger.info(f"💾 Warehouse: {self.warehouse_path}\n")

        start_time = datetime.now()

        try:
            # Extract
            raw_data = self.extract()

            # Transform
            transformed_data = self.transform(raw_data)

            # Load
            self.load(transformed_data)

            # Metrics
            duration = (datetime.now() - start_time).total_seconds()
            self.log_metrics(len(transformed_data), duration)

            logger.info(f"\n✅ Pipeline completed successfully!")
            logger.info(f"📍 View data: sqlite3 {self.warehouse_path}\n")

            return 0

        except Exception as e:
            logger.error(f"\n❌ Pipeline failed: {e}")
            return 1

def main():
    """Main entry point"""

    config = {
        'warehouse_path': os.getenv('WAREHOUSE_PATH', 'data/warehouse.db'),
        'data_source_url': os.getenv('DATA_SOURCE_URL'),
        'api_key': os.getenv('API_KEY'),
    }

    pipeline = DataPipeline(config)
    return pipeline.run()

if __name__ == '__main__':
    sys.exit(main())
