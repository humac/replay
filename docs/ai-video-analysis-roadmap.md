# AI Video Analysis Roadmap

This roadmap extends `docs/coaching-analysis-feature-roadmap.md` with a practical plan for computer-vision assisted soccer analysis.

The goal is not to replace the coach. The goal is to help the coach find useful moments faster, visualize player/team behavior, and eventually produce player-specific review clips and performance summaries.

This roadmap should start after the Coach Review cockpit work in `docs/coach-review-ui-ux-implementation-plan.md` is complete and after the manual coaching workflow in `docs/coaching-analysis-feature-roadmap.md` has at least structured notes, templates, thumbnails, clips, and player profiles.

## Candidate model

Candidate external model:

- Roboflow Universe football player detection model:
  - `https://universe.roboflow.com/roboflow-jvuqo/football-players-detection-3zvbc`

Important caveat:

- Treat this as a candidate detector, not a guaranteed production dependency.
- Before implementation, verify the model license, API terms, current availability, inference cost, rate limits, export options, and performance on your actual match footage.
- The model appears relevant for player detection, but Replay should be designed so the detector can be swapped later.

## Product vision

Replay should eventually support three AI/video-analysis layers:

1. Detection
   - find players, ball if available, officials if available, and maybe teams by kit color

2. Tracking
   - follow detected players across frames
   - maintain track IDs
   - handle occlusion, missed detections, and camera motion

3. Coaching intelligence
   - convert detections/tracks into useful coach-facing moments, visuals, clips, and player development signals

The useful output is not raw bounding boxes. The useful output is:

- candidate clips
- player highlights
- formation snapshots
- heatmaps
- tactical shape changes
- possession sequences
- reviewable moments
- player/team development insights

---

# Recommended implementation order

Do not start with real-time broadcasting overlays or advanced physical KPIs. Start with offline analysis and human review.

Best order:

1. Detection ingestion framework
2. Offline video analysis job runner
3. Player detection overlay in Coach Review
4. Track generation and smoothing
5. Detected moments review queue
6. Clip creation from accepted moments
7. Tactical shape snapshots
8. Player/zone heatmaps
9. Semi-automatic player identification
10. Physical KPI estimates with confidence warnings
11. Broadcast/stat-tag overlays
12. Live/near-live analysis, only if offline analysis is reliable

---

# Phase 1: Detection ingestion framework

## Goal

Add a detector-agnostic data model so Replay can store outputs from Roboflow or any future model.

## Why first

Do not hard-code Roboflow into the core coaching workflow. The platform should store normalized detections regardless of which model produced them.

## Data model

Add tables similar to:

### `video_analysis_jobs`

Fields:

- `id`
- `match_id`
- `slot`
- `source_video_path`
- `status`: queued, running, completed, failed, cancelled
- `provider`: roboflow, local_yolo, soccer360, manual_import
- `model_name`
- `model_version`
- `frame_sample_rate`
- `started_at`
- `completed_at`
- `error_code`
- `error_message`
- `metadata_json`

### `video_detections`

Fields:

- `id`
- `job_id`
- `match_id`
- `slot`
- `frame_index`
- `timestamp_seconds`
- `class_name`: player, ball, referee, goalkeeper, unknown
- `confidence`
- `x_center`
- `y_center`
- `width`
- `height`
- `normalized`: boolean, should be true for 0..1 coordinates
- `track_id`: nullable initially
- `metadata_json`

### `video_tracks`

Fields:

- `id`
- `job_id`
- `match_id`
- `slot`
- `track_id`
- `class_name`
- `team_label`: home, away, keeper_home, keeper_away, referee, unknown
- `player_id`: nullable until linked to roster
- `jersey_number`: nullable
- `start_seconds`
- `end_seconds`
- `confidence`
- `metadata_json`

## API endpoints

Coach/admin only:

- `GET /api/coach/analysis/jobs?match_id=&slot=`
- `POST /api/coach/analysis/jobs`
- `GET /api/coach/analysis/jobs/{id}`
- `DELETE /api/coach/analysis/jobs/{id}` or cancel
- `GET /api/coach/analysis/detections?match_id=&slot=&t0=&t1=`
- `GET /api/coach/analysis/tracks?match_id=&slot=&t0=&t1=`

