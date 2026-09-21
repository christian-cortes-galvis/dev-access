-- Esquema del portal de administración de copias (backupcsr).
-- Idempotente: la app lo aplica al arrancar (db.init_schema, no requiere cliente mysql).
-- Cada sentencia termina en punto y coma y no contiene ese caracter dentro.

CREATE TABLE IF NOT EXISTS users (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  username VARCHAR(64) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  role ENUM('admin','viewer') NOT NULL DEFAULT 'viewer',
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_users_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS jobs (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  slug VARCHAR(64) NOT NULL,
  name VARCHAR(128) NOT NULL,
  description VARCHAR(255) NOT NULL DEFAULT '',
  origin_type ENUM('ftp','sftp','sftp_pass') NOT NULL DEFAULT 'ftp',
  source VARCHAR(255) NOT NULL DEFAULT '',
  dest_rel VARCHAR(255) NOT NULL DEFAULT '',
  lockfile VARCHAR(255) NOT NULL DEFAULT '',
  enabled TINYINT(1) NOT NULL DEFAULT 1,
  cron_minute VARCHAR(32) NOT NULL DEFAULT '20',
  cron_hour VARCHAR(64) NOT NULL DEFAULT '6-19',
  cron_dom VARCHAR(32) NOT NULL DEFAULT '*',
  cron_month VARCHAR(32) NOT NULL DEFAULT '*',
  cron_dow VARCHAR(32) NOT NULL DEFAULT '*',
  sort INT NOT NULL DEFAULT 100,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_jobs_slug (slug)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS runs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  job_id INT UNSIGNED NOT NULL,
  started_at DATETIME NOT NULL,
  finished_at DATETIME NULL,
  status ENUM('OK','FALLO','EN_CURSO','INCIERTO') NOT NULL DEFAULT 'INCIERTO',
  dry_run TINYINT(1) NOT NULL DEFAULT 0,
  exit_code INT NULL,
  files_transferred INT NOT NULL DEFAULT 0,
  files_removed INT NOT NULL DEFAULT 0,
  error_text VARCHAR(1024) NULL,
  triggered_by ENUM('cron','manual') NOT NULL DEFAULT 'cron',
  log_path VARCHAR(255) NOT NULL DEFAULT '',
  truncated TINYINT(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY uq_runs_job_start (job_id, started_at),
  KEY idx_runs_job_start (job_id, started_at),
  CONSTRAINT fk_runs_job FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS run_files (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  run_id BIGINT UNSIGNED NOT NULL,
  path VARCHAR(512) NOT NULL,
  action ENUM('transfer','remove') NOT NULL DEFAULT 'transfer',
  PRIMARY KEY (id),
  KEY idx_run_files_run (run_id),
  CONSTRAINT fk_run_files_run FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS size_snapshots (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  job_id INT UNSIGNED NOT NULL,
  taken_at DATETIME NOT NULL,
  bytes BIGINT UNSIGNED NOT NULL DEFAULT 0,
  files INT UNSIGNED NOT NULL DEFAULT 0,
  run_id BIGINT UNSIGNED NULL,
  truncated TINYINT(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY uq_size_job_taken (job_id, taken_at),
  KEY idx_size_taken (taken_at),
  KEY idx_size_run (run_id),
  CONSTRAINT fk_size_job FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS audit_log (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  username VARCHAR(64) NOT NULL,
  action VARCHAR(64) NOT NULL,
  job_slug VARCHAR(64) NULL,
  detail_json TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_audit_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
