-- База: threat_alerts

CREATE TABLE IF NOT EXISTS devices (
    id          SERIAL PRIMARY KEY,
    fcm_token   TEXT UNIQUE NOT NULL,
    name        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alerts (
    id          SERIAL PRIMARY KEY,
    threat_type TEXT NOT NULL,            -- 'fire' | 'fight' | 'smoke'
    detected_at TIMESTAMPTZ NOT NULL,     -- момент T
    video_path  TEXT NOT NULL,            -- шлях до mp4
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_alerts_detected_at ON alerts(detected_at);
CREATE INDEX IF NOT EXISTS idx_alerts_threat_type ON alerts(threat_type);

