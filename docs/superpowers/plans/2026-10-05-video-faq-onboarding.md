# Video, FAQ and onboarding Implementation Plan

> Executed inline (the user said "approved start now").

**Spec:** `docs/superpowers/specs/2026-10-05-video-faq-onboarding-design.md`

## Global constraints
- No AI calls in testing. No new dependencies. SVG icons only, no emoji. No em dashes in UI copy.
- Python: `C:/tle/rel-Aligned/aligned/backend/venv/Scripts/python.exe`, tests run from `backend/`.
- Bump `?v=` on every page whose JS or CSS changed.

### Task 1: Video backend
Test first, `backend/test_announcement_video.py` (cases listed in the spec). Then:
- `Announcement.video_path/video_name/video_size` + `_add_column` migration; `to_dict` adds `has_video`, `video_name`,
  `video_size`, `video_url`.
- `routes/announcement_routes.py`: `POST /admin/announcements/<id>/video/chunks`, `DELETE /admin/announcements/<id>/video`,
  `GET /announcements/<id>/video` (audience check, `send_file(conditional=True)`); deleting an announcement removes its file.

### Task 2: Onboarding backend
Test first, `backend/test_onboarding.py`. Then `User.onboarded_at` + migration that marks existing users;
`to_dict` adds `onboarded`; `POST /api/me/onboarded`.

### Task 3: Frontend
- Video: admin form (file input, Replace/Remove, progress, chunked upload in `Api`), `<video>` in announcement cards
  (Announcements page and dashboard).
- Help button injected by `api.js` into `.topbar-actions`; `faq.html` + `js/faq.js` (groups, search, Replay the tour).
- `js/owl-tour.js` on `dashboard.html` and `admin-dashboard.html`: role-specific steps, Back/Next/Skip, sidebar highlight,
  marks onboarded on finish or skip.

### Task 4: Verify and deploy
Full backend suite once; browser check of the Help button, FAQ search, a tour run and a small video upload and playback;
backup, deploy, server check.
