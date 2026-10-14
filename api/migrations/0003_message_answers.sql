-- Messages keep the full answer, so a conversation can be shown again and
-- "apply all fixes" can find the findings it is applying.
--   status: for an assistant message, the outcome (checked, clarify, reviewed, ...)
--   answer: everything shown with it (explanation, checks, findings, notes,
--           doc links, questions); for a user message, any extra input such
--           as the AmiBroker error text

alter table messages add column status text;
alter table messages add column answer jsonb;
