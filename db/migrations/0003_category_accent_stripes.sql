-- A class whose identity is more than one colour.
--
-- 0002 gave each class a single accent, on the reasonable assumption that a
-- championship has a colour. The NASCAR Cup Series has three - yellow, red and
-- blue, side by side - and picking one of them would be picking a third of a
-- logo. Xfinity and the Truck Series each have one, so they use the column
-- 0002 added and nothing here changes for them.
--
-- Nullable, and deliberately additive rather than a replacement:
-- `accent_color` stays the single colour, and stays authoritative everywhere a
-- single colour is what is wanted - a chip, a heading, a link. This column is
-- read only where the class's identity mark is actually drawn, and only to
-- split that mark into bands. A class with one colour leaves it NULL and every
-- surface behaves exactly as before.
--
-- Stored as a comma-separated list rather than a Postgres array on purpose:
-- it crosses into the web layer as one string on a row that is already being
-- selected, and an array would buy nothing but a driver-specific type.

ALTER TABLE categories
    ADD COLUMN accent_colors text;

COMMENT ON COLUMN categories.accent_colors IS
    'Comma-separated hex #rrggbb bands for the identity mark, in order. '
    'NULL means the mark is the single accent_color, which is the usual case.';

-- Two or more colours, or nothing. One colour here would be a duplicate of
-- accent_color and two places to change it.
ALTER TABLE categories
    ADD CONSTRAINT categories_accent_colors_hex_list
    CHECK (
        accent_colors IS NULL
        OR accent_colors ~ '^#[0-9A-Fa-f]{6}(,#[0-9A-Fa-f]{6})+$'
    );