## Acceptance criteria

- Replay can store detections from any provider.
- Detection records use normalized video coordinates.
- No detections are player-facing by default.
- Job status and errors are visible to coach/admin.
- Existing playback and coaching notes are unaffected.

## Coding agent prompt

```text
Add a detector-agnostic video analysis data model to Replay. Create video_analysis_jobs, video_detections, and video_tracks tables through a migration. Add Pydantic models and coach/admin-only endpoints to create/list/read/cancel analysis jobs and query detections/tracks by match, slot, and time range. Do not integrate Roboflow yet. Do not expose analysis outputs to My Feedback. Store normalized coordinates so overlays can render correctly over the existing video player and coach drawing canvas.
```

---

# Phase 2: Offline analysis job runner

## Goal

Run player detection offline against uploaded match videos.

## Why offline first

Offline analysis is safer, cheaper, and easier to validate. Live analysis should come later.

## Job flow

1. Coach/admin clicks Analyze Match.
2. Backend creates `video_analysis_jobs` row.
3. Background worker samples frames from the video.
4. Worker sends frames to provider or local detector.
5. Worker stores normalized detections.
6. Job status updates to completed or failed.

## Provider abstraction

Create an analysis provider interface similar to:

```python
class DetectionProvider:
    name: str

    async def detect_frame(self, frame_image) -> list[DetectionResult]:
        ...
```

Provider candidates:

- `roboflow_api`
- `local_yolo`
- `soccer360_import`
- `mock_provider` for tests

## Roboflow integration considerations

Before implementation, verify:

- model license
- API authentication method
- export/runtime options
- whether commercial/team use is permitted
- rate limits
- per-image/video inference cost
- whether inference can run locally
- data/privacy implications of sending youth sports footage to a third party

## Sampling strategy

Start conservative:

- 1 frame per second for MVP
- configurable later: 1 fps, 2 fps, 5 fps
- store video width/height metadata
- normalize coordinates to 0..1

Do not process every frame initially. Full-frame analysis of long matches can get expensive fast.

## Acceptance criteria

- Coach/admin can queue an analysis job for a ready match slot.
- Job runs asynchronously.
- Job stores detections.
- Job failure is visible and does not break match playback.
- Mock provider tests exist.

## Coding agent prompt

```text
Implement the offline video analysis job runner. Add a provider abstraction with a mock provider first. The job should sample frames from a ready match slot, run detection through the provider, normalize bounding boxes, and store results in video_detections. Start with 1 fps sampling and make it configurable. Add job status updates and error handling. Do not call Roboflow in tests. Add tests using the mock provider. Keep analysis coach/admin-only.
```

---

# Phase 3: Detection overlay in Coach Review

## Goal

Let coaches visually inspect detections over the video before trusting them.

## UX

In Coach Review, add an Analysis Overlay toggle:

- Off
- Players
- Tracks
- Teams
- Confidence

Overlay should render:

- bounding boxes
- optional confidence
- optional track ID
- optional team label

Use a separate canvas or SVG layer from the coaching drawing canvas to avoid corrupting coach-authored drawing metadata.

## Important design choice

Do not mix detection overlays into the existing telestrator drawing schema. Detection overlays are analysis data, not coach-created drawings.

## Acceptance criteria

- Coach can toggle detection overlay on/off.
- Overlay stays aligned with the video at different sizes.
- Overlay updates as video time changes.
- Detection overlay does not save into coaching note drawings unless coach explicitly converts a frame to a note/clip.

## Coding agent prompt

```text
Add a detection overlay to Coach Review. Use stored video_detections and render bounding boxes over the coach review video in a separate overlay layer, not inside the coach drawing payload. Add an Analysis Overlay toggle with modes for players, tracks, teams, and confidence where data exists. Query detections near the current timestamp and update on timeupdate/seek. Ensure overlay alignment survives resize and focus mode. Do not expose this overlay to public match pages or My Feedback yet.
```

---

