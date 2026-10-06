-- Kanban statuses: 'To Do', 'In Progress', 'In Review', 'Completed'.
-- Renames the old 'Pending' status to 'To Do' and makes it the default for new tasks.
-- Run once against your existing database:  mysql -u root -p task_management < migrations/002_kanban_statuses.sql

UPDATE tasks SET status = 'To Do' WHERE status = 'Pending' OR status IS NULL OR status = '';

ALTER TABLE tasks
    MODIFY COLUMN status VARCHAR(20) NOT NULL DEFAULT 'To Do';
