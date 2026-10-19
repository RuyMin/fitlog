-- Frozen schema of user_version=2 (commit ff6bea0), generated from a fresh database.
-- Migration tests start from this file; never regenerate it from newer models.
CREATE TABLE body_metrics (
	id INTEGER NOT NULL, 
	measured_at DATETIME NOT NULL, 
	weight FLOAT, 
	body_fat FLOAT, 
	skeletal_muscle FLOAT, 
	memo TEXT, 
	external_id VARCHAR(200), 
	source VARCHAR(30) DEFAULT 'local' NOT NULL, 
	source_updated_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_body_weight CHECK (weight IS NULL OR weight > 0), 
	CONSTRAINT ck_body_fat CHECK (body_fat IS NULL OR body_fat BETWEEN 0 AND 100), 
	CONSTRAINT ck_body_muscle CHECK (skeletal_muscle IS NULL OR skeletal_muscle >= 0), 
	CONSTRAINT ck_body_value CHECK (weight IS NOT NULL OR body_fat IS NOT NULL OR skeletal_muscle IS NOT NULL)
);
CREATE TABLE excel_previews (
	token VARCHAR(64) NOT NULL, 
	payload TEXT NOT NULL, 
	original BLOB NOT NULL, 
	created_at DATETIME NOT NULL, 
	result TEXT, 
	PRIMARY KEY (token)
);
CREATE TABLE exercises (
	id INTEGER NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	category VARCHAR(100), 
	body_part VARCHAR(100), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_exercise_name CHECK (length(trim(name)) > 0), 
	UNIQUE (name)
);
CREATE TABLE import_archives (
	id INTEGER NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	filename VARCHAR(255) NOT NULL, 
	original BLOB NOT NULL, 
	payload TEXT NOT NULL, 
	report TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (sha256)
);
CREATE TABLE meals (
	id INTEGER NOT NULL, 
	eaten_at DATETIME NOT NULL, 
	meal_type VARCHAR(50) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	calories FLOAT, 
	protein FLOAT, 
	carbohydrates FLOAT, 
	fat FLOAT, 
	memo TEXT, 
	image_path VARCHAR(500), 
	image_url VARCHAR(2000), 
	created_at DATETIME NOT NULL, 
	external_id VARCHAR(200), 
	source VARCHAR(30) DEFAULT 'local' NOT NULL, 
	source_updated_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_meal_calories CHECK (calories IS NULL OR calories >= 0), 
	CONSTRAINT ck_meal_protein CHECK (protein IS NULL OR protein >= 0), 
	CONSTRAINT ck_meal_carbohydrates CHECK (carbohydrates IS NULL OR carbohydrates >= 0), 
	CONSTRAINT ck_meal_fat CHECK (fat IS NULL OR fat >= 0), 
	CONSTRAINT ck_meal_name CHECK (length(trim(name)) > 0)
);
CREATE TABLE sleep_records (
	id INTEGER NOT NULL, 
	sleep_start DATETIME NOT NULL, 
	sleep_end DATETIME NOT NULL, 
	duration_minutes INTEGER NOT NULL, 
	sleep_type VARCHAR(20) NOT NULL, 
	memo TEXT, 
	external_id VARCHAR(200), 
	source VARCHAR(30) DEFAULT 'local' NOT NULL, 
	source_updated_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_sleep_time CHECK (sleep_end > sleep_start), 
	CONSTRAINT ck_sleep_duration CHECK (duration_minutes >= 0), 
	CONSTRAINT ck_sleep_type CHECK (sleep_type IN ('main', 'nap'))
);
CREATE TABLE sync_state (
	id INTEGER NOT NULL, 
	spreadsheet_id VARCHAR(200), 
	spreadsheet_title VARCHAR(300), 
	last_sync_at DATETIME, 
	last_sync_status VARCHAR(30), 
	last_sync_error TEXT, 
	last_result TEXT, 
	PRIMARY KEY (id)
);
CREATE TABLE workout_sets (
	id INTEGER NOT NULL, 
	workout_id INTEGER NOT NULL, 
	exercise_id INTEGER NOT NULL, 
	set_number INTEGER NOT NULL, 
	weight FLOAT, 
	reps INTEGER, 
	completed BOOLEAN NOT NULL, 
	memo TEXT, 
	rpe FLOAT, 
	rir FLOAT, 
	external_id VARCHAR(200), 
	source VARCHAR(30) DEFAULT 'local' NOT NULL, 
	source_updated_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_set_number UNIQUE (workout_id, exercise_id, set_number), 
	CONSTRAINT ck_set_number CHECK (set_number > 0), 
	CONSTRAINT ck_set_weight CHECK (weight IS NULL OR weight >= 0), 
	CONSTRAINT ck_set_reps CHECK (reps IS NULL OR reps >= 0), 
	FOREIGN KEY(workout_id) REFERENCES workouts (id) ON DELETE CASCADE, 
	FOREIGN KEY(exercise_id) REFERENCES exercises (id) ON DELETE RESTRICT, 
	CHECK (completed IN (0, 1))
);
CREATE TABLE workouts (
	id INTEGER NOT NULL, 
	workout_date DATE NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	body_part VARCHAR(100), 
	started_at DATETIME, 
	ended_at DATETIME, 
	memo TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	external_id VARCHAR(200), 
	source VARCHAR(30) DEFAULT 'local' NOT NULL, 
	source_updated_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_workout_title CHECK (length(trim(title)) > 0), 
	CONSTRAINT ck_workout_time CHECK (ended_at IS NULL OR (started_at IS NOT NULL AND ended_at >= started_at))
);
CREATE INDEX ix_body_metrics_measured_at ON body_metrics (measured_at);
CREATE INDEX ix_meals_eaten_at ON meals (eaten_at);
CREATE INDEX ix_sleep_records_sleep_start ON sleep_records (sleep_start);
CREATE INDEX ix_workout_sets_exercise_id ON workout_sets (exercise_id);
CREATE INDEX ix_workout_sets_workout_id ON workout_sets (workout_id);
CREATE INDEX ix_workouts_workout_date ON workouts (workout_date);
CREATE UNIQUE INDEX uq_body_metrics_source_external ON body_metrics(source, external_id);
CREATE UNIQUE INDEX uq_meals_source_external ON meals(source, external_id);
CREATE UNIQUE INDEX uq_sleep_records_source_external ON sleep_records(source, external_id);
CREATE UNIQUE INDEX uq_workout_sets_source_external ON workout_sets(source, external_id);
CREATE UNIQUE INDEX uq_workouts_source_external ON workouts(source, external_id);
PRAGMA user_version=2;