# Phase 4: Tracking and smoothing

## Goal

Convert frame detections into usable player tracks.

## Tracking approach

Start simple:

- Use ByteTrack, SORT, DeepSORT, or a simple IoU tracker depending on available dependencies.
- Smooth bounding boxes over time.
- Fill short gaps.
- Mark track confidence.
- Keep track IDs stable enough for review, not perfect.

## Outputs

- `video_tracks`
- `track_id` on detections
- per-track duration
- time ranges where track is visible

## Acceptance criteria

- Player boxes persist as tracks across time.
- Short detection gaps do not create excessive new tracks.
- Coach can see track IDs in overlay.
- Bad tracks can be ignored or rejected later.

## Coding agent prompt

```text
Add a tracking stage that converts video_detections into video_tracks and assigns track_id values to detections. Start with a simple IoU/SORT-style tracker or a lightweight dependency if already acceptable for the repo. Smooth boxes over time and bridge short gaps. Store track confidence and start/end times. Add tests for basic track continuity using synthetic detections. Do not attempt roster player identification yet.
```

---

# Phase 5: Detected moments review queue

## Goal

Turn raw detections/tracks into coach-reviewable suggestions.

## Candidate moments

Start with simple heuristics:

- crowded attacking third shape
- set-piece-like clustering
- goalkeeper possession if goalkeeper/team classification exists
- sustained player/ball cluster near box if ball detection exists
- team shape snapshots every N minutes
- high-confidence tactical formation moments

If ball detection is unavailable, avoid overclaiming. Create generic player/shape candidates first.

## Data model

`detected_moments`

Fields:

- `id`
- `job_id`
- `match_id`
- `slot`
- `timestamp_seconds`
- `moment_type`
- `title`
- `confidence`
- `review_status`: new, accepted, rejected, converted_to_note, converted_to_clip
- `metadata_json`

## Coach actions

- accept
- reject
- convert to note
- convert to clip
- jump to timestamp

## Acceptance criteria

- Detections do not automatically become coaching feedback.
- Coach must accept/convert suggestions.
- False positives can be rejected.
- Accepted suggestions can become notes/clips.

## Coding agent prompt

```text
Implement a detected moments review queue. Create detected_moments with match, slot, timestamp, moment_type, title, confidence, review_status, and metadata_json. Generate initial suggestions using conservative heuristics from stored detections/tracks. Add Coach UI to review, jump to timestamp, accept, reject, convert to note, and convert to clip. Do not show detected moments to players automatically. Add tests for status transitions and conversion behavior.
```

---

# Phase 6: Tactical shape snapshots

## Goal

Use detections to help coaches visualize formations and shape.

## Features

- freeze-frame team shape snapshot
- convex hull or formation polygon
- average player positions over a time window
- side-by-side before/after shape moments
- convert snapshot into a coaching note drawing

## Team classification

Start with manual or semi-automatic team labels:

- unknown
- home
- away
- goalkeeper_home
- goalkeeper_away
- referee

Possible classification methods:

1. Manual selection by coach.
2. Kit-color clustering from bounding boxes.
3. Future jersey-number/player identification.

## Acceptance criteria

- Coach can view a shape snapshot at current timestamp.
- Coach can convert snapshot into a note drawing or keep it as analysis overlay.
- Team labels can remain unknown initially.
- No player-facing publication without coach action.

## Coding agent prompt

```text
Add tactical shape snapshots based on stored detections/tracks. At a selected timestamp or time window, compute visible player positions and render a formation-style overlay or convex hull. Keep this as analysis overlay by default, but allow coach to convert the snapshot into a coaching note drawing. Support unknown team labels initially, with optional manual team labeling. Do not require perfect player identification.
```

---

# Phase 7: Player and team heatmaps

## Goal

Summarize where players or teams spend time on the field.

## Important limitation

Raw broadcast/video coordinates are not the same as field coordinates. Accurate heatmaps require field calibration or a homography transform. Without calibration, only video-frame heatmaps are possible.

## MVP approach

Start with video-frame activity maps:

- where detected players appear in the video frame
- useful for camera-centric review, but not true field-position analytics

