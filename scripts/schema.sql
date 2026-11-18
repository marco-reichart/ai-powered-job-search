PRAGMA foreign_keys = ON;

-- =========================================================
-- 1. SAVED JOB SEARCHES
-- =========================================================

CREATE TABLE IF NOT EXISTS job_searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_archived INTEGER NOT NULL DEFAULT 0
        CHECK (is_archived IN (0, 1))
);


-- =========================================================
-- 2. VERSIONED SEARCH PROFILES
-- One profile version contains all four configurations.
-- =========================================================

CREATE TABLE IF NOT EXISTS search_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id INTEGER NOT NULL,

    version INTEGER NOT NULL,

    candidate_profile_json TEXT NOT NULL,
    discovery_config_json TEXT NOT NULL,
    filtering_config_json TEXT NOT NULL,
    evaluation_config_json TEXT NOT NULL,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER NOT NULL DEFAULT 1
        CHECK (is_active IN (0, 1)),

    FOREIGN KEY (search_id)
        REFERENCES job_searches(id)
        ON DELETE CASCADE,

    UNIQUE (search_id, version)
);

CREATE UNIQUE INDEX IF NOT EXISTS
    idx_one_active_profile_per_search
ON search_profiles(search_id)
WHERE is_active = 1;


-- =========================================================
-- 3. SEARCH RUNS
-- One execution of a saved search.
-- =========================================================

CREATE TABLE IF NOT EXISTS search_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id INTEGER NOT NULL,
    profile_id INTEGER NOT NULL,

    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,

    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN (
            'running',
            'completed',
            'completed_with_errors',
            'failed',
            'cancelled'
        )),

    jobs_found INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,

    FOREIGN KEY (search_id)
        REFERENCES job_searches(id),

    FOREIGN KEY (profile_id)
        REFERENCES search_profiles(id)
);


-- =========================================================
-- 4. DISCOVERY TASKS
-- Each category or title query is a separate task.
-- =========================================================

CREATE TABLE IF NOT EXISTS discovery_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_run_id INTEGER NOT NULL,

    source TEXT NOT NULL DEFAULT 'freehire',

    search_type TEXT NOT NULL
        CHECK (search_type IN (
            'category',
            'title',
            'manual'
        )),

    query_value TEXT,

    -- API parameters or manually entered listing data for this task.
    api_params_json TEXT,

    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,

    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN (
            'pending',
            'running',
            'completed',
            'failed',
            'cancelled'
        )),

    jobs_found INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,

    FOREIGN KEY (search_run_id)
        REFERENCES search_runs(id)
        ON DELETE CASCADE
);


-- =========================================================
-- 5. CANONICAL JOBS
-- One record for each unique real-world job opportunity.
-- =========================================================

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,

    normalized_title TEXT,
    normalized_company TEXT,
    normalized_location TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);


-- =========================================================
-- 6. JOB LISTINGS
-- Preserve every source listing, including duplicates.
-- =========================================================

CREATE TABLE IF NOT EXISTS job_listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    job_id INTEGER NOT NULL,

    source TEXT NOT NULL,
    external_id TEXT,
    url TEXT,

    title TEXT,
    company TEXT,
    location TEXT,

    work_mode TEXT,
    employment_type TEXT,

    description TEXT,

    raw_json TEXT,

    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (job_id)
        REFERENCES jobs(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS
    idx_unique_source_external_id
ON job_listings(source, external_id)
WHERE external_id IS NOT NULL;


-- =========================================================
-- 7. SEARCH RUN JOBS
-- Records what happened to a job in a particular run.
-- Multiple discovery tasks can find the same listing.
-- =========================================================

CREATE TABLE IF NOT EXISTS search_run_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    search_run_id INTEGER NOT NULL,
    discovery_task_id INTEGER,

    job_id INTEGER NOT NULL,
    listing_id INTEGER NOT NULL,

    processing_status TEXT NOT NULL DEFAULT 'found'
        CHECK (processing_status IN (
            'found',
            'duplicate',
            'filtered_out',
            'location_mismatch',
            'ready_for_evaluation',
            'evaluated',
            'evaluation_failed'
        )),

    processing_reason TEXT,

    duplicate_of_id INTEGER,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (search_run_id)
        REFERENCES search_runs(id)
        ON DELETE CASCADE,

    FOREIGN KEY (discovery_task_id)
        REFERENCES discovery_tasks(id),

    FOREIGN KEY (job_id)
        REFERENCES jobs(id),

    FOREIGN KEY (listing_id)
        REFERENCES job_listings(id),

    FOREIGN KEY (duplicate_of_id)
        REFERENCES search_run_jobs(id)
);

CREATE INDEX IF NOT EXISTS
    idx_search_run_jobs_run
ON search_run_jobs(search_run_id);

