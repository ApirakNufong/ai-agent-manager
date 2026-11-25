-- Generated from backend/app/models.py. Runtime initialization creates these tables.

CREATE TABLE audit_logs (
	id VARCHAR(50) NOT NULL,
	timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
	"user" VARCHAR(100) NOT NULL,
	action VARCHAR(100) NOT NULL,
	entity VARCHAR(180) NOT NULL,
	"old" JSON NOT NULL,
	"new" JSON NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE configurations (
	id VARCHAR(180) NOT NULL,
	kind VARCHAR(30) NOT NULL,
	body JSON NOT NULL,
	PRIMARY KEY (id)
);

CREATE INDEX ix_configurations_kind ON configurations (kind);
CREATE TABLE datasets (
	id VARCHAR(50) NOT NULL,
	run_id VARCHAR(50) NOT NULL,
	source JSON NOT NULL,
	schema JSON NOT NULL,
	row_count INTEGER NOT NULL,
	path TEXT NOT NULL,
	lineage JSON NOT NULL,
	PRIMARY KEY (id)
);

CREATE INDEX ix_datasets_run_id ON datasets (run_id);
CREATE TABLE events (
	id VARCHAR(50) NOT NULL,
	topic VARCHAR(300) NOT NULL,
	run_id VARCHAR(50) NOT NULL,
	timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
	body JSON NOT NULL,
	processing VARCHAR(50) NOT NULL,
	PRIMARY KEY (id)
);

CREATE INDEX ix_events_run_id ON events (run_id);
CREATE TABLE executions (
	id VARCHAR(50) NOT NULL,
	run_id VARCHAR(50) NOT NULL,
	agent_id VARCHAR(100) NOT NULL,
	attempt INTEGER NOT NULL,
	status VARCHAR(30) NOT NULL,
	started TIMESTAMP WITH TIME ZONE NOT NULL,
	finished TIMESTAMP WITH TIME ZONE,
	result JSON NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (run_id, agent_id, attempt)
);

CREATE INDEX ix_executions_run_id ON executions (run_id);
CREATE TABLE heartbeats (
	id VARCHAR(100) NOT NULL,
	timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
	status VARCHAR(30) NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE runs (
	id VARCHAR(50) NOT NULL,
	workflow_id VARCHAR(100) NOT NULL,
	status VARCHAR(30) NOT NULL,
	current VARCHAR(100) NOT NULL,
	started TIMESTAMP WITH TIME ZONE NOT NULL,
	finished TIMESTAMP WITH TIME ZONE,
	snapshot JSON NOT NULL,
	context JSON NOT NULL,
	error JSON NOT NULL,
	PRIMARY KEY (id)
);