Later add field calibration:

- coach identifies field corners/lines
- estimate homography
- map player bottom-center points to field coordinates

## Heatmap types

1. Team activity heatmap
2. Track heatmap
3. Player-linked heatmap once tracks are assigned to roster players
4. Zone occupancy summary

## Acceptance criteria

- MVP heatmaps are clearly labeled as video-frame heatmaps if no field calibration exists.
- Field-coordinate heatmaps require calibration.
- Heatmaps are coach/admin-only unless explicitly shared.

## Coding agent prompt

```text
Add heatmap generation from detection/tracking data. Start with video-frame heatmaps and label them clearly as frame-space, not true field-space. Add the data and UI structure so future field calibration can map detections to pitch coordinates. Generate team/track activity maps from stored detections. Do not claim accurate distance or field zones until homography calibration exists.
```

---

# Phase 8: Semi-automatic player identification

## Goal

Let coaches link tracks to roster players.

## Features

- track gallery showing cropped player examples
- coach assigns track to roster player or jersey number
- merge/split track tools for obvious errors
- remember assignments per match

## Future possibilities

- jersey number OCR
- appearance embeddings
- manual first-frame lineup mapping
- integration with formation anchors from Coach Review

## Acceptance criteria

- Coach can manually assign a track to a roster player.
- Assignment is stored and used in overlays, clips, and summaries.
- Track assignment does not affect unrelated matches unless explicitly linked.

## Coding agent prompt

```text
Add semi-automatic player identification for analysis tracks. Create a track assignment UI that shows representative crops for each track and allows a coach to assign the track to a roster player or jersey number. Store assignments per match/slot/job. Show assigned player labels in Coach Review overlays. Add merge/split placeholders only if simple; do not attempt full automatic jersey OCR yet.
```

---

# Phase 9: Player performance metrics

## Goal

Calculate useful player metrics from detection/tracking data.

## Important warning

Physical KPIs such as total distance covered and sprint speed require reliable field calibration, camera model handling, frame rate consistency, and stable identity tracking. Without that, distance/speed numbers can be misleading.

## Recommended metric maturity levels

### Level 1: Safe metrics without field calibration

- visible time in analyzed video
- number of tracked appearances
- average screen position
- involvement in accepted clips
- notes/clips by category
- review completion

### Level 2: Approximate field metrics with calibration

- zone occupancy
- left/right/central tendency
- team shape width/depth estimates
- movement density

### Level 3: Physical KPIs with strong warnings

- estimated total distance
- estimated top speed
- sprint count
- high-intensity movement count

Only expose Level 3 metrics after calibration, validation, and confidence scoring.

## Acceptance criteria

- MVP does not overstate physical accuracy.
- Metrics include confidence labels.
- Field-based metrics require calibration.
- Player-facing metrics are curated by coach, not dumped raw.

## Coding agent prompt

```text
Add player performance metrics in maturity levels. Start with safe non-field-calibrated metrics: visible analyzed time, track appearances, notes/clips by category, involvement in accepted clips, and review completion. Add schema and UI placeholders for calibrated field metrics later. Do not calculate or display distance covered, sprint speed, or heatmap zones as physical truth unless field calibration and identity tracking confidence are available. Include confidence labels and coach/admin-only visibility by default.
```

---

# Phase 10: Broadcast and stat-tag overlays

## Goal

Use detection/tracking data to enhance replay or live viewing with optional overlays.

## Features

Offline replay overlays first:

- highlight selected player
- stat-tag following a player track
- label player by jersey or roster name if assigned
- show team shape overlay
- show possession-like sequence only if ball/team tracking exists

Live overlays later:

- real-time player highlight
- live stat-tags
- possession tracking

## Important limitation

Do not attempt live broadcast overlays until offline detection/tracking is reliable and fast.

## Acceptance criteria

- Overlays are optional and off by default.
- Public viewers do not see experimental overlays unless explicitly enabled.
- Coach/admin can preview overlays first.
- Live overlays are deferred until offline pipeline is stable.

## Coding agent prompt

