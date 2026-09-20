#!/usr/bin/env node
/**
 * Todo API Server
 * Example project for TempleDB
 */

const express = require('express');
const cors = require('cors');
const Database = require('better-sqlite3');
require('dotenv').config();

const app = express();
const PORT = process.env.PORT || 3000;
const DB_PATH = process.env.DATABASE_URL || './todos.db';

// Middleware
app.use(cors());
app.use(express.json());

// Initialize database
const db = new Database(DB_PATH);
db.exec(`
  CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    completed BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
  )
`);

// API key middleware (simple auth for demo)
const requireAuth = (req, res, next) => {
  const apiKey = req.headers['x-api-key'];
  if (process.env.API_KEY && apiKey !== process.env.API_KEY) {
    return res.status(401).json({ error: 'Unauthorized' });
  }
  next();
};

// Routes

// GET /api/todos - List all todos
app.get('/api/todos', requireAuth, (req, res) => {
  try {
    const todos = db.prepare('SELECT * FROM todos ORDER BY created_at DESC').all();
    res.json({ todos, count: todos.length });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// POST /api/todos - Create a new todo
app.post('/api/todos', requireAuth, (req, res) => {
  try {
    const { title, description } = req.body;

    if (!title) {
      return res.status(400).json({ error: 'Title is required' });
    }

    const stmt = db.prepare(`
      INSERT INTO todos (title, description)
      VALUES (?, ?)
    `);

    const result = stmt.run(title, description || null);
    const todo = db.prepare('SELECT * FROM todos WHERE id = ?').get(result.lastInsertRowid);

    res.status(201).json({ todo });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// GET /api/todos/:id - Get a specific todo
app.get('/api/todos/:id', requireAuth, (req, res) => {
  try {
    const todo = db.prepare('SELECT * FROM todos WHERE id = ?').get(req.params.id);

    if (!todo) {
      return res.status(404).json({ error: 'Todo not found' });
    }

    res.json({ todo });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// PUT /api/todos/:id - Update a todo
app.put('/api/todos/:id', requireAuth, (req, res) => {
  try {
    const { title, description, completed } = req.body;

    const stmt = db.prepare(`
      UPDATE todos
      SET title = COALESCE(?, title),
          description = COALESCE(?, description),
          completed = COALESCE(?, completed),
          updated_at = CURRENT_TIMESTAMP
      WHERE id = ?
    `);

    const result = stmt.run(title, description, completed, req.params.id);

    if (result.changes === 0) {
      return res.status(404).json({ error: 'Todo not found' });
    }

    const todo = db.prepare('SELECT * FROM todos WHERE id = ?').get(req.params.id);
    res.json({ todo });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// DELETE /api/todos/:id - Delete a todo
app.delete('/api/todos/:id', requireAuth, (req, res) => {
  try {
    const stmt = db.prepare('DELETE FROM todos WHERE id = ?');
    const result = stmt.run(req.params.id);

    if (result.changes === 0) {
      return res.status(404).json({ error: 'Todo not found' });
    }

    res.status(204).send();
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'healthy', timestamp: new Date().toISOString() });
});

// Start server
app.listen(PORT, () => {
  console.log(`\n🏛️  Todo API Server`);
  console.log(`📍 Listening on http://localhost:${PORT}`);
  console.log(`💾 Database: ${DB_PATH}`);
  console.log(`🔐 Auth: ${process.env.API_KEY ? 'enabled' : 'disabled'}`);
  console.log(`\n📚 Endpoints:`);
  console.log(`   GET    /api/todos       - List todos`);
  console.log(`   POST   /api/todos       - Create todo`);
  console.log(`   GET    /api/todos/:id   - Get todo`);
  console.log(`   PUT    /api/todos/:id   - Update todo`);
  console.log(`   DELETE /api/todos/:id   - Delete todo`);
  console.log(`   GET    /health          - Health check\n`);
});

// Graceful shutdown
process.on('SIGINT', () => {
  console.log('\n👋 Shutting down gracefully...');
  db.close();
  process.exit(0);
});

module.exports = app;
