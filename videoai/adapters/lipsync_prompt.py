"""Prompt cố định cho Copy Động Tác (Flow · Omni 1.2 Flash, Video › Thành phần: video mẫu + ảnh nhân vật).

Đúng prompt người dùng đã chạy thành công trên Flow (chép động tác / vũ đạo). KHÔNG yêu cầu khẩu hình hay lời nói:
chính sách Google không cho tạo hoặc chỉnh sửa lời nói cho người trong video tải lên."""

LIPSYNC_PROMPT = """Use the provided character image and the reference dance video to create a new video.

Replace the dancer in the reference video with the character from the provided image. The character must perform the TikTok dance by closely copying the movement, choreography, poses, gestures, body motion, rhythm, timing, and overall performance of the dancer in the reference video.

Motion reference:

* The reference video is the ONLY source for the character's dance movement.
* Reproduce the dance movement as accurately as possible, frame by frame.
* Preserve the original choreography, movement sequence, timing, rhythm, hand gestures, arm movements, body movements, hip movements, footwork, turns, poses, and transitions from the reference video.
* Do not invent, simplify, exaggerate, or replace any dance movements.
* Do not change the choreography or add additional movements.
* The character should follow the same movement trajectory and timing as the reference dancer throughout the entire performance.

Character identity:

* The character must match the provided reference image exactly.
* Preserve the face, facial features, hairstyle, skin tone, body proportions, clothing, accessories, and overall appearance consistently throughout the video.
* Do not change, morph, distort, or reinterpret the character's identity or outfit.
* The character's appearance must remain stable from the beginning to the end of the video.

TikTok dance style:

* Preserve the energetic, rhythmic, expressive performance style of the original TikTok dance.
* Match the dancer's tempo, body isolation, gestures, poses, attitude, and performance energy.
* Keep the movement natural and physically believable.
* Maintain accurate human body mechanics and realistic joint movement.

Video continuity:

* Create one continuous shot with no scene cuts.
* Keep the camera movement and framing consistent with the reference video unless otherwise specified.
* Do not change the environment or introduce additional characters or objects.
* No sudden camera changes, scene transitions, morphing, duplicated limbs, extra fingers, broken anatomy, floating body parts, or unnatural movement.

The final video should look like the character from the provided image is actually performing the exact TikTok dance from the reference video, while preserving the character's identity and appearance throughout the entire performance.
The reference video controls the motion. The reference image controls the character identity. Do not mix or reinterpret these roles.
Movement fidelity has the highest priority: when there is any conflict between creative interpretation and the reference dance, always follow the reference dance movement precisely."""