CREATE INDEX IF NOT EXISTS
    idx_search_run_jobs_job
ON search_run_jobs(job_id);

CREATE INDEX IF NOT EXISTS
    idx_search_run_jobs_status
ON search_run_jobs(processing_status);


-- =========================================================
-- 8. EVALUATION RUNS
-- Records the settings used for one LLM evaluation batch.
-- =========================================================

CREATE TABLE IF NOT EXISTS evaluation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    search_id INTEGER NOT NULL,
    search_run_id INTEGER,

    model_name TEXT NOT NULL,
    context_size INTEGER,
    temperature REAL,
    num_predict INTEGER,

    score_weights_json TEXT,
    prompt_version TEXT,

    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,

    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN (
            'running',
            'completed',
            'completed_with_errors',
            'failed',
            'cancelled'
        )),

    error_message TEXT,

    FOREIGN KEY (search_id)
        REFERENCES job_searches(id),

    FOREIGN KEY (search_run_id)
        REFERENCES search_runs(id)
);


-- =========================================================
-- 9. JOB EVALUATIONS
-- One evaluation per job per evaluation run.
-- =========================================================

CREATE TABLE IF NOT EXISTS job_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    evaluation_run_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,

    technical_skills_score REAL,
    experience_score REAL,
    role_relevance_score REAL,
    overall_score REAL,

    work_setup TEXT,
    job_location TEXT,
    office_attendance_required INTEGER,
    remote_scope TEXT,
    location_matches INTEGER,

    matching_skills_json TEXT,
    missing_skills_json TEXT,
    matching_responsibilities_json TEXT,

    explanation TEXT,
    location_explanation TEXT,

    raw_evaluation_json TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (evaluation_run_id)
        REFERENCES evaluation_runs(id)
        ON DELETE CASCADE,

    FOREIGN KEY (job_id)
        REFERENCES jobs(id),

    UNIQUE (evaluation_run_id, job_id),

    CHECK (
        technical_skills_score IS NULL OR
        technical_skills_score BETWEEN 0 AND 10
    ),

    CHECK (
        experience_score IS NULL OR
        experience_score BETWEEN 0 AND 10
    ),

    CHECK (
        role_relevance_score IS NULL OR
        role_relevance_score BETWEEN 0 AND 10
    ),

    CHECK (
        overall_score IS NULL OR
        overall_score BETWEEN 0 AND 100
    ),

    CHECK (
        office_attendance_required IS NULL OR
        office_attendance_required IN (0, 1)
    ),

    CHECK (
        location_matches IS NULL OR
        location_matches IN (0, 1)
    )
);

CREATE INDEX IF NOT EXISTS
    idx_job_evaluations_job
ON job_evaluations(job_id);

CREATE INDEX IF NOT EXISTS
    idx_job_evaluations_score
ON job_evaluations(overall_score);


-- =========================================================
-- 10. CURRENT APPLICATION STATUS
-- Separate from discovery and evaluation status.
-- =========================================================

CREATE TABLE IF NOT EXISTS job_application_statuses (
    job_id INTEGER PRIMARY KEY,

    status TEXT NOT NULL DEFAULT 'new'
        CHECK (status IN (
            'new',
            'not_interested',
            'interested',
            'to_apply',
            'applied',
            'interview',
            'offer',
            'rejected',
            'withdrawn',
            'hired'
        )),

    notes TEXT,

    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (job_id)
        REFERENCES jobs(id)
        ON DELETE CASCADE
);


-- =========================================================
-- 11. APPLICATION STATUS HISTORY
-- =========================================================

CREATE TABLE IF NOT EXISTS job_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    job_id INTEGER NOT NULL,

    old_status TEXT,
    new_status TEXT NOT NULL,

    changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,

    FOREIGN KEY (job_id)
        REFERENCES jobs(id)
        ON DELETE CASCADE
);


-- =========================================================
-- 12. ADDITIONAL INDEXES
-- =========================================================

CREATE INDEX IF NOT EXISTS
    idx_jobs_normalized_title_company
ON jobs(normalized_title, normalized_company);

CREATE INDEX IF NOT EXISTS
    idx_jobs_normalized_location
ON jobs(normalized_location);

CREATE INDEX IF NOT EXISTS
    idx_job_listings_job
ON job_listings(job_id);

CREATE INDEX IF NOT EXISTS
    idx_job_listings_source
ON job_listings(source);

CREATE INDEX IF NOT EXISTS
    idx_search_profiles_search
ON search_profiles(search_id);

CREATE INDEX IF NOT EXISTS
    idx_search_runs_search
ON search_runs(search_id);

CREATE INDEX IF NOT EXISTS
    idx_discovery_tasks_run
ON discovery_tasks(search_run_id);

CREATE INDEX IF NOT EXISTS
    idx_evaluation_runs_search
ON evaluation_runs(search_id);
