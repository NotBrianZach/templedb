# Todo API - TempleDB Example Project

A simple REST API for managing todos, demonstrating TempleDB project management.

## Features

- RESTful API with Express.js
- SQLite database for todos
- Environment configuration
- Deployment ready

## Project Structure

```
todo-api/
├── src/
│   ├── server.js         # Express server
│   ├── routes/           # API routes
│   │   └── todos.js
│   ├── models/           # Data models
│   │   └── todo.js
│   └── db/               # Database
│       └── schema.sql
├── tests/
│   └── api.test.js
├── package.json
├── .env.example
└── README.md
```

## API Endpoints

- `GET /api/todos` - List all todos
- `POST /api/todos` - Create a new todo
- `GET /api/todos/:id` - Get a specific todo
- `PUT /api/todos/:id` - Update a todo
- `DELETE /api/todos/:id` - Delete a todo

## Environment Variables

Required variables (use TempleDB secrets management):
- `DATABASE_URL` - SQLite database path
- `PORT` - Server port (default: 3000)
- `API_KEY` - API authentication key

## TempleDB Workflow

```bash
# Import project
templedb project import /path/to/todo-api

# Setup environment
templedb env detect todo-api
templedb env new todo-api dev

# Configure secrets
./prompt_missing_vars.sh todo-api dev

# Enter environment
templedb env enter todo-api dev

# Run development server
npm install
npm run dev
```

## Tracked by TempleDB

This project demonstrates:
- File tracking (JavaScript, JSON, SQL)
- Version control integration
- Environment management
- Secret handling
- Deployment configuration
