-- Per-class accent colour.
--
-- Colour has always carried series identity: a 3px rule at the left edge of a
-- row. Since Formula 2 and Formula 3 arrived, one weekend can hold four
-- championships, and painting all seventeen of its sessions the same red said
-- nothing about which of them was which.
--
-- Nullable on purpose. A headline class - Formula 1 within Formula 1, MotoGP
-- within MotoGP - has no colour of its own to state, and its series colour is
-- already correct. NULL means "inherit", which is resolved in the read query
-- rather than duplicated down every row here: a series changing its colour
-- should not need a data migration to carry the change into its classes.

ALTER TABLE categories
    ADD COLUMN accent_color text;

COMMENT ON COLUMN categories.accent_color IS
    'Hex #rrggbb. NULL inherits the parent series colour.';

ALTER TABLE categories
    ADD CONSTRAINT categories_accent_color_hex
    CHECK (accent_color IS NULL OR accent_color ~ '^#[0-9A-Fa-f]{6}$');
