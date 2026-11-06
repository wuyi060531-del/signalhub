ALTER TABLE job_applications
 ADD COLUMN next_action text CHECK (char_length(next_action) <= 500);
