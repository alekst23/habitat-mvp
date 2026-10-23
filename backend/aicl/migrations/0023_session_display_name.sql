-- Optional display-only label. Existing identities, sessions and expiry remain intact.
ALTER TABLE session ADD COLUMN display_name TEXT CHECK (length(display_name) <= 64);
