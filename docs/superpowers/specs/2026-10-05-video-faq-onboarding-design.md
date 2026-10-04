# Tutorial video on announcements, FAQ, and the owl's onboarding tour

Date: 2026-10-05
Status: design approved in conversation; spec awaiting review
Parts 2 to 4 of 4 (part 1, the TLE components, is done and deployed)

## Decisions (confirmed with the user)

- A video is attached to an announcement by an admin and plays in the announcement card.
- A Help (?) button in the top bar of every page opens an FAQ page written by Claude.
- New accounts get a one-time, step-by-step owl tour, tailored by role and replayable from the FAQ.

## Constraints found

- Production: Apache forwards `aligned.ddns.net` to gunicorn (no upload size limit, `Timeout 300`).
  gunicorn runs 3 sync workers with `--timeout 120`, so one long request (a large upload over a slow
  school connection) would be killed. Flask's `MAX_CONTENT_LENGTH` is 10 MB.
- VPS disk: 32 GB free.
- The owl must never be the chat's open/close control (unaffected here). No emoji icons: SVG only.

## Part 2: video on announcements

### Data
`Announcement` gets three nullable columns, added by the existing `_add_column` start-up migration:
`video_path` (VARCHAR 500), `video_name` (VARCHAR 255, the original filename), `video_size` (BIGINT).
`to_dict()` adds `has_video`, `video_name`, `video_size`, and `video_url` (`/api/announcements/<id>/video`)
when a video is attached.

### Upload (admin only)
- `POST /api/admin/announcements/<id>/video/chunks`, form fields `upload_id` (random token from the
  browser), `index`, `total`, and file `chunk` (at most 5 MB). Chunks are appended in order to
  `uploads/videos/tmp/<upload_id>.part`. A chunk out of order, or a running total over 500 MB, is
  rejected with 400 and the part file removed.
- On the last chunk the server checks the file's first bytes: MP4 (`ftyp` at offset 4) or WebM
  (`1A 45 DF A3`). A file that is neither is deleted and refused. A good file moves to
  `uploads/videos/announcement-<id>.<mp4|webm>`, replacing any earlier video, and the columns are set.
- `DELETE /api/admin/announcements/<id>/video` removes the file and clears the columns. Deleting an
  announcement deletes its video.
- `upload_id` must match `^[A-Za-z0-9_-]{8,64}$`, so it can't be used as a path.

### Viewing
`GET /api/announcements/<id>/video` (login required) streams the file with `send_file(conditional=True)`,
so seeking (HTTP Range) works. It is allowed only to someone the announcement is visible to: the same
audience rule `/announcements/active` uses, plus admins.

### Frontend
- Admin announcement form (`admin-announcements.html/js`): an "Attach video" file input (accept
  `video/mp4,video/webm`), the current video's name with Replace and Remove, and a progress bar
  during the chunked upload, which runs after the announcement itself is saved.
- Announcement cards (Announcements page and dashboard): when `has_video`, a
  `<video controls preload="none">` under the message, sized to the card.

## Part 3: FAQ and the Help button

- `api.js` adds a Help button (SVG question-mark icon, `aria-label="Help and FAQ"`) into
  `.topbar-actions` on every page that has one, before the bell when there is a bell. It links to
  `faq.html`.
- `faq.html` + `js/faq.js`: page header "Help and FAQ" with a search box and a "Replay the tour"
  button; questions in groups using native `<details>`/`<summary>`. The search filters questions and
  answers as you type and hides empty groups.
- Groups and content (written from how the app behaves now):
  1. Getting started (what AlignED does, roles, where things are)
  2. Formats (built-in formats, adding your own from a .docx or PDF, why some formats are locked)
  3. Making a plan (Setup, Building Proficiency vs Guided, the "Also write these for me?" list,
     ILAW's day-by-day fields, Lesson Title and Session No. being yours to fill, the live document and zoom)
  4. Course guides and subjects (official guides, the six subjects, uploading your own)
  5. Saving, drafts and exporting (drafts in List of Lesson Plans, Continue, Export as Word)
  6. Sections and submissions (teachers: creating sections and join codes; students: joining and submitting)
  7. Announcements and the tutorial video
  8. Your account (password, profile)
- Linked from the sidebar? No: the top-bar button is the one entry point (as decided).

## Part 4: the owl's onboarding tour

### Data
`User.onboarded_at` (DATETIME, nullable), added by migration; the migration then sets it to now for
every existing user that has none, so only accounts created after this release see the tour.
`/api/me` (the current-user payload) includes `onboarded` (bool). `POST /api/me/onboarded` sets it.

### Behaviour
- On the role's landing page (`dashboard.html` for students and teachers, `admin-dashboard.html` for
  admins), if `onboarded` is false or the URL has `?tour=1`, `js/owl-tour.js` starts the tour.
- The tour uses the existing owl (`OwlGuide`) element in a docked state: its bubble shows the step
  text, a step counter ("2 of 6"), and Back, Next (Finish on the last step) and Skip tour buttons.
  It does not time out.
- Each step may highlight a sidebar link (by its nav key) with an outline and scroll it into view;
  on phones, where the sidebar is collapsed, the step text names the menu item instead.
- Finish or Skip calls `POST /api/me/onboarded` (when it was a first run) and hides the owl.
- Steps (about six per role):
  - teacher: welcome; Create Lesson Plan (formats); List of Lesson Plans (drafts, Continue); My Sections
    and Submissions; Curriculum/Course Guide; Announcements (tutorial video) and the Help button.
  - student: welcome; Create Lesson Plan; List of Lesson Plans; My Classes (joining, submitting);
    Curriculum/Course Guide; Announcements and Help.
  - admin: welcome; Manage Users; Manage Sections; Documents; Announcements (posting a video); Help.
- The FAQ's "Replay the tour" opens the landing page with `?tour=1`.

## Testing (no AI calls)

- `backend/test_announcement_video.py`: chunks join into the stored file; a non-video is refused and
  leaves no file; a total over the limit is refused; out-of-order chunks are refused; a bad `upload_id`
  is refused; only admins may upload; viewing is allowed for the audience and refused for others;
  Range requests return 206; deleting the announcement removes the file.
- `backend/test_onboarding.py`: the migration marks existing users onboarded; a newly created user is
  not; `/api/me` reports it; `POST /api/me/onboarded` sets it.
- The full backend suite stays green. Browser check of the Help button, FAQ search, a tour run and a
  video upload and playback, then deploy (backup first).

## Out of scope

- Teachers attaching videos (admins only, as asked).
- Video transcoding or thumbnails (the browser plays MP4/WebM as uploaded).
- An admin editor for the FAQ.
