-- Anonymous waitlist abuse counters only: no cleartext email addresses or IPs.
CREATE TABLE waitlist_rate_limit (
    bucket TEXT NOT NULL,
    window_start INTEGER NOT NULL,
    count INTEGER NOT NULL CHECK (count > 0),
    PRIMARY KEY (bucket, window_start)
);