```text
Add optional replay stat-tag overlays powered by stored tracks. Start offline only. Let a coach select a track/player and show a following label/highlight during replay. Add controls to toggle player highlight, stat-tag label, and team shape overlay. Keep overlays off by default and coach/admin-only initially. Do not implement live overlays until offline analysis is reliable.
```

---

# Phase 11: Live or near-live analysis

## Goal

Eventually support near-live analysis for broadcasts and coaches.

## Requirements before starting

Only start this after:

- offline detection is reliable
- tracking is stable enough
- cost/performance is understood
- model latency is acceptable
- privacy policy is clear
- fallback behavior is good

## Architecture options

1. Near-live sampled analysis
   - sample one frame every 1 to 2 seconds from live HLS/RTMP
   - run detection asynchronously
   - show delayed overlays or coach-only insights

2. Real-time overlay pipeline
   - much harder
   - requires low-latency inference and overlay rendering
   - should be a separate service

## Acceptance criteria

- Live stream remains watchable if analysis fails.
- Analysis never blocks live playback.
- Latency and confidence are visible.
- Experimental overlays can be disabled instantly.

## Coding agent prompt

```text
Design near-live analysis as an optional asynchronous service that never blocks live playback. Sample frames from the live stream at a conservative rate, run detection through the provider abstraction, and store outputs as analysis jobs or live analysis sessions. Expose coach/admin-only delayed overlays first. Include a kill switch and clear latency/confidence indicators. Do not alter the core live streaming pipeline in a way that risks playback reliability.
```

---

# Roboflow integration prompt

Use this only after Phases 1 and 2 exist with a mock provider.

```text
Add a Roboflow detection provider to the existing video analysis provider interface. Use the football players detection model from https://universe.roboflow.com/roboflow-jvuqo/football-players-detection-3zvbc as a configurable candidate model. Do not hard-code secrets. Add environment variables for API key, model identifier, model version, confidence threshold, and max frames per job. Verify license/terms before enabling by default. Keep the mock provider as the default for tests. Normalize Roboflow detections into the video_detections schema. Add robust error handling for rate limits, timeouts, missing credentials, and provider downtime. The app must work when Roboflow is not configured.
```

Suggested environment variables:

```text
REPLAY_ANALYSIS_PROVIDER=mock|roboflow|local_yolo|soccer360_import
ROBOFLOW_API_KEY=
ROBOFLOW_MODEL_ID=football-players-detection-3zvbc
ROBOFLOW_MODEL_VERSION=
ROBOFLOW_CONFIDENCE_THRESHOLD=0.35
REPLAY_ANALYSIS_FRAME_SAMPLE_RATE=1
REPLAY_ANALYSIS_MAX_FRAMES_PER_JOB=600
```

---

# Security and privacy guardrails

This matters because youth sports video may contain minors.

Before sending video frames to a third-party API:

- verify terms of service
- verify whether images are stored by the provider
- verify whether images are used for training
- verify data retention controls
- verify API key security
- add explicit configuration to enable external analysis
- document the privacy tradeoff for admins

Default should be safe:

- analysis disabled unless configured
- mock/local provider for development
- no third-party frame upload unless admin opts in
- no player-facing publication without coach approval

---

# What not to do first

Do not start with:

- real-time possession tracking
- total distance covered
- sprint speed
- live broadcast stat-tags
- automatic player identity recognition
- automatic player-facing feedback publication

Those require reliable tracking, field calibration, and privacy controls.

Start with offline detection, coach-visible overlays, and a human review queue.

---

# Integration with existing roadmaps

Recommended sequence after current Sprint 6:

1. Finish Coach Review UI/UX implementation plan.
2. Complete the manual coaching feature roadmap through at least:
   - structured notes
   - templates
   - thumbnails
   - clip builder
   - player profiles
3. Add AI/video analysis Phase 1 and Phase 2.
4. Add detection overlay and review queue.
5. Add clips from accepted detected moments.
6. Add tactical snapshots and heatmaps.
7. Add player identity and performance metrics later.
8. Add broadcast/live overlays last.

The manual coaching workflow should remain valuable even if AI/video analysis is disabled.
