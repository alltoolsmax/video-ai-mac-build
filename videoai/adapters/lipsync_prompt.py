"""Prompt cố định cho Video Lip-Sync (Flow · Omni 1.2 Flash, chế độ Video › Thành phần: video gốc + ảnh nhân vật).
Dựa trên prompt người dùng đã chạy thành công 100%, mở rộng cho khẩu hình / biểu cảm và không tạo âm thanh mới
(tiếng gốc của video được ghép lại sau khi tạo)."""

LIPSYNC_PROMPT = """Use the provided character image and the reference video to create a new video.

Replace the person in the reference video with the character from the provided image. The character must perform exactly what the person in the reference video does: copy the lip movements, mouth shapes, facial expressions, head movement, gestures, body motion, rhythm, timing, and overall performance as closely as possible.

Motion and performance reference:
* The reference video is the ONLY source for the character's movement and performance.
* Reproduce the performance as accurately as possible, frame by frame, for the full length of the video.
* Preserve the original timing, rhythm, gestures, hand and arm movements, body movements, head turns, poses, and transitions.
* Do not invent, simplify, exaggerate, or replace any movement. Do not add extra movements.
* The character must follow the same movement trajectory and timing as the reference person throughout the entire video.

Lip-sync and facial performance:
* Match the lip movements and mouth shapes of the reference person exactly, syllable by syllable, with the same timing, so the character appears to be saying or singing exactly the same words.
* Copy the jaw movement, mouth opening, teeth and tongue visibility, blinking, eye direction, eyebrow movement, and facial expressions frame by frame.
* Keep the mouth fully visible and sharp whenever it is visible in the reference video.
* Do not add talking, mouth movement, or expressions that are not in the reference video, and do not freeze the mouth while the reference person is speaking or singing.

Character identity:
* The character must match the provided reference image exactly.
* Preserve the face, facial features, hairstyle, skin tone, body proportions, clothing, accessories, and overall appearance consistently throughout the video.
* Do not change, morph, distort, or reinterpret the character's identity or outfit.
* The character's appearance must remain stable from the beginning to the end of the video.

Performance style:
* Preserve the energy, attitude, emotion, and expressiveness of the original performance.
* Keep the movement natural and physically believable, with accurate human body mechanics and realistic joint movement.

Video continuity:
* Create one continuous shot with no scene cuts.
* Keep the camera movement, framing, and shot size consistent with the reference video.
* Do not change the environment or introduce additional characters or objects.
* No sudden camera changes, scene transitions, morphing, duplicated limbs, extra fingers, broken anatomy, floating body parts, or unnatural movement.

Audio:
* Do not generate new dialogue, new lyrics, narration, or music. The original audio of the reference video will be added afterwards, so the lip movements must follow the original speech or singing exactly.

The final video should look like the character from the provided image is actually performing the exact performance from the reference video, with perfectly matching lip movements, while preserving the character's identity and appearance throughout.
The reference video controls the motion, facial expressions, and lip movements. The reference image controls the character identity. Do not mix or reinterpret these roles.
Movement and lip-sync fidelity have the highest priority: when there is any conflict between creative interpretation and the reference video, always follow the reference video precisely."""
