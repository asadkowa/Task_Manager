-- Adds priority levels to existing tasks. Existing tasks become 'Medium'.
-- Run once against your existing database:  mysql -u root -p task_management < migrations/001_add_task_priority.sql

ALTER TABLE tasks
    ADD COLUMN priority ENUM('Urgent', 'High', 'Medium', 'Low') NOT NULL DEFAULT 'Medium' AFTER status,
    ADD INDEX idx_tasks_priority (priority);
