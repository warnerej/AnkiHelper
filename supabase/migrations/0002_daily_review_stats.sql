-- Optional per-day stats reported by the add-on. Nullable so existing rows stay valid.
alter table public.daily_reviews
  add column retention     numeric(5,2) check (retention between 0 and 100),
  add column study_minutes numeric(7,2) check (study_minutes >= 0 and study_minutes <= 1440);
